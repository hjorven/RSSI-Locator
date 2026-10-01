#!/usr/bin/env python3
"""Simulierte Nodes: schickt erfundene Messwerte an /ingest.

Damit lässt sich der ganze Server ohne Hardware testen. Die Ziele laufen auf
Zufallsbahnen durch den Raum, addätzlichem Rauschen und einem gelegentlichen
"Aussetzer" (Gerät nicht mehr sichtbar), damit Filter und "zuletzt gesehen"
sichtbar arbeiten.

    python3 tools/simulate_nodes.py --url http://127.0.0.1:8099/ingest
    python3 tools/simulate_nodes.py --devices 8 --hz 2 --speed 2

Die Geometrie wird beim Server erfragt, damit Simulator und Server dasselbe
rechnen. Für Nodes, die der Server noch nicht kennt, legt er sie nach dem
gleichen Muster selbst fest. Abweichungen lassen sich mit `--node-position
ID:X,Y` erzwingen.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
import urllib.error
import urllib.request

# Funkraum für die Simulation: 6 m x 4 m, Node A bei (0,0), Node B bei (D,0).
NAMES_BLE = ["tag1", "schluessel", "kopfhoerer", "beacon-01", "sensor-kueche"]
NAMES_WIFI = ["FRITZ!Box", "WLAN-Gast", "Nachbar-2.4"]


def fetch_layout(url: str) -> tuple[dict, float]:
    """Fragt die tatsächliche Node-Geometrie beim Server ab.

    Liefert (Positionen je Node-ID, Nodeabstand). Der Server legt die ersten
    beiden Nodes auf die Basislinie und weitere auf die y-Achse; rechnet der
    Simulator mit einer anderen Annahme, sind alle erwarteten Positionen
    systematisch verschoben. Noch nicht bekannte Nodes bekommen einen
    Platzhalter, bis der Server sie kennt.
    """
    state = url[: url.rindex("/")] + "/api/state" if "/ingest" in url else url + "/api/state"
    try:
        with urllib.request.urlopen(state, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        pos = {n["id"]: (float(n["x"]), float(n["y"])) for n in data.get("nodes", [])}
        return pos, float(data["settings"]["node_distance"])
    except Exception:                                   # noqa: BLE001
        return {}, 4.0


def layout_for(node_ids: list[str], known: dict, node_distance: float) -> dict:
    """Node-Positionen, mit den vom Server gemeldeten wo vorhanden."""
    pos = {}
    for i, nid in enumerate(node_ids):
        if nid in known:
            pos[nid] = known[nid]
        elif i == 0:
            pos[nid] = (0.0, 0.0)
        elif i == 1:
            pos[nid] = (node_distance, 0.0)
        else:
            pos[nid] = (0.0, node_distance * (i - 1))
    return pos


def post_json(url: str, payload: dict, timeout: float = 2.0) -> bool:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError) as exc:
        print(f"Fehler beim Senden: {exc}", flush=True)
        return False


class Target:
    """Ein simuliertes Gerät, das auf einer weichen Zufallsbahn läuft."""

    def __init__(self, name: str, kind: str, x0: float, y0: float) -> None:
        self.name = name
        self.kind = kind
        self.x, self.y = x0, y0
        self.tx, self.ty = x0, y0
        self.speed = random.uniform(0.15, 0.45)
        self.visible = True

    def step(self, dt: float, t: float) -> None:
        # Ziel wanderlangsam Richtung tx,ty und sucht sich gelegentlich ein neues Ziel.
        if math.hypot(self.tx - self.x, self.ty - self.y) < 0.2:
            self.tx = random.uniform(0.2, 5.8)
            self.ty = random.uniform(0.2, 3.8)
        ang = math.atan2(self.ty - self.y, self.tx - self.x)
        ang += random.uniform(-0.4, 0.4)
        self.x += math.cos(ang) * self.speed * dt
        self.y += math.sin(ang) * self.speed * dt
        # gelegentlich außerhalb der Funkreichweite -> Gerät fällt weg
        if random.random() < 0.004:
            self.visible = not self.visible


def rssi_at(dist: float, rssi_1m: float, path_loss: float) -> int:
    return int(round(rssi_1m - 10.0 * path_loss * math.log10(max(dist, 0.2))))


def mac_for(name: str) -> str:
    raw = 0x001A2B3C0000 ^ (hash(name) & 0xFFFFFF)
    return ":".join(f"{(raw >> (8 * i)) & 0xFF:02X}" for i in range(5, -1, -1))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fake-Nodes für den RSSI-Locator")
    ap.add_argument("--url", default="http://127.0.0.1:8099/ingest")
    ap.add_argument("--nodes", default="A,B", help="Node-IDs, kommagetrennt")
    ap.add_argument(
        "--node-position",
        action="append",
        default=[],
        metavar="ID:X,Y",
        help="Position eines Nodes fest vorgeben, z. B. --node-position A:0,0. "
             "Ohne diese Angaben wird das Layout beim Server erfragt.",
    )
    ap.add_argument("--devices", type=int, default=5)
    ap.add_argument("--hz", type=float, default=1.0, help="Sendrate je Node")
    ap.add_argument("--speed", type=float, default=1.0, help="Zeitraffer der Bewegung")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    node_ids = [n.strip() for n in args.nodes.split(",") if n.strip()]
    fest = {}
    for angabe in args.node_position:
        nid, _, xy = angabe.partition(":")
        if not xy:
            ap.error(f"--node-position braucht ID:X,Y, bekam {angabe!r}")
        try:
            x, y = (float(v) for v in xy.split(","))
        except ValueError:
            ap.error(f"--node-position {angabe!r}: X und Y müssen Zahlen sein")
        fest[nid.strip()] = (x, y)
    known, node_distance = fetch_layout(args.url)
    fest.update({k: v for k, v in known.items() if k in fest})   # CLI schlägt Server
    node_pos = layout_for(node_ids, fest, node_distance)

    targets: list[Target] = []
    for i in range(args.devices):
        kind = "ble" if i % 2 == 0 else "wifi"
        pool = NAMES_BLE if kind == "ble" else NAMES_WIFI
        name = pool[i // 2] if (i // 2) < len(pool) else f"{kind}{i}"
        targets.append(Target(name, kind, random.uniform(0.3, 5.5), random.uniform(0.3, 3.5)))

    rssi_1m = {"ble": -59.0, "wifi": -45.0}
    path_loss = {"ble": 2.5, "wifi": 3.0}

    print(f"Sende {len(node_ids)} Nodes an {args.url}, {args.hz:.1f} Hz", flush=True)
    print("  Node-Layout: " + ", ".join(f"{n}=({node_pos[n][0]:.2f},{node_pos[n][1]:.2f})"
                                        for n in node_ids), flush=True)
    interval = 1.0 / max(0.1, args.hz)
    last = time.time()
    t0 = last
    while True:
        now = time.time()
        dt = min(1.0, (now - last)) * args.speed
        last = now
        for target in targets:
            target.step(dt, now - t0)

        for nid in node_ids:
            nx, ny = node_pos[nid]
            payload = {"node": nid, "ts": int(now), "ble": [], "wifi": []}
            for t in targets:
                if not t.visible:
                    continue
                dist = math.hypot(t.x - nx, t.y - ny)
                rssi = rssi_at(dist, rssi_1m[t.kind], path_loss[t.kind])
                rssi += random.gauss(0, 4.0)
                if random.random() < 0.02:
                    rssi -= random.uniform(5, 15)  # gelegentlicher Ausreißer
                if t.kind == "ble":
                    payload["ble"].append({"mac": mac_for(t.name), "name": t.name, "rssi": int(rssi)})
                else:
                    payload["wifi"].append(
                        {"ssid": t.name, "bssid": mac_for(t.name), "rssi": int(rssi)}
                    )
            if not post_json(args.url, payload):
                pass
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("beendet")
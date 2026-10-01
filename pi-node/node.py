"""Node-Client fuer Linux, getestet auf dem Raspberry Pi 4 B.

Gleiches Datenformat wie die MicroPython-Firmware in firmware/node/main.py, damit
Server, Simulator und Weboberflaeche unveraendert damit arbeiten koennen.

Der Raspberry Pi 4 B hat beide Funkmodule an Bord: WLAN (wlan0) und Bluetooth
(hci0). Der WLAN-Vollscan liefert ueber `iw` echte dBm-Werte, der BLE-Scan ueber
`bleak`. `iw` braucht CAP_NET_ADMIN, bleak laeuft ohne Root.

Ablauf eines Zyklus: scannen -> senden -> kurze Pause. WLAN- und BLE-Scan
wechseln sich ab, weil ein `iw scan` die Schnittstelle fuer mehrere Sekunden
belegt und dann der Server laenger keine Daten bekommt. Beide Puffer werden bei
jedem POST mitgeschickt, damit der Server zu jedem Zeitpunkt Messwerte hat.

Der Pi haengt am Ethernet und funkt nur wlan0 zum Messen, deshalb ist keine
WLAN-Konfiguration und kein Passwort noetig — anders als auf dem Pico.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"

#: Alles Schwächere ist Rauschen und verwirft die Glättung des Servers.
RSSI_FLOOR = -95

_BSS_RE = re.compile(r"^BSS ([0-9a-fA-F:]{17})")
_SIGNAL_RE = re.compile(r"^\s*signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_SSID_RE = re.compile(r"^\s*SSID:\s*(.*)$")
_FLAGS_RE = re.compile(r"<([^>]*)>")


def log(msg: str) -> None:
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# ---------------------------------------------------------------------------
# WLAN
# ---------------------------------------------------------------------------


def parse_iw_scan(text: str) -> list[tuple[str, str, int]]:
    """Ausgabe von ``iw dev wlan0 scan`` in (ssid, bssid, rssi) zerlegen.

    Ein BSS-Block beginnt mit ``BSS <mac>(on wlan0)``, gefolgt von Zeilen wie
    ``signal: -45.00 dBm`` und ``SSID: Name``. Verborgene APs haben keine
    SSID-Zeile; sie werden über die BSSID erfasst, der Server nutzt sie ohnehin
    als Schlüssel. Ergebnisse unterhalb von `RSSI_FLOOR` fliegen raus.
    """
    out: list[tuple[str, str, int]] = []
    bssid = None
    rssi: float | None = None
    ssid = ""
    for line in text.splitlines():
        match = _BSS_RE.match(line)
        if match:
            if bssid and rssi is not None and rssi >= RSSI_FLOOR:
                out.append((ssid, bssid.upper(), int(round(rssi))))
            bssid, rssi, ssid = match.group(1), None, ""
            continue
        if bssid is None:
            continue
        match = _SIGNAL_RE.match(line)
        if match and rssi is None:
            rssi = float(match.group(1))
            continue
        match = _SSID_RE.match(line)
        if match and not ssid:
            ssid = match.group(1).strip()
    if bssid and rssi is not None and rssi >= RSSI_FLOOR:
        out.append((ssid, bssid.upper(), int(round(rssi))))
    return out


def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", "%s fehlt" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "Zeitueberschreitung nach %.0f s" % timeout
    return proc.returncode, proc.stdout, proc.stderr


def iface_is_up(iface: str) -> bool:
    code, out, _ = _run(["ip", "-o", "link", "show", iface], 5.0)
    if code != 0:
        return False
    match = _FLAGS_RE.search(out)
    return bool(match and "UP" in match.group(1).split(","))


def set_iface(iface: str, up: bool) -> bool:
    code, _, err = _run(["ip", "link", "set", iface, "up" if up else "down"], 10.0)
    if code != 0:
        log("Schnittstelle %s nicht %s: %s" % (iface, "hoch" if up else "runter", err.strip()))
    return code == 0


def scan_wifi(iface: str, timeout: float = 15.0) -> list[tuple[str, str, int]]:
    code, out, err = _run(["iw", "dev", iface, "scan"], timeout)
    if code != 0:
        log("WLAN-Scan fehlgeschlagen: %s" % (err.strip() or "unbekannt"))
        return []
    return parse_iw_scan(out)


# ---------------------------------------------------------------------------
# BLE
# ---------------------------------------------------------------------------


async def _ble_scan(timeout: float) -> list[tuple[str, int, str]]:
    from bleak import BleakScanner

    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    out = []
    for addr, entry in found.items():
        # bleak liefert je nach Version ein Tupel (Gerät, Werbedaten) oder nur
        # die Werbedaten.
        adv = entry[1] if isinstance(entry, tuple) else entry
        rssi = getattr(adv, "rssi", None)
        if rssi is None or rssi < RSSI_FLOOR:
            continue
        name = (getattr(adv, "local_name", None) or "").strip()
        out.append((addr.upper(), int(round(rssi)), name))
    return out


def scan_ble(timeout: float) -> list[tuple[str, int, str]]:
    try:
        return asyncio.run(_ble_scan(timeout))
    except ImportError:
        log("BLE aus: bleak fehlt (pi-node/install.sh installiert es)")
    except Exception as exc:  # Adapter weg, busy, kein Permission
        log("BLE-Scan fehlgeschlagen: %s" % exc)
    return []


# ---------------------------------------------------------------------------
# Senden
# ---------------------------------------------------------------------------


def build_payload(node: str, ble: list, wifi: list, ts: int) -> dict:
    """Payload in der Form, die der Server unter /ingest erwartet."""
    return {
        "node": node,
        "ts": ts,
        "ble": [{"mac": mac, "rssi": rssi, "name": name} for mac, rssi, name in ble],
        "wifi": [
            {"ssid": ssid, "bssid": bssid, "rssi": rssi} for ssid, bssid, rssi in wifi
        ],
    }


def post_json(url: str, payload: dict, timeout: float = 4.0) -> bool:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        log("Server lehnt ab: HTTP %d" % exc.code)
    except (urllib.error.URLError, OSError) as exc:
        log("Senden fehlgeschlagen: %s" % exc)
    return False


# ---------------------------------------------------------------------------
# Hauptzyklus
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="RSSI-Locator Node fuer Linux")
    parser.add_argument("--node", default="A", help="Node-Kennung, z. B. A")
    parser.add_argument("--iface", default="wlan0", help="WLAN-Schnittstelle")
    parser.add_argument("--url", default="http://192.168.178.43:8099/ingest")
    parser.add_argument("--ble-timeout", type=float, default=5.0)
    parser.add_argument(
        "--wifi-every", type=int, default=2, help="WLAN-Scan alle n Zyklen"
    )
    parser.add_argument("--no-ble", action="store_true", help="kein BLE-Scan")
    parser.add_argument("--once", action="store_true", help="nur einen Zyklus")
    args = parser.parse_args()

    log("Node %s, Version %s, Ziel %s" % (args.node, VERSION, args.url))
    if not args.ble_timeout or args.no_ble:
        args.ble_timeout = 0.0

    bringe_selbst_hoch = not iface_is_up(args.iface)
    if bringe_selbst_hoch:
        if not set_iface(args.iface, True):
            log(
                "FEHLER: %s laesst sich nicht hochfahren. Braucht CAP_NET_ADMIN, "
                "siehe pi-node/rssi-node.service." % args.iface
            )
            return 1
        log("Schnittstelle %s war aus und wurde hochgefahren" % args.iface)

    stop = False

    def beenden(*_args) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, beenden)
    signal.signal(signal.SIGINT, beenden)

    ble_buffer: list = []
    wifi_buffer: list = []
    zyklus = 0
    try:
        while not stop:
            begonnen = time.time()
            zyklus += 1

            if args.ble_timeout > 0 and zyklus % 2 == 1:
                treffer = scan_ble(args.ble_timeout)
                if treffer:
                    ble_buffer = treffer
            if zyklus % max(1, args.wifi_every) == 0:
                aps = scan_wifi(args.iface)
                if aps:
                    wifi_buffer = aps

            payload = build_payload(args.node, ble_buffer, wifi_buffer, int(begonnen))
            ok = post_json(args.url, payload)
            log(
                "Zyklus %d: %d BLE, %d WLAN, gesendet %s"
                % (zyklus, len(ble_buffer), len(wifi_buffer), "ok" if ok else "nein")
            )
            if args.once:
                return 0 if ok else 1
            # Bei Fehlern nicht sofort wieder scannen: dann wartet der Server
            # vergeblich auf Daten, die der Node noch gar nicht gesammelt hat.
            if not ok:
                time.sleep(2.0)
    finally:
        if bringe_selbst_hoch:
            set_iface(args.iface, False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

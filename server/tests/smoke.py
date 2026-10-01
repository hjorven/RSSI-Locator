"""Kurzer End-to-End-Rauchtest gegen einen laufenden Server.

Startet den Simulator für wenige Sekunden und prüft, ob über /api/state
Geräte mit Positionen auftauchen.

    python3 server/tests/smoke.py http://127.0.0.1:8099

Der Simulator läuft mit eigenen Node-IDs (`TEST-A`, `TEST-B`), damit er die
Messreihen der echten Nodes nicht verfälscht. Seine Geräte verschwinden nach
`drop_after` (2 min) von selbst.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "simulate_nodes.py"
TEST_NODES = ("TEST-A", "TEST-B")


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read().decode())


async def check_websocket(base: str, messages: int = 3) -> None:
    """Der Browser bekommt seine Daten ueber /ws — das muss geprueft werden."""
    import websockets

    uri = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
    async with websockets.connect(uri, open_timeout=5) as ws:
        for _ in range(messages):
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            payload = json.loads(raw)
            assert "devices" in payload and "nodes" in payload, payload.keys()
            assert "settings" in payload
        print(f"WebSocket ok: {messages} Snapshots empfangen, "
              f"{len(payload['devices'])} Geräte im letzten")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099").rstrip("/")
    print("healthz:", get_json(base + "/healthz"))
    proc = subprocess.Popen(
        [
            sys.executable,
            str(TOOLS),
            "--url",
            base + "/ingest",
            "--speed",
            "3.0",
            "--nodes",
            ",".join(TEST_NODES),
        ]
    )
    try:
        asyncio.run(check_websocket(base))
        deadline = time.time() + 12
        while time.time() < deadline:
            time.sleep(1.0)
            state = get_json(base + "/api/state")
            # Nur die Test-Geräte zählen: die echten Nodes liefern laufend Daten,
            # sonst wäre der Test schon gruen, bevor der Simulator sendet.
            test_geraete = [
                d
                for d in state["devices"]
                if {s["node"] for s in d["sources"]} >= set(TEST_NODES)
            ]
            positioned = [d for d in test_geraete if d["ok"]]
            print(
                f"nodes={len(state['nodes'])} devices={len(state['devices'])} "
                f"testgeraete={len(test_geraete)} "
                f"positioniert={len(positioned)} "
                f"konsistent={sum(1 for d in positioned if d['consistent'])}"
            )
            if positioned:
                for d in positioned[:3]:
                    quellen = [(s["node"], s["rssi"], s["dist"]) for s in d["sources"]]
                    print(f"  {d['label']}: ({d['x']}, {d['y']}) m  ±{d['rx']}/{d['ry']} m  {quellen}")
                print("OK: Geräte werden positioniert.")
                return 0
        print("FEHLER: keine positionierten Testgeräte gesehen")
        return 1
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
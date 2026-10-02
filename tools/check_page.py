"""Prueft die Weboberflaeche im echten Browser (headless Chrome + CDP).

Startet Chrome mit Remote-Debugging, laedt die Seite, wartet auf echte
WebSocket-Daten und liest danach Tabelle und Canvas aus.

    python3 tools/check_page.py http://192.168.1.20:8099
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME_CANDIDATES = [
    "/var/home/jorven/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome",
    "chromium",
    "google-chrome",
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists() or subprocess.run(
            ["which", candidate], capture_output=True
        ).returncode == 0:
            return candidate
    raise SystemExit("kein Chrome/Chromium gefunden")


async def evaluate(cdp_url: str, expression: str, timeout: float = 15.0):
    """Wertet JavaScript in der Seite aus und wartet auf ein wahres Ergebnis."""
    async with websockets.connect(cdp_url, max_size=8 * 1024 * 1024) as ws:
        await ws.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "awaitPromise": True,
                        "returnByValue": True,
                    },
                }
            )
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - time.time()))
            msg = json.loads(raw)
            if msg.get("id") == 1:
                return msg["result"]["result"].get("value")
    raise TimeoutError("kein Ergebnis vom Browser")


WAIT_SCRIPT = """
(async () => {
  const warten = (ms) => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 100; i++) {
    if (window.state && window.state.devices.length) break;
    await warten(200);
  }
  const rows = [...document.querySelectorAll('#devbody tr')].map(tr =>
    [...tr.querySelectorAll('td')].map(td => td.textContent.trim()));
  const canvas = document.getElementById('canvas');
  const ctx = canvas.getContext('2d');
  const px = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  let gezeichnet = 0;
  for (let i = 0; i < px.length; i += 4000) if (px[i] !== 0 || px[i+1] !== 0) gezeichnet++;
  return JSON.stringify({
    ws: document.getElementById('wstxt').textContent,
    nodes: document.getElementById('nodecount').textContent,
    settings: window.state ? window.state.settings.node_distance : null,
    devices: window.state ? window.state.devices.length : 0,
    rows: rows,
    canvasBreite: canvas.width,
    canvasHoehe: canvas.height,
    gezeichnetePixel: gezeichnet
  });
})()
"""


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099").rstrip("/")
    chrome = find_chrome()
    profile = tempfile.mkdtemp(prefix="chrome-rssi-")
    proc = subprocess.Popen(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--window-size=1500,900",
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}",
            base + "/",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        cdp_url = None
        for _ in range(40):
            time.sleep(0.5)
            try:
                with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2) as r:
                    targets = json.loads(r.read().decode())
            except Exception:
                continue
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                cdp_url = pages[0]["webSocketDebuggerUrl"]
                break
        if not cdp_url:
            print("FEHLER: Chrome-DevTools nicht erreichbar")
            return 1
        raw = asyncio.run(evaluate(cdp_url, WAIT_SCRIPT))
        if not raw:
            print("FEHLER: Seite lieferte kein Ergebnis (JS-Fehler?)")
            return 1
        data = json.loads(raw)
        print("WebSocket:      ", data["ws"])
        print("Nodes:          ", data["nodes"])
        print("D aus Server:   ", data["settings"])
        print("Geräte (JSON):  ", data["devices"])
        print("Canvas:         ", f"{data['canvasBreite']}x{data['canvasHoehe']}",
              f", {data['gezeichnetePixel']} geprüfte Pixel != schwarz")
        for row in data["rows"]:
            print("   ", " | ".join(row))
        if data["ws"] != "verbunden":
            print("FEHLER: WebSocket nicht verbunden")
            return 1
        if not data["devices"] or not data["rows"]:
            print("FEHLER: keine Geräte in der Oberfläche")
            return 1
        if data["gezeichnetePixel"] == 0:
            print("FEHLER: Canvas bleibt leer")
            return 1
        print("\nOK: Weboberfläche zeigt Daten und zeichnet die Karte.")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
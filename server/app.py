"""RSSI-Locator Server: /ingest (Nodes), /ws (Browser), /api/settings.

Daten liegen ausschließlich im Arbeitsspeicher, es gibt keine Datenbank.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from positioning import Locator

log = logging.getLogger("rssi")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PUSH_HZ = float(os.environ.get("PUSH_HZ", "2"))

app = FastAPI(title="RSSI-Locator", docs_url=None, redoc_url=None)
locator = Locator()

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Datenmodelle für /ingest
# ---------------------------------------------------------------------------


class BleEntry(BaseModel):
    mac: str
    rssi: int
    name: Optional[str] = None


class WifiEntry(BaseModel):
    bssid: str
    rssi: int
    ssid: Optional[str] = None


class Ingest(BaseModel):
    node: str = Field(min_length=1, max_length=16)
    ts: Optional[float] = None
    ble: List[BleEntry] = Field(default_factory=list)
    wifi: List[WifiEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP-Endpunkte
# ---------------------------------------------------------------------------


@app.post("/ingest")
async def ingest(payload: Ingest) -> JSONResponse:
    """Ein Messdatensatz eines Nodes. Antwort ist bewusst winzig: die Nodes
    pollen häufig und sollen möglichst wenig Traffic und Speicher brauchen."""
    now = time.time()
    locator.ingest(
        payload.node,
        [e.model_dump() for e in payload.ble],
        [e.model_dump() for e in payload.wifi],
        now=now,
    )
    locator.recompute()
    return JSONResponse({"ok": True, "server_ts": now})


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "uptime": round(time.time() - locator.started, 1),
        "nodes": len(locator.nodes),
        "devices": len(locator.devices),
        "dropped": locator.dropped,
    }


async def housekeeping() -> None:
    """Räumt auch dann auf, wenn kein Node mehr sendet.

    Ohne diesen Takt bleiben Geräte endgültig stehen, sobald die Nodes
    ausfallen, und der Online-Status würde einfrieren.
    """
    while True:
        await asyncio.sleep(1.0)
        try:
            locator.expire()
        except Exception:  # pragma: no cover - darf den Dienst nie killen
            log.exception("Aufräumen fehlgeschlagen")


@app.get("/api/state")
async def state() -> dict:
    return locator.snapshot()


@app.post("/api/settings")
async def update_settings(values: dict) -> dict:
    """Parameter der Positionsschätzung ändern (D, RSSI_1m, n, Filter)."""
    before = locator.settings.to_dict()
    locator.settings.update(values)
    after = locator.settings.to_dict()
    changed = [k for k in after if after[k] != before[k]]
    if changed:
        # Kalibrierwerte wirken erst nach Neuaufbau der Historie sauber,
        # deshalb verwerfen wir die Puffer bei relevanten Änderungen.
        reset_keys = ("rssi_window",)
        if any(k in reset_keys for k in changed):
            for device in locator.devices.values():
                for src in device.sources.values():
                    src.filter.set_window(after["rssi_window"])
        log.info("Settings geändert: %s", changed)
    locator.recompute()
    return {"ok": True, "settings": after, "changed": changed}


@app.post("/api/reset")
async def reset() -> dict:
    """Alle Geräte und Filter verwerfen (Neukalibrierung)."""
    locator.devices.clear()
    locator.nodes.clear()
    return {"ok": True}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# WebSocket-Push
# ---------------------------------------------------------------------------


class Hub:
    """Verwaltet verbundene Browser und schickt den Zustand mit fester Rate."""

    def __init__(self, hz: float = PUSH_HZ) -> None:
        self.clients: set[WebSocket] = set()
        self.hz = max(0.2, hz)
        self._task: Optional[asyncio.Task] = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _run(self) -> None:
        interval = 1.0 / self.hz
        while True:
            try:
                payload = json.dumps(locator.snapshot())
            except Exception:  # pragma: no cover - Snapshot sollte nie werfen
                log.exception("Snapshot fehlgeschlagen")
                await asyncio.sleep(interval)
                continue
            dead = []
            for ws in list(self.clients):
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.clients.discard(ws)
            await asyncio.sleep(interval)

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


hub = Hub()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            # Der Browser sendet nichts; Lesen dient nur dem Erkennen geschlossener Sockets.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.disconnect(ws)


@app.on_event("startup")
async def on_startup() -> None:
    housekeeping_task = asyncio.create_task(housekeeping())
    log.info("RSSI-Locator gestartet, Push mit %.1f Hz", PUSH_HZ)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    housekeeping_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await housekeeping_task
    await hub.shutdown()
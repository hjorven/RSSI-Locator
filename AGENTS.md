# AGENTS.md — RSSI-Locator

Projekt: Zwei Raspberry Pi Pico 2 W messen RSSI von BLE-Geräten und Access Points und
schicken die Messwerte per HTTP an einen Raspberry Pi 4 B. Der Server schätzt die
Positionen und zeigt sie auf einer Webseite live an.

## Umgebung

| Ort | Rolle |
|-----|-------|
| Bazzite (Host) | Entwicklung, Pico per USB (`mpremote`) |
| Raspberry Pi 4 B, `192.168.178.43`, User `pi` | Server-Betrieb (venv + systemd, Port 8099) |

Der gemeldete Pico am USB-Port ist ein **Pico 2 ohne WLAN**, geflasht mit CircuitPython.
Die Firmware in `firmware/` ist für **Pico 2 W + MicroPython** geschrieben und wird
erst nutzbar, wenn ein echtes Pico 2 W-Board geflasht wird.

## Harte Regeln

- Erst Phase 1 (Server + Simulator) testen, Hardware danach. Kein Refactoring ohne
  laufende Tests.
- Jede Berechnung in `server/positioning.py` braucht einen Unit-Test in `server/tests/`.
  Tests müssen ohne Server laufen: `pytest server/tests`.
- Server: Python 3, FastAPI + uvicorn, **keine Datenbank**, Daten nur im Arbeitsspeicher,
  keine schweren Abhängigkeiten (kein numpy, kein scipy).
- Firmware: MicroPython, Konfiguration ausschließlich in `firmware/common/config.py`.
  `config.py` ist in `.gitignore`, `config.example.py` wird eingecheckt. Keine
  WLAN-Passwörter ins Git.
- Kommentare, Docstrings und Doku auf Deutsch.
- Kein Docker auf dem Pi (1,8 GB RAM, andere Dienste laufen) — Deployment per venv +
  systemd, siehe `deploy/`.

## Server-Start lokal

```bash
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8099
```

## Simulator

```bash
.venv/bin/python tools/simulate_nodes.py --url http://192.168.178.43:8099/ingest
```

## Prüfwerkzeuge

| Befehl | Prüft |
|--------|-------|
| `python3 server/tests/test_positioning.py` | Rechnung, ohne Server und ohne pytest |
| `server/.venv/bin/python server/tests/smoke.py <URL>` | Ingest, WebSocket, Positionierung |
| `server/.venv/bin/python tools/check_page.py <URL>` | Weboberfläche in headless Chrome |

Nach jeder Änderung an `server/positioning.py` mindestens den ersten Befehl,
nach Änderungen an `server/app.py` oder `static/index.html` alle drei.

## Deployment

```bash
bash deploy/deploy.sh          # rsync + venv + systemd restart auf dem Pi
bash deploy/deploy.sh logs     # systemctl logs folgen
```

## Datenformat Node → Server

```json
{"node": "A", "ts": 1727800000,
 "ble": [{"mac": "AA:BB:CC:DD:EE:FF", "name": "tag1", "rssi": -63}],
 "wifi": [{"ssid": "FRITZ!Box", "bssid": "11:22:33:44:55:66", "rssi": -48}]}
```

Der Server stempelt die Zeit selbst — Pico-Uhren sind unzuverlässig.

## Qualität

- Vor jedem Abschluss: `pytest server/tests` und ein manueller Test
  (`/healthz`, Simulator, WebSocket-Push).
- Keine Kommentare, die nur Code erklären. Kommentare nur, wenn *warum* nicht offensichtlich ist.
- Skalare Einheiten: alle Längen in **Metern**, RSSI in **dBm**, Zeiten in **Sekunden (Unix)**.
# AGENTS.md — RSSI-Locator

Projekt: Zwei Raspberry Pi Pico 2 W messen RSSI von BLE-Geräten und Access Points und
schicken die Messwerte per HTTP an einen Raspberry Pi 4 B. Der Server schätzt die
Positionen und zeigt sie auf einer Webseite live an. Aktuell läuft Node A auf einem
Pico 2 W, Node B auf dem Pi 4 B selbst (`pi-node/`).

## Umgebung

| Ort | Rolle |
|-----|-------|
| Bazzite (Host) | Entwicklung, Pico 2 W per USB (`mpremote`) |
| Raspberry Pi 4 B, `192.168.178.43`, User `pi` | Server-Betrieb (venv + systemd, Port 8099) **und** Node B (`rssi-node`) |

Node A ist der **Pico 2 W** mit MicroPython 1.29.0 (`firmware/`), Node B der
Linux-Node `pi-node/` auf dem Pi 4 B.

Vorsicht bei der Hardware-Erkennung: `os.uname().machine` nennt die
kompilierte Firmware, nicht die Platine. Auf diesem Board lief kurzzeitig die
CircuitPython-Build `RASPBERRYPI_PICO2` (ohne Funk) auf einem Pico 2 W und meldete
sich dadurch als "Pico 2" ganz ohne `network`. Verbindlich ist nur, was nach dem
Flashen von `RPI_PICO2_W` da ist, siehe `docs/hardware.md`.

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
- Linux-Node (`pi-node/`): nur Standardbibliothek, `bleak` als einzige Abhängigkeit.
  Konfiguration über Argumente und `Environment=` in `pi-node/rssi-node.service`,
  keine eigene Config-Datei und keine Zugangsdaten (der Pi hängt am Ethernet).
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
| `python3 pi-node/test_node.py` | Parser des Linux-Nodes, ohne Funk und ohne pytest |
| `server/.venv/bin/python server/tests/smoke.py <URL>` | Ingest, WebSocket, Positionierung |
| `server/.venv/bin/python tools/check_page.py <URL>` | Weboberfläche in headless Chrome |

Nach jeder Änderung an `server/positioning.py` mindestens den ersten Befehl,
nach Änderungen an `pi-node/node.py` den zweiten, nach Änderungen an
`server/app.py` oder `static/index.html` alle vier.

## Deployment

```bash
bash deploy/deploy.sh          # rsync + venv + systemd restart auf dem Pi
bash deploy/deploy.sh logs     # systemctl logs folgen
```

Der Node auf dem Pi wird nach dem Deploy einmalig installiert und läuft danach
automatisch weiter:

```bash
ssh pi@192.168.178.43 'bash /home/pi/rssi-locator/pi-node/install.sh'
ssh pi@192.168.178.43 'sudo journalctl -u rssi-node -f'
```

## Datenformat Node → Server

```json
{"node": "A", "ts": 1727800000,
 "ble": [{"mac": "AA:BB:CC:DD:EE:FF", "name": "tag1", "rssi": -63}],
 "wifi": [{"ssid": "FRITZ!Box", "bssid": "11:22:33:44:55:66", "rssi": -48}]}
```

Der Server stempelt die Zeit selbst — Pico-Uhren sind unzuverlässig.

## Qualität

- Vor jedem Abschluss: `pytest server/tests pi-node` und ein manueller Test
  (`/healthz`, Simulator, WebSocket-Push).
- Keine Kommentare, die nur Code erklären. Kommentare nur, wenn *warum* nicht offensichtlich ist.
- Skalare Einheiten: alle Längen in **Metern**, RSSI in **dBm**, Zeiten in **Sekunden (Unix)**.
# RSSI-Locator

Zwei Raspberry Pi Pico 2 W messen die Signalstärke (RSSI) von BLE-Geräten und
WLAN-Access-Points und schicken die Messwerte per HTTP an einen Raspberry Pi 4 B.
Der Server schätzt daraus die Positionen und zeigt sie live auf einer Webseite.

```
Node A (Pico 2 W) --\
                     >-- HTTP POST (JSON) --> Pi 4 B: FastAPI + WebSocket --> Browser (Canvas)
Node B (Pico 2 W) --/
```

## Status

| Phase | Inhalt | Stand |
|-------|--------|-------|
| 1 | Server (`/ingest`, `/ws`, Weboberfläche), Simulator, Tests | fertig, läuft auf dem Pi |
| 2/3 | Firmware für Pico 2 W (WLAN, BLE-Scan, Senden) | geschrieben, nicht getestet (kein Pico 2 W angeschlossen) |
| 2/3 | Node für Linux im Pi 4 B (`pi-node/`) | fertig, läuft als Node A |
| 4 | Kalibrierung mit echtem Test-Beacon | offen |
| 5 | Autostart auf dem Pi | fertig (systemd, `enabled`) |
| 6 | 3. Node, Heatmap, Verlauf | offen |

## Schnellstart

### Server lokal

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8099
```

### Simulator (testet alles ohne Hardware)

```bash
server/.venv/bin/python tools/simulate_nodes.py --url http://127.0.0.1:8099/ingest
# Browser: http://127.0.0.1:8099/
```

### Tests

```bash
python3 server/tests/test_positioning.py     # 33 Tests, ohne pytest
python3 pi-node/test_node.py                 # 8 Tests, ohne pytest
server/.venv/bin/python server/tests/smoke.py http://127.0.0.1:8099   # inkl. WebSocket
server/.venv/bin/python tools/check_page.py http://127.0.0.1:8099      # Browser prüfen
```

`tools/check_page.py` startet ein headless Chrome, lädt die Seite, wartet auf echte
WebSocket-Daten und prüft Tabelle und Canvas. Das ist die einzige Prüfung, die
auch die JavaScript-Seite abdeckt.

### Deployment auf den Pi

```bash
bash deploy/deploy.sh            # rsync + venv + Tests + systemd-Neustart
bash deploy/deploy.sh status
bash deploy/deploy.sh logs
bash deploy/deploy.sh uninstall
```

Der Server läuft danach als systemd-Dienst `rssi-locator` auf Port 8099 und
startet automatisch nach einem Neustart. Kein Docker, keine Datenbank, ~46 MB
Speicher.

## Firmware auf den Pico

Siehe [docs/hardware.md](docs/hardware.md) für das Flashen von MicroPython.

Danach genügt ein Befehl — er prüft zuerst, ob das Board überhaupt WLAN kann:

```bash
bash tools/flash_node.sh            # Board suchen, config.py + main.py kopieren, Startlog
bash tools/flash_node.sh /dev/ttyACM0
```

Für Node B `firmware/common/config.py` mit `NODE_ID = "B"` und
`BEACON_NAME = "RSSI-Node-B"` anpassen, dann das Skript erneut ausführen.

## Node auf dem Pi statt auf dem Pico

Solange kein Pico 2 W da ist, misst der Pi 4 B selbst: er hat WLAN und
Bluetooth an Bord und sendet im selben Format wie die Firmware. Aktueller Stand
sind 39 Geräte (BLE + Access Points) mit echten dBm-Werten, Node A läuft als
systemd-Dienst `rssi-node`.

```bash
bash deploy/deploy.sh                                       # Code kopieren
ssh pi@192.168.178.43 'bash /home/pi/rssi-locator/pi-node/install.sh'
ssh pi@192.168.178.43 'sudo journalctl -u rssi-node -f'      # Log
```

Details in [docs/hardware.md](docs/hardware.md#zwischenlösung-der-pi-4-b-als-node).

## Kalibrierung

Siehe [docs/kalibrierung.md](docs/kalibrierung.md). Ohne Kalibrierung sind die
angezeigten Meterzahlen nur eine grobe Skala, die Einstellungen `RSSI 1 m` und
`n` lassen sich aber live im Browser korrigieren.

## Ehrliche Grenzen

- Der Pico 2 W sieht per WLAN-Scan nur Access Points, keine WLAN-Clients.
  Bewegliche Ziele müssen daher **BLE** senden (Tags, Beacons, Handys).
- RSSI schwankt um ±5 bis 10 dB. Erwartbare Genauigkeit: 1 bis 3 m.
- Zwei Nodes ergeben zwei spiegelbildliche Lösungen; die Anzeige bleibt auf
  `y >= 0` und markiert das mit gestrichelter Ellipse.
- Die Ellipsen zeigen die 95-%-Unsicherheit aus der RSSI-Streuung, nicht aus
  Reflexionen und Abschirmung im Raum. In Gebäuden streuen die Werte stärker als
  das Modell annimmt.
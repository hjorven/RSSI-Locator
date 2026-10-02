<<<<<<< HEAD
# RSSI-Locator

Zwei Raspberry Pi Pico 2 W messen die Signalstärke (RSSI) von BLE-Geräten und
WLAN-Access-Points und schicken die Messwerte per HTTP an einen Raspberry Pi 4 B.
Der Server schätzt daraus die Positionen und zeigt sie live auf einer Webseite.

```
Node A (Pico 2 W) --\
                     >-- HTTP POST (JSON) --> Pi 4 B: FastAPI + WebSocket --> Browser (Canvas)
Node B (Pico 2 W) --/
```

## Wofür das gedacht ist

WLAN-Tracker zeigen normalerweise nur den Access Point, mit dem ein Gerät
verbunden ist — nicht, wo das Gerät im Raum steht. RSSI-Locator macht das
umgekehrt: Er nimmt *alle* Access Points im Umfeld als Gehilfen, vermisst sie
von zwei Seiten aus und berechnet daraus, wo ein Gerät ungefähr liegt. Ohne
Zusatz-Hardware, ohne App im Gerät, ohne Tracking-Consent.

Das ist eine **RSSI-Schätzung, keine Ortung.** Sie ersetzt kein GPS und keine
genehmigungspflichtige Ortung. Zweck: eigene Geräte im eigenen Zuhause finden —
Schlüssel, Tracker-Tags, Geräte, die man gerade sucht.

## Status

| Phase | Inhalt | Stand |
|-------|--------|-------|
| 1 | Server (`/ingest`, `/ws`, Weboberfläche), Simulator, Tests | fertig, läuft auf dem Pi |
| 2/3 | Firmware für Pico 2 W (WLAN, BLE-Scan, Senden) | läuft als Node A auf einem Pico 2 W |
| 2/3 | Node für Linux im Pi 4 B (`pi-node/`) | läuft als Node B |
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

Der Simulator erfragt die Node-Geometrie beim Server, rechnet also mit derselben
Anordnung wie die Oberfläche. Mit `--nodes TEST-A,TEST-B --node-position
TEST-A:0,1 --node-position TEST-B:0,3` lässt er sich neben echten Nodes laufen
lassen, ohne deren Messreihen zu verfälschen.

### Tests

```bash
python3 server/tests/test_positioning.py     # 41 Tests, ohne pytest
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

In `deploy/deploy.sh` oben die Zugangsdaten für den Pi anpassen (`PI_USER`,
`PI_HOST`).

## Firmware auf den Pico

Siehe [docs/hardware.md](docs/hardware.md) für das Flashen von MicroPython. Der
Pico 2 W hat einen **BOOTSEL-Knopf**: gedrückt halten, USB-Kabel einstecken,
`RPI_PICO2_W-…uf2` von <https://micropython.org/download/RPI_PICO2_W> auf das
Laufwerk kopieren, Kabel abziehen und neu einstecken.

Danach genügt ein Befehl — er prüft zuerst, ob das Board überhaupt WLAN kann:

```bash
bash tools/flash_node.sh            # Board suchen, config.py + main.py kopieren, Startlog
bash tools/flash_node.sh /dev/ttyACM0
```

Für Node B `firmware/common/config.py` mit `NODE_ID = "B"` und
`BEACON_NAME = "RSSI-Node-B"` anpassen, dann das Skript erneut ausführen.

## Node auf dem Pi

Solange kein zweiter Pico 2 W da ist, misst der Pi 4 B selbst als Node B: er hat
WLAN und Bluetooth an Bord und sendet im selben Format wie die Firmware.

```bash
bash deploy/deploy.sh                                       # Code kopieren
ssh pi@192.168.1.20 'bash /home/pi/rssi-locator/pi-node/install.sh'
ssh pi@192.168.1.20 'sudo journalctl -u rssi-node -f'      # Log
```

Details in [docs/hardware.md](docs/hardware.md#zwischenlösung-der-pi-4-b-als-node).

## Kalibrierung

Siehe [docs/kalibrierung.md](docs/kalibrierung.md). Ohne Kalibrierung sind die
angezeigten Meterzahlen nur eine grobe Skala, die Einstellungen `RSSI 1 m` und
`n` lassen sich aber live im Browser korrigieren.

Der **Nodeabstand D** ist der wichtigste Wert, weil er über die Genauigkeit
entscheidet: bei 45 cm zwischen den Nodes liegt der mittlere Positionsfehler bei
1,9 m, bei 2 m nur noch bei 1,1 m. Faustregel: D etwa halb so groß wie der
größte Abstand, den du messen willst. Die Tabelle mit Messwerten steht in der
Kalibrierungsdoku.

Die Einstellungen werden in `server/settings.json` gespeichert und überstehen
Neustart und Deployment. Messdaten bleiben nur im Arbeitsspeicher.

## Ehrliche Grenzen

- Der Pico 2 W sieht per WLAN-Scan nur Access Points, keine WLAN-Clients.
  Bewegliche Ziele müssen daher **BLE** senden (Tags, Beacons, Handys).
- RSSI schwankt um ±5 bis 10 dB. Erwartbare Genauigkeit: 1 bis 3 m.
- Zwei Nodes ergeben zwei spiegelbildliche Lösungen; die Anzeige bleibt auf
  `y >= 0` und markiert das mit gestrichelter Ellipse.
- Die Ellipsen zeigen die 95-%-Unsicherheit aus der RSSI-Streuung, nicht aus
  Reflexionen und Abschirmung im Raum. In Gebäuden streuen die Werte stärker als
  das Modell annimmt.
- Geräte, die nur ein einziger Node sieht, haben keine Position. Sie stehen in
  der Liste, aber nicht auf der Karte. Aus einem Abstand allein folgt keine
  Richtung.
- `max_distance` (Vorgabe 12 m) begrenzt den Messbereich. Dahinter liefern
  schwache Signale nur noch "irgendwo jenseits der Grenze" und werden verworfen.
- BLE-Geräte mit MAC-Randomisierung erscheinen bei jedem Scan unter neuer
  Adresse. Für die Ortung sind Geräte mit Namen oder festem Beacon brauchbarer.

## Sicherheit und Datenschutz

- Der Server hört nur auf dem Pi. Es gibt keine Weiterleitung nach außen.
- Der Pico sendet nur RSSI-Werte und MAC-Adressen, keine Inhalte.
- Wer den Server ins Internet stellt, braucht TLS und Authentifizierung. Beides
  ist nicht enthalten.

## Beiträge

Pull Requests willkommen. Vor dem Absenden bitte:

```bash
server/.venv/bin/python -m pytest server/tests pi-node   # muss grün sein
```

Bitte keine echten SSIDs, WLAN-Passwörter oder BSSIDs committen — dafür gibt es
`firmware/common/config.example.py`.

## Lizenz

MIT, siehe [LICENSE](LICENSE).
=======
# RSSI-Locator
>>>>>>> origin/main

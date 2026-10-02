# Hardware und Flashen

## Aktueller Stand

Angeschlossen ist ein **Pico 2 W** mit **MicroPython 1.29.0** (`/dev/ttyACM0`),
der als Node A läuft. Ausgelesen und bestätigt:

```
machine : Raspberry Pi Pico 2 W with RP2350
version : v1.29.0 on 2026-08-24
network, bluetooth, ssl: vorhanden
```

### Wichtig: `os.uname().machine` nennt die Firmware, nicht die Platine

Auf dem Board lief vorher **CircuitPython 9.2.0-beta**, und zwar die Build
`RASPBERRYPI_PICO2` — die Variante **ohne** Funk. Die meldete sich als

```
Machine: Raspberry Pi Pico 2 with rp2350a
network, wifi, bluetooth, socketpool, ssl: fehlen alle
```

was nach einem Pico 2 ohne W aussieht, aber keiner war. Der Board-String und die
verfügbaren Module stammen aus der **kompilierten Firmware**, nicht aus dem
Silberdruck. Vor dem Schluss "das ist kein W" gehört deshalb `RPI_PICO2_W`
geflasht und `network` erneut geprüft.

Anhaltspunkte, die unabhängig von der Firmware stimmen:

| Merkmal | Pico 2 | Pico 2 W |
|---------|--------|----------|
| USB-ID in CircuitPython | `2e8a:000b` | `2e8a:000a` |
| Funkmodul auf der Platine | keins | RM2/CYW43, Antenne auf der Rückseite |
| `import network` | nein | ja |
| Aufschrift | `PICO 2` | `PICO 2 W` |

`tools/flash_node.sh` prüft `network` und `bluetooth` und bricht ab, statt
Dateien auf ein Board ohne Funk zu kopieren:

```
FEHLER: Das Board hat kein network-Modul.
```

## Zwischenlösung: der Pi 4 B als Node

Der Pi 4 B hat WLAN (`wlan0`) und Bluetooth (`hci0`) an Bord und macht dieselben
Messungen wie der Pico 2 W. Der Node-Client liegt in `pi-node/` und spricht
dasselbe `/ingest`-Format wie die Firmware. Er ist als **Node B** eingetragen,
weil der Pico die mobilen Node A mit den WLAN-Zugangsdaten ist.

```bash
bash deploy/deploy.sh                 # Code auf den Pi kopieren
ssh pi@192.168.1.20 'bash /home/pi/rssi-locator/pi-node/install.sh'
```

Der Dienst `rssi-node` läuft danach dauerhaft, ebenso wie der Server. Er
braucht `CAP_NET_ADMIN` für `iw` (Schnittstelle hochfahren und scannen); der
BLE-Scan über `bleak` läuft ohne Root. Der Pi hängt am Ethernet und funkt nur
zum Messen — deshalb ist kein WLAN-Passwort nötig, im Gegensatz zum Pico.

Die Node-Kennung steckt in einem Drop-in, damit die Unit-Datei unverändert
bleibt:

```bash
printf "[Service]\nEnvironment=NODE_ID=B\n" | \
  sudo tee /etc/systemd/system/rssi-node.service.d/node-id.conf
sudo systemctl daemon-reload && sudo systemctl restart rssi-node
```

| Node | Kennung | Ort |
|------|---------|-----|
| A | `A` | Pico 2 W, `firmware/common/config.py` |
| B | `B` | Pi 4 B, Drop-in am Dienst `rssi-node` |

## MicroPython auf den Pico 2 W flashen

1. **BOOTSEL-Knopf gedrückt halten** und das USB-Kabel einstecken. Der Pico 2 W
   hat einen Knopf, kein Lötpad. Nach dem Einstecken erscheint das Laufwerk mit
   der Bezeichnung `RP2350` (128 MB, `2e8a:000f`).
2. Firmware herunterladen: <https://micropython.org/download/RPI_PICO2_W>. Der
   Dateiname enthält das Datum, im Zweifel von der Seite ablesen und nicht
   zusammenbauen:
   ```
   RPI_PICO2_W-20260824-v1.29.0.uf2
   https://micropython.org/resources/firmware/RPI_PICO2_W-20260824-v1.29.0.uf2
   ```
3. Datei auf das Laufwerk kopieren, Gerät trennen und wieder anstecken. Auf einem
   System ohne Dateimanager geht das auch so:
   ```bash
   sudo mkdir -p /tmp/uf2 && sudo mount /dev/sdX1 /tmp/uf2
   sudo cp RPI_PICO2_W-*.uf2 /tmp/uf2/ && sudo sync
   sleep 3 && sudo umount /tmp/uf2       # danach ist das Verzeichnis leer
   ```
   Der leere Mount am Ende ist kein Fehler: der Bootloader hat die Partition
   zurückgesetzt und das Board neu gestartet.
4. Prüfen:
   ```bash
   mpremote connect list          # muss "Raspberry Pi Pico 2 W" zeigen
   mpremote exec "import network, bluetooth; print(network.WLAN(network.STA_IF).config('essid'))"
   ```

MicroPython ab Version 1.21 hat das `bluetooth`-Modul im rp2-Port. Der Code in
`firmware/node/main.py` nutzt nur `network`, `bluetooth` und `micropython.const`
und braucht daher **keine** zusätzlich kopierten Bibliotheken.

## Konfiguration

```bash
cp firmware/common/config.example.py firmware/common/config.py
$EDITOR firmware/common/config.py      # WLAN_SSID, WLAN_PASSWORD, SERVER_HOST
```

`firmware/common/config.py` ist in `.gitignore` und darf nicht eingecheckt
werden. Für zwei Nodes wird die Datei zweimal angepasst, jeweils mit anderem
`NODE_ID`:

| Node | `NODE_ID` | `BEACON_NAME` |
|------|-----------|---------------|
| A    | `"A"`     | `"RSSI-Node-A"` |
| B    | `"B"`     | `"RSSI-Node-B"` |

## Auf den Node kopieren

```bash
bash tools/flash_node.sh              # sucht das Board, prüft Funk, kopiert, zeigt das Log
bash tools/flash_node.sh /dev/ttyACM0 # Port explizit
```

Die serielle Ausgabe zeigt den Fortschritt. Ohne Bildschirm ist die einzige
Anzeige der serielle Log, deshalb gibt der Node alle 20 Zyklen eine Zeile aus:

```
[A] Firmware 1.0.0, MicroPython 3.4.0; MicroPython v1.29.0 on 2026-08-24
[A] WLAN verbunden: MEIN_WLAN, IP 192.168.1.30
[A] Beacon aktiv: RSSI-Node-A (A)
[A] Zyklus 20: 22 BLE, 3 WLAN, gesendet ok
```

Das Log lässt sich auch ohne Terminal mitlesen, `script` leiht dem Aufruf ein
pty:

```bash
python3 - <<'PY'
import serial, time
s = serial.Serial('/dev/ttyACM0', 115200, timeout=0.5)
s.write(b'\x04')                      # Soft-Restart, startet main.py neu
s.reset_input_buffer()
print(s.read(4000).decode('utf-8', 'replace'))
s.close()
PY
```

### Fallstricke, die beim ersten Lauf Zeit gekostet haben

- `bluetooth.ble` gibt es nicht mehr. MicroPython liefert die Instanz aus
  `BLE()`, man muss sie selbst festhalten.
- `wlan.scan()` nimmt **kein** Argument; `wlan.scan(None)` wirft auf dem rp2-Port
  einen Fehler.
- `wlan.scan()` liefert **Tupel**, keine Dictionaries:
  `(ssid, bssid, security, rssi, ?, kanal)`, also steht der RSSI an Index 3.
- Puffer, die im IRQ **zugewiesen** werden, brauchen ein `global` in der
  aufrufenden Funktion, sonst arbeitet jede Funktion auf ihrer eigenen Kopie. Zwei
  Varianten standen im ersten Stand drin: `ble_buffer`/`wifi_buffer` blieben
  dadurch leer, der Node sendete also erfolgreich ganz ohne Messwerte, und
  `scan_done` wurde nie `True`, wodurch jeder Scan die vollen 5 s statt der
  3 s wartete. Seit dem Fix dauert ein Zyklus 2 s statt 7 s.
- Direkt nach dem DHCP-Vergabe läuft der erste TCP-Connect gelegentlich in einen
  Timeout. `post_json` versucht es zweimal.
- Ein Firmware-Absturz beendet `main.py` lautlos. `main()` fängt deshalb alles ab
  und startet nach 10 s neu.

## Nodeabstand D automatisch messen (optional)

Beide Nodes senden eine BLE-Werbesendung mit einer eigenen Kennung
(`config.py`: `BEACON_ADVERTISE = True`). Node A sieht damit in seinen
Scan-Ergebnissen den Eintrag von Node B und umgekehrt — allerdings nur als
normales Gerät im Devices-Listen, nicht als eigener Abstandswert.

Für die automatische Übernahme in `D` ist noch ein Schritt offen: der Server
müsste die Kennung im Namen erkennen (`node_link`) und daraus `D` ableiten.
Geplant, aber nicht implementiert (siehe `docs/offene-punkte.md`).

## Ohne Root-Zugriff auf den Host

```bash
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", MODE="0666"' | sudo tee /etc/udev/rules.d/99-pico.rules
sudo udevadm control --reload-rules
```

Ohne diese Regel funktioniert `mpremote` nur mit sudo.
# Hardware und Flashen

## Aktueller Stand

Angeschlossen ist ein **Pico 2 ohne WLAN** (`/dev/ttyACM0`, USB-ID `2e8a:000b`),
geflasht mit **CircuitPython 9.2.0-beta**. Ausgelesen und bestätigt:

```
Machine: Raspberry Pi Pico 2 with rp2350a
network, wifi, bluetooth, socketpool, ssl: fehlen alle
```

Ein Pico 2 W ist nicht nur eine andere Firmware, sondern eine andere Platine mit
Funkmodul (RM2/CYW43). Auch mit MicroPython bekäme dieses Board kein WLAN und
kein BLE, die Firmware aus `firmware/` läuft darauf also nie.

Erkennen, was angeschlossen ist:

```bash
mpremote connect list
mpremote exec "import os; print(os.uname().machine)"
mpremote exec "import network"      # nur beim Pico 2 W ein Erfolg
```

`tools/flash_node.sh` prüft `network` und `bluetooth` und bricht mit dieser
Meldung ab, statt nutzlose Dateien auf ein Board ohne Funk zu kopieren:

```
FEHLER: Das Board hat kein network-Modul.
```

## Zwischenlösung: der Pi 4 B als Node

Der Pi 4 B hat WLAN (`wlan0`) und Bluetooth (`hci0`) an Bord und kann dieselben
Messungen machen wie der Pico 2 W. Der Node-Client liegt in `pi-node/` und
spricht dasselbe `/ingest`-Format wie die Firmware.

```bash
bash deploy/deploy.sh                 # Code auf den Pi kopieren
ssh pi@192.168.178.43 'bash /home/pi/rssi-locator/pi-node/install.sh'
```

Der Dienst `rssi-node` läuft danach dauerhaft, ebenso wie der Server. Er
braucht `CAP_NET_ADMIN` für `iw` (Schnittstelle hochfahren und scannen); der
BLE-Scan über `bleak` läuft ohne Root. Der Pi hängt am Ethernet und funkt nur
zum Messen — deshalb ist kein WLAN-Passwort nötig, im Gegensatz zum Pico.

Konfiguration per Drop-in:

```bash
sudo systemctl edit rssi-node         # NODE_ID, IFACE, NODE_URL
bash deploy/deploy.sh && ssh pi@192.168.178.43 'sudo systemctl restart rssi-node'
```

| Node | `NODE_ID` | Ort |
|------|-----------|-----|
| A    | `A` (Vorgabe) | Pi 4 B, `rssi-node` |
| B    | `B` | später der Pico 2 W |

## MicroPython auf den Pico 2 W flashen

1. **BOOTSEL**: Pico 2 W hat keinen BOOTSEL-Schalter mehr, sondern startet mit
   gedrücktem BOOTSEL USB in den Mass-Storage-Modus.
2. Firmware herunterladen (RP2350, USB):
   <https://micropython.org/download> → `RPI_PICO2_W` → `.uf2`
3. Die `.uf2` per Drag-and-drop auf das neu sichtbare Laufwerk `RPI-RP2` legen,
   Gerät trennen und wieder anstecken.
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
PORT=$(mpremote connect list | grep -m1 "Pico 2 W.*:/dev/ttyACM" | cut -d' ' -f1)
mpremote connect "$PORT" fs cp firmware/common/config.py :config.py
mpremote connect "$PORT" fs cp firmware/node/main.py :main.py
mpremote connect "$PORT" fs ls
mpremote connect "$PORT" reset
```

Die serielle Ausgabe zeigt den Fortschritt:

```
[A] Firmware 1.0.0, MicroPython v1.24.1 ...
[A] WLAN verbunden: WLAN-50, IP 192.168.178.51
[A] Beacon aktiv: RSSI-Node-A (A)
[A] Sende 2 Nodes an ...
```

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
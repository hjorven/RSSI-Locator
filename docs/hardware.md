# Hardware und Flashen

## Aktueller Stand

Angeschlossen ist ein **Pico 2 ohne WLAN** (`/dev/ttyACM0`, USB-ID `2e8a:000b`),
geflasht mit **CircuitPython 9.2**. Dieses Board hat kein `network`-Modul, kann
also weder WLAN noch BLE. Die Firmware in `firmware/` ist für
**Pico 2 W + MicroPython** geschrieben und konnte deshalb noch nicht auf
echter Hardware laufen.

Erkennen, was angeschlossen ist:

```bash
mpremote connect list
mpremote exec "import os; print(os.uname().machine)"
mpremote exec "import network"      # nur beim Pico 2 W ein Erfolg
```

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
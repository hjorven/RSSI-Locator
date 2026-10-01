#!/usr/bin/env bash
# Firmware auf einen Pico 2 W kopieren und den Start prüfen.
#
#   bash tools/flash_node.sh                     # Board suchen, prüfen, kopieren
#   bash tools/flash_node.sh /dev/ttyACM0        # Board explizit angeben
#   PORT=... NODE_ID=B bash tools/flash_node.sh  # Konfiguration für Node B
#
# Voraussetzung: MicroPython ist auf dem Board (siehe docs/hardware.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_SRC="${ROOT}/firmware/common/config.py"
MAIN_SRC="${ROOT}/firmware/node/main.py"

[ -f "$CONFIG_SRC" ] || { echo "FEHLER: ${CONFIG_SRC} fehlt (siehe firmware/common/config.example.py)"; exit 1; }

if [ $# -ge 1 ]; then
  PORT="$1"
else
  # || true, weil grep bei "kein Treffer" Status 1 liefert und set -e sonst
  # das Skript ohne Meldung beenden wuerde.
  PORT="${PORT:-$(mpremote connect list 2>/dev/null | grep -m1 '2e8a:' | cut -d' ' -f1 || true)}"
fi
[ -n "${PORT:-}" ] || { echo "FEHLER: kein Board gefunden. Steck es ein oder gib den Port an."; exit 1; }

echo ">> Board: $PORT"
info="$(mpremote connect "$PORT" exec "import os; print(os.uname().machine, os.uname().version)" 2>&1 | tail -1)"
echo ">> $info"

if ! mpremote connect "$PORT" exec "import network" >/dev/null 2>&1; then
  cat >&2 <<'WARN'
FEHLER: Das Board hat kein network-Modul.
  Entweder ist es ein Pico 2 OHNE "W" (kein WLAN, kein BLE) oder es läuft
  noch kein MicroPython. Beides geht für dieses Projekt nicht.
  Nötig: Pico 2 W mit MicroPython, siehe docs/hardware.md
WARN
  exit 1
fi

if ! mpremote connect "$PORT" exec "import bluetooth" >/dev/null 2>&1; then
  echo "WARNUNG: kein bluetooth-Modul. Der Node kann nur WLAN scannen."
fi

echo ">> Dateien kopieren"
mpremote connect "$PORT" fs cp "$CONFIG_SRC" :config.py
mpremote connect "$PORT" fs cp "$MAIN_SRC" :main.py

echo ">> Neustart und Startmeldung (10 s)"
mpremote connect "$PORT" reset >/dev/null 2>&1 || true
sleep 1
timeout 10 mpremote connect "$PORT" soft-reset 2>&1 | head -25 || true
echo
echo "Fertig. Erwartete Ausgabe: 'WLAN verbunden', 'Beacon aktiv', danach sendet der Node."
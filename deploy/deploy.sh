#!/usr/bin/env bash
# Deployment auf den Raspberry Pi 4 B: rsync, venv, systemd.
#
#   bash deploy/deploy.sh            # Code kopieren, Abhaengigkeiten, Neustart
#   bash deploy/deploy.sh logs       # Log folgen
#   bash deploy/deploy.sh status     # Status und Health-Check
#   bash deploy/deploy.sh uninstall  # Dienst entfernen
set -euo pipefail

PI_HOST="${PI_HOST:-192.168.178.43}"
PI_USER="${PI_USER:-pi}"
REMOTE_DIR="${REMOTE_DIR:-/home/pi/rssi-locator}"
SERVICE="rssi-locator"
PORT="8099"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH=(ssh -o ConnectTimeout=8 "${PI_USER}@${PI_HOST}")

case "${1:-deploy}" in

deploy)
  echo ">> 1/5 Code nach ${PI_USER}@${PI_HOST}:${REMOTE_DIR} kopieren"
  "${SSH[@]}" "mkdir -p '${REMOTE_DIR}'"
  # settings.json wird ausdrücklich vom Löschen ausgenommen: es enthält die
  # Kalibrierwerte des Geräts, steht in .gitignore und darf ein Deployment
  # nicht überleben lassen.
  rsync -az --delete \
    --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
    --exclude 'firmware/common/config.py' \
    --exclude 'server/settings.json' \
    "${ROOT}/" "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"

  echo ">> 2/5 bis 4/5 venv, Abhaengigkeiten, Unit-Tests auf dem Pi"
  # Der Schritt läuft als eigenes Skript auf dem Pi, damit die lokalen Anführungs-
  # zeichen nicht mit den Pfaden kollidieren.
  "${SSH[@]}" bash -s -- "$REMOTE_DIR" "$SERVICE" <<'REMOTE'
set -euo pipefail
dir="$1"
service="$2"
py="$dir/server/.venv/bin/python"

[ -x "$py" ] || python3 -m venv "$dir/server/.venv"
"$dir/server/.venv/bin/pip" install --quiet --upgrade pip
"$dir/server/.venv/bin/pip" install --quiet -r "$dir/server/requirements.txt"
"$py" -c 'import fastapi, uvicorn, websockets; print("fastapi", fastapi.__version__, "| uvicorn", uvicorn.__version__)'
"$py" "$dir/server/tests/test_positioning.py" | tail -2
REMOTE

  echo ">> 5/5 systemd-Unit installieren und Dienst starten"
  "${SSH[@]}" sudo install -m 644 /dev/stdin /etc/systemd/system/"${SERVICE}".service \
    < "${ROOT}/deploy/${SERVICE}.service"
  "${SSH[@]}" bash -s -- "$SERVICE" <<'REMOTE'
set -euo pipefail
service="$1"
sudo systemctl daemon-reload
sudo systemctl enable "$service" >/dev/null
sudo systemctl restart "$service"
REMOTE

  sleep 2
  echo ">> Zustand auf dem Pi"
  "${SSH[@]}" "systemctl is-active ${SERVICE}; systemctl is-enabled ${SERVICE}"

  echo ">> Health-Check (warte auf HTTP)"
  # uvicorn braucht auf dem Pi ein paar Sekunden bis der Port offen ist.
  for attempt in $(seq 1 30); do
    if curl -sS --max-time 3 "http://${PI_HOST}:${PORT}/healthz" 2>/dev/null; then
      echo
      echo "Fertig: http://${PI_HOST}:${PORT}/"
      exit 0
    fi
    sleep 1
  done
  echo "FEHLER: Server antwortet nicht auf Port ${PORT}"
  "${SSH[@]}" "sudo journalctl -u ${SERVICE} -n 20 --no-pager"
  exit 1
  ;;

status)
  "${SSH[@]}" "systemctl status ${SERVICE} --no-pager -l | head -15"
  echo
  curl -sS --max-time 5 "http://${PI_HOST}:${PORT}/healthz"
  echo
  curl -sS --max-time 5 "http://${PI_HOST}:${PORT}/api/state" | head -c 500
  echo
  ;;

logs)
  "${SSH[@]}" "sudo journalctl -u ${SERVICE} -f -n 40"
  ;;

uninstall)
  "${SSH[@]}" bash -s -- "$SERVICE" <<'REMOTE'
set -euo pipefail
service="$1"
sudo systemctl disable --now "$service"
sudo rm -f "/etc/systemd/system/${service}.service"
sudo systemctl daemon-reload
REMOTE
  echo "Dienst entfernt (Dateien in ${REMOTE_DIR} bleiben)."
  ;;

*)
  echo "Aufruf: bash deploy/deploy.sh [deploy|logs|status|uninstall]"
  exit 1
  ;;
esac
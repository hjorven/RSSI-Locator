#!/usr/bin/env bash
# Node auf dem Raspberry Pi installieren: venv, bleak, systemd-Unit.
#
#   bash pi-node/install.sh            # venv anlegen, Dienst starten
#   bash pi-node/install.sh logs       # Log folgen
#   bash pi-node/install.sh uninstall  # Dienst entfernen
#
# Aufruf erst nach bash deploy/deploy.sh, damit der Code auf dem Pi liegt.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${DIR}/.venv"
SERVICE="rssi-node"
URL="${NODE_URL:-http://192.168.178.43:8099/ingest}"

case "${1:-install}" in

install)
  echo ">> 1/3 venv und bleak"
  [ -x "${VENV}/bin/python" ] || python3 -m venv "$VENV"
  "${VENV}/bin/pip" install --quiet --upgrade pip
  "${VENV}/bin/pip" install --quiet bleak
  "${VENV}/bin/python" -c 'import bleak; print("bleak installiert")'

  echo ">> 2/3 Scanner-Parser testen"
  "${VENV}/bin/python" "${DIR}/test_node.py" | tail -1

  echo ">> 3/3 systemd-Unit installieren und Dienst starten"
  sudo install -m 644 "${DIR}/${SERVICE}.service" "/etc/systemd/system/${SERVICE}.service"
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE" >/dev/null
  sudo systemctl restart "$SERVICE"
  sleep 3
  systemctl is-active "$SERVICE"
  sudo journalctl -u "$SERVICE" -n 12 --no-pager
  echo
  echo "Ziel: $URL"
  echo "Aendern: sudo systemctl edit ${SERVICE}  (NODE_ID, IFACE, NODE_URL)"
  ;;

logs)
  sudo journalctl -u "$SERVICE" -f -n 40
  ;;

uninstall)
  sudo systemctl disable --now "$SERVICE"
  sudo rm -f "/etc/systemd/system/${SERVICE}.service"
  sudo systemctl daemon-reload
  echo "Dienst entfernt (venv und Dateien bleiben)."
  ;;

*)
  echo "Aufruf: bash pi-node/install.sh [install|logs|uninstall]"
  exit 1
  ;;
esac

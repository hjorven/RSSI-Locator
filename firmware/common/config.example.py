# WLAN- und Server-Konfiguration fuer die Nodes.
#
# Kopieren nach config.py und anpassen:
#   cp config.example.py config.py
#
# config.py ist in .gitignore und darf NICHT eingecheckt werden.

# --- Identitaet -------------------------------------------------------------
NODE_ID = "A"          # "A" oder "B" (je Node ein eigener Wert)

# --- WLAN -------------------------------------------------------------------
WLAN_SSID = "DEIN_WLAN"
WLAN_PASSWORD = "DEIN_PASSWORT"
WLAN_MAX_RETRIES = 20        # Verbindungsversuche je Start
WLAN_TIMEOUT_MS = 15000      # Verbindungs-Timeout pro Versuch

# --- Server -----------------------------------------------------------------
SERVER_HOST = "192.168.178.43"
SERVER_PORT = 8099
SERVER_PATH = "/ingest"

# --- Scan-Parameter ---------------------------------------------------------
SCAN_HZ = 1.0              # Scan-Zyklen pro Sekunde (nach dem Senden)
BLE_SCAN_MS = 3000         # BLE-Scanfenster pro Zyklus
WIFI_SCAN_EVERY = 3        # WLAN-Vollscan nur alle n Zyklen (dauert ~2-3 s)

# Optionaler Selbsttest-Beacon: Der Node sendet eine BLE-Werbesendung mit
# fester Kennung, damit der jeweils andere Node den Nodeabstand messen kann.
BEACON_ADVERTISE = True
BEACON_NAME = "RSSI-Node-A"   # muss zum NODE_ID passen

# --- Kalibrierung (Anzeigeseite, hier nur Dokumentation) --------------------
# RSSI_1m und Umgebungsfaktor n werden im Server eingestellt, nicht im Node.
NODE_DISTANCE_M = 4.0      # Nur zur Anzeige im Server-Log nach dem Flashen
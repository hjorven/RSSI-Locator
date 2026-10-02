"""Firmware fuer Raspberry Pi Pico 2 W (MicroPython 1.22+).

Ablauf eines Zyklus: WLAN verbunden -> scannen -> senden -> kurze Pause.

BLE-Scan und WLAN-Scan laufen bewusst NICHT gleichzeitig. Der CYW43-Treiber
sendet waehrend eines aktiven BLE-Scans unzuverlaessig und umgekehrt leiden
die Scanergebnisse. Deshalb wird abwechselt: pro Zyklus wird nur ein Typ
gescannt, das Ergebnis des anderen wird mitgeschickt.

Die BLE-API von MicroPython ist ereignisbasiert (kein Ergebnis-Array wie bei
Blinken), deshalb sammelt der IRQ-Handler die Treffer in einem Dictionary.

Ohne externe Bibliotheken: HTTP wird ueber ein rohes Socket geschrieben, damit
kein requests-Modul auf den Pico kopiert werden muss.
"""

import gc
import json
import socket
import sys
import time

import network
from micropython import const

try:
    from bluetooth import BLE
except ImportError:  # Board ohne Funk (z. B. Pico 2 ohne "W")
    BLE = None

from config import (
    BEACON_ADVERTISE,
    BEACON_NAME,
    BLE_SCAN_MS,
    NODE_ID,
    SCAN_HZ,
    SERVER_HOST,
    SERVER_PATH,
    SERVER_PORT,
    WIFI_SCAN_EVERY,
    WLAN_MAX_RETRIES,
    WLAN_PASSWORD,
    WLAN_SSID,
)

VERSION = "1.0.0"
DEBUG = True

# Ereigniscodes des bluetooth-Moduls (laut MicroPython-Doku nicht exportiert).
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE = const(6)

# AD-Typen aus den Advertising-Records.
_AD_FLAGS = const(0x01)
_AD_SHORT_NAME = const(0x08)
_AD_COMPLETE_NAME = const(0x09)
_AD_MANUFACTURER = const(0xFF)

# Signatur im Herstellerfeld, damit der Partner-Node uns erkennt (Nodeabstand).
BEACON_COMPANY = const(0x4C53)  # 'LS'
RSSI_FLOOR = -95  # alles Schwächere ist Rauschen und verwirft die Glättung


def log(msg):
    if DEBUG:
        print("[%s] %s" % (NODE_ID, msg))


# ---------------------------------------------------------------------------
# WLAN
# ---------------------------------------------------------------------------


def connect_wlan():
    """Verbindet zum WLAN und wartet auf die IP."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        log("WLAN schon verbunden: %s" % wlan.config("essid"))
        return wlan
    wlan.connect(WLAN_SSID, WLAN_PASSWORD)
    for attempt in range(WLAN_MAX_RETRIES):
        if wlan.isconnected():
            log("WLAN verbunden: %s, IP %s" % (wlan.config("essid"), wlan.ifconfig()[0]))
            return wlan
        time.sleep(1)
        log("WLAN-Versuch %d/%d fehlgeschlagen" % (attempt + 1, WLAN_MAX_RETRIES))
    raise RuntimeError("kein WLAN: %s" % WLAN_SSID)


# ---------------------------------------------------------------------------
# BLE
# ---------------------------------------------------------------------------

ble_results = {}
scan_done = False

#: Die BLE-Instanz des Controllers. MicroPython haengt sie nicht mehr unter
#: `bluetooth.ble`, sie kommt aus `BLE()` und wird hier festgehalten.
ble = None


def ble_irq(event, data):
    global scan_done
    if event == _IRQ_SCAN_RESULT:
        addr_type, addr, adv_type, rssi, adv_data = data
        rssi = int(rssi)
        if rssi < RSSI_FLOOR:
            return
        # adv_data zeigt in den Puffer des Treibers, also sofort kopieren.
        key = addr_str(bytes(addr))
        name, node_link = parse_adv(bytes(adv_data))
        ble_results[key] = (rssi, name, node_link)
    elif event == _IRQ_SCAN_DONE:
        scan_done = True


def parse_adv(adv):
    """Zerlegt einen Advertising-Payload.

    Rueckgabe: (Name oder None, Node-Kennung des Partnernodes oder None).
    """
    name = None
    node_link = None
    i = 0
    while i + 1 < len(adv):
        length = adv[i]
        if length == 0:
            break
        typ = adv[i + 1]
        data = adv[i + 2 : i + 1 + length]
        if typ in (_AD_SHORT_NAME, _AD_COMPLETE_NAME) and data:
            name = data.decode("utf-8", "replace").strip()
        elif typ == _AD_MANUFACTURER and len(data) >= 3:
            company = (data[0] << 8) | data[1]
            if company == BEACON_COMPANY:
                node_link = data[2:].decode("utf-8", "replace").strip()
        i += 1 + length
    return name, node_link


def addr_str(addr):
    return ":".join("%02X" % b for b in addr)


def scan_ble():
    """Ein BLE-Scanfenster. Liefert Liste von (mac, rssi, name, node_link)."""
    # `scan_done` wird im IRQ gesetzt. Ohne `global` laeuft die Warteschleife in
    # ein lokales False und wartet jedes Mal die vollen 5 s ab, auch wenn der
    # Treiber den Scan nach 3 s sauber beendet hat.
    global scan_done
    if ble is None:
        return []
    ble_results.clear()
    scan_done = False
    try:
        ble.gap_scan(BLE_SCAN_MS, 20000, 11250, False)
    except Exception as exc:
        log("BLE-Scan-Start fehlgeschlagen: %s" % exc)
        return []
    # Warten bis der Treiber den Scan beendet hat; hart begrenzt, falls das
    # IRQ-Event ausbleibt.
    waited = 0
    while not scan_done and waited < BLE_SCAN_MS + 2000:
        time.sleep_ms(100)
        waited += 100
    try:
        ble.gap_scan(None)  # Scan sicherheitshalber beenden
    except Exception:
        pass
    out = [(mac, rssi, name, link) for mac, (rssi, name, link) in ble_results.items()]
    return out


def start_beacon():
    """Optionale BLE-Werbesendung, damit der Partner-Node unseren Abstand misst."""
    if not BEACON_ADVERTISE or ble is None:
        return
    name = BEACON_NAME.encode()
    payload = bytes([len(name) + 1, _AD_COMPLETE_NAME]) + name
    manu = bytes([len(NODE_ID) + 3, _AD_MANUFACTURER, BEACON_COMPANY >> 8,
                  BEACON_COMPANY & 0xFF]) + NODE_ID.encode()
    flags = bytes([2, _AD_FLAGS, 0x06])  # LE General Discoverable + BR/ED nicht unterstützt
    try:
        ble.active(True)
        ble.config(gap_name=BEACON_NAME)
        ble.gap_advertise(625000, adv_data=flags + manu + payload, connectable=False)
        log("Beacon aktiv: %s (%s)" % (BEACON_NAME, NODE_ID))
    except Exception as exc:
        log("Beacon nicht aktiv: %s" % exc)


# ---------------------------------------------------------------------------
# WLAN-Scan
# ---------------------------------------------------------------------------


def bssid_str(raw):
    if isinstance(raw, str):
        return raw.upper()
    return ":".join("%02X" % b for b in bytes(raw))


def ap_entry(ap):
    """Ein Scan-Ergebnis in (ssid, bssid, rssi) zerlegen.

    Der rp2-Port liefert Tupel, keine Dictionaries. Die belegte Reihenfolge
    ist (ssid, bssid, security, rssi, ?, kanal), ausgegeben auf dem Board:

        (b'MEIN_WLAN', b'\\xaa\\xbb\\xcc\\xdd\\xee\\xff', 1, -43, 7, 4)

    Andere Ports liefern Dictionaries, deshalb wird beides akzeptiert.
    """
    if isinstance(ap, dict):
        ssid = ap.get("ssid") or b""
        bssid = ap.get("bssid") or b""
        rssi = ap.get("signal", -100)
    else:
        ssid = ap[0] if len(ap) > 0 else b""
        bssid = ap[1] if len(ap) > 1 else b""
        rssi = ap[3] if len(ap) > 3 else -100
    if isinstance(ssid, bytes):
        ssid = ssid.decode("utf-8", "replace")
    return (ssid, bssid_str(bssid), int(rssi))


def scan_wifi():
    """WLAN-Vollscan. Liefert nur Access Points, keine WLAN-Clients."""
    wlan = network.WLAN(network.STA_IF)
    try:
        # Der rp2-Port nimmt kein Argument: wlan.scan(None) wirft einen Fehler.
        aps = wlan.scan()
    except Exception as exc:
        log("WLAN-Scan-Fehler: %s" % exc)
        return []
    out = []
    for ap in aps:
        ssid, bssid, rssi = ap_entry(ap)
        if rssi < RSSI_FLOOR:
            continue
        out.append((ssid, bssid, rssi))
    return out


# ---------------------------------------------------------------------------
# Senden
# ---------------------------------------------------------------------------


def post_json(payload, versuche=2, timeout=5.0):
    """POST per rohem Socket, ohne requests-Modul.

    Zwei Versuche: direkt nach dem DHCP-Vergabe hat der CYW43-Treiber die
    Routing-Tabelle manchmal noch nicht fertig, dann laeuft der erste Connect in
    einen Timeout. Der zweite Versuch klappt dann sofort.
    """
    data = json.dumps(payload).encode()
    head = (
        "POST %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n\r\n"
    ) % (SERVER_PATH, SERVER_HOST, SERVER_PORT, len(data))

    for attempt in range(versuche):
        sock = None
        try:
            sock = socket.socket()
            sock.settimeout(timeout)
            sock.connect((SERVER_HOST, SERVER_PORT))
            sock.sendall(head.encode() + data)
            try:
                sock.recv(64)
            except OSError:
                pass
            return True
        except OSError as exc:
            log("Senden fehlgeschlagen: %s" % exc)
            time.sleep(1)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    return False


# ---------------------------------------------------------------------------
# Hauptzyklus
# ---------------------------------------------------------------------------

ble_buffer = []
wifi_buffer = []


def build_payload():
    """Baut den JSON-Payload aus beiden Puffern."""
    return {
        "node": NODE_ID,
        "ts": int(time.time()),
        "ble": [
            {"mac": mac, "rssi": rssi, "name": name} for mac, rssi, name, _ in ble_buffer
        ],
        "wifi": [
            {"ssid": ssid, "bssid": bssid, "rssi": rssi} for ssid, bssid, rssi in wifi_buffer
        ],
    }


def run():
    """Ein Durchlauf inklusive WLAN-Verbindung, danach endlos scannen und senden.

    Wirft bei einem Verbindungsproblem nach außen, damit `main` neu starten kann.
    """
    # Ohne dieses `global` legt Python unten lokale Listen an, und `build_payload`
    # bliebe auf den leeren Modulvariablen stehen: der Node sendet dann zwar
    # erfolgreich, aber ohne Messwerte.
    global ble_buffer, wifi_buffer

    wlan = connect_wlan()
    start_beacon()
    interval = 1.0 / SCAN_HZ if SCAN_HZ > 0 else 1.0
    cycle = 0

    while True:
        started = time.time()

        if not wlan.isconnected():
            log("WLAN verloren, verbinde neu")
            try:
                wlan.connect(WLAN_SSID, WLAN_PASSWORD)
                wlan = network.WLAN(network.STA_IF)
            except Exception as exc:
                log("WLAN-Wiederverbindung fehlgeschlagen: %s" % exc)
                time.sleep(5)
                continue

        cycle += 1

        # Abwechselnd scannen, das Ergebnis des anderen Typs wird mitgesendet.
        if ble is not None and cycle % 2 == 1:
            ble_buffer = scan_ble()
        if cycle % (2 * max(1, WIFI_SCAN_EVERY)) == 0:
            wifi_buffer = scan_wifi()

        ok = post_json(build_payload())
        if cycle % 20 == 0:
            # Ohne Bildschirm ist die serielle Ausgabe die einzige Anzeige. Alle
            # 20 Zyklen eine Zeile, damit ein stiller Node auffällt.
            log(
                "Zyklus %d: %d BLE, %d WLAN, gesendet %s"
                % (cycle, len(ble_buffer), len(wifi_buffer), "ok" if ok else "nein")
            )
        if not ok:
            # Kurze Pause: Server down oder WLAN weg, nicht sofort neu scannen.
            time.sleep(2)

        gc.collect()

        rest = interval - (time.time() - started)
        if rest > 0.2:
            time.sleep(rest)


def start_ble():
    """BLE-Controller aktivieren. Liefert False, wenn das Board keinen Funk hat."""
    global ble
    if BLE is None:
        return False
    try:
        ble = BLE()
        ble.irq(ble_irq)
        ble.active(True)
    except Exception as exc:
        ble = None
        log("BLE nicht verfuegbar: %s" % exc)
        return False
    return True


def main():
    log("Firmware %s, MicroPython %s" % (VERSION, sys.version))

    if not start_ble():
        log("WARNUNG: kein bluetooth-Modul, nur WLAN-Scan")

    # Ohne diesen Rahmen bleibt der Node bei einem WLAN-Problem beim ersten
    # Aufruf stehen und macht nichts mehr, bis jemand das Kabel zieht.
    while True:
        try:
            run()
        except Exception as exc:
            log("Abbruch (%r), neuer Versuch in 10 s" % exc)
            time.sleep(10)


main()
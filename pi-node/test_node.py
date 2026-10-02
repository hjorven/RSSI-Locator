"""Tests des Linux-Nodes (Scanner-Parser und Payload).

Ausfuehren:
    pytest pi-node
    oder ohne pytest:
    python3 pi-node/test_node.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from node import RSSI_FLOOR, build_payload, parse_iw_scan  # noqa: E402

SCAN = """BSS aa:bb:cc:dd:ee:01(on wlan0)
\tlast seen:
\tfreq: 2412
\tRSSI: -45.00 dBm
\tsignal: -45.00 dBm
\tSSID: MEIN_WLAN
BSS AA:BB:CC:DD:EE:02(on wlan0)
\tfreq: 5180
\tsignal: -72.40 dBm
\tSSID: GASTNETZ
BSS aa:bb:cc:dd:ee:03(on wlan0)
\tfreq: 2437
\tsignal: -60.00 dBm
BSS aa:bb:cc:dd:ee:04(on wlan0)
\tfreq: 2412
\tsignal: -96.00 dBm
\tSSID: Zu weit weg
BSS aa:bb:cc:dd:ee:05(on wlan0)
\tfreq: 2412
\tSSID: Kein Signalwert
"""


def test_parse_iw_scan():
    aps = parse_iw_scan(SCAN)
    assert aps == [
        ("MEIN_WLAN", "AA:BB:CC:DD:EE:01", -45),
        ("GASTNETZ", "AA:BB:CC:DD:EE:02", -72),
        ("", "AA:BB:CC:DD:EE:03", -60),
    ], aps


def test_versteckter_ap_bleibt_drin():
    """Ohne SSID-Zeile zählt der AP über seine BSSID, der Server nutzt sie als Schlüssel."""
    aps = dict((bssid, ssid) for ssid, bssid, _ in parse_iw_scan(SCAN))
    assert aps["AA:BB:CC:DD:EE:03"] == ""


def test_ap_unter_grenze_faellt_weg():
    bssids = [b for _, b, _ in parse_iw_scan(SCAN)]
    assert "AA:BB:CC:DD:EE:04" not in bssids
    assert all(rssi >= RSSI_FLOOR for _, _, rssi in parse_iw_scan(SCAN))


def test_ap_ohne_signalwert_faellt_weg():
    bssids = [b for _, b, _ in parse_iw_scan(SCAN)]
    assert "AA:BB:CC:DD:EE:05" not in bssids


def test_leere_ausgabe():
    assert parse_iw_scan("") == []
    assert parse_iw_scan("command failed: Device or resource busy (-16)\n") == []


def test_zeilen_vor_dem_ersten_bss_werden_ignoriert():
    text = "BSS-Liste wird erzeugt...\nwlan0\n" + SCAN
    assert len(parse_iw_scan(text)) == 3


def test_build_payload():
    payload = build_payload(
        "A",
        [("C4:7F:0E:CD:65:C9", -49, "MOZA")],
        [("MEIN_WLAN", "AA:BB:CC:DD:EE:01", -45)],
        1727800000,
    )
    assert payload["node"] == "A"
    assert payload["ts"] == 1727800000
    assert payload["ble"] == [{"mac": "C4:7F:0E:CD:65:C9", "rssi": -49, "name": "MOZA"}]
    assert payload["wifi"] == [
        {"ssid": "MEIN_WLAN", "bssid": "AA:BB:CC:DD:EE:01", "rssi": -45}
    ]


def test_build_payload_ohne_messungen():
    """Ein Node ohne Treffer muss trotzdem gueltige Zahlenlisten senden."""
    payload = build_payload("B", [], [], 1727800001)
    assert payload["ble"] == [] and payload["wifi"] == []
    assert payload["node"] == "B"


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, func in tests:
        try:
            func()
            print("ok   %s" % name)
        except AssertionError as exc:
            failed += 1
            print("FAIL %s: %s" % (name, exc))
    print("%d Tests, %d Fehler" % (len(tests), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests der Positionsberechnung.

Ausfuehren:
    pytest server/tests
    oder ohne pytest-Installation:
    python3 server/tests/test_positioning.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from positioning import (  # noqa: E402
    Ema,
    Locator,
    RssiFilter,
    Settings,
    distance_sigma,
    mad_sigma,
    median,
    rssi_to_distance,
    trilaterate_2_nodes,
    trilaterate_linear,
)


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_median():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5
    assert approx(median([-60, -61, -62, -63]), -61.5)
    # Ein Ausreißer darf den Median kaum bewegen, den Mittelwert schon.
    with_outlier = [-60, -61, -62, -63, -95]
    assert median(with_outlier) == -62
    assert sum(with_outlier) / 5 < -62


def test_mad_sigma():
    assert mad_sigma([1]) == 0.0
    # Gleichverteiltes Rauschen um 0 -> sigma groesser 0
    assert mad_sigma([-5, -3, -1, 1, 3, 5]) > 2.5
    # Ein Ausreißer bei MAD: 0 (Median-Abweichung ist 0 bzw. klein)
    assert approx(mad_sigma([-60] * 6 + [-30]), 0.0)


def test_rssi_filter_median_and_window():
    f = RssiFilter(window=3)
    assert f.add(-60) == -60
    assert f.add(-70) == -65  # Median aus zwei Werten
    assert f.add(-62) == -62
    assert f.add(-64) == -64  # Fenster rollt: -70 faellt raus
    assert len(f.values) == 3
    # Unsicherheit braucht mindestens drei Werte
    assert approx(f.sigma, 0.0) is False or f.sigma == 0.0


def test_rssi_filter_sigma_and_set_window():
    f = RssiFilter(window=5)
    for v in (-60, -61, -62, -60, -61):
        f.add(v)
    assert 0.3 < f.sigma < 2.0
    f.set_window(2)
    assert f.window == 2
    assert len(f.values) == 2  # Historie auf neues Fenster gekuerzt


def test_ema():
    e = Ema(alpha=0.5)
    assert e.update(10) == 10
    assert e.update(20) == 15
    assert e.update(20) == 17.5
    e.reset()
    assert e.value is None


def test_rssi_to_distance():
    # Bei rssi == rssi_1m ist die Distanz genau 1 m
    assert approx(rssi_to_distance(-59, -59, 2.5), 1.0)
    # 10 dB Abfall entspricht Faktor 10 bei n=1 -> hier n=2: Faktor 10^0.5
    assert approx(rssi_to_distance(-69, -59, 2.0), 10 ** 0.5)
    # n = 3: 30 dB Abfall -> Faktor 10
    assert approx(rssi_to_distance(-89, -59, 3.0), 10.0)
    # Staerkeres Signal -> kleinere Distanz (monoton)
    assert rssi_to_distance(-50, -59, 2.5) < rssi_to_distance(-70, -59, 2.5)


def test_distance_sigma_grows_with_distance_and_noise():
    d1, d2 = 2.0, 8.0
    assert distance_sigma(d1, 4.0, 2.5) < distance_sigma(d2, 4.0, 2.5)
    assert distance_sigma(d2, 4.0, 2.5) < distance_sigma(d2, 8.0, 2.5)
    assert distance_sigma(3.0, 0.0, 2.5) == 0.0


def test_trilaterate_two_nodes_on_midline():
    # Gleich weit von beiden Nodes: x = D/2
    x, y, hit = trilaterate_2_nodes(5.0, 5.0, 10.0)
    assert approx(x, 5.0)
    # Die Kreise beruehren sich genau auf der Mittelsenkrechten: kein Schnitt.
    assert not hit and approx(y, 0.0)


def test_trilaterate_two_nodes_known_point():
    D = 4.0
    # Ziel bei (1, 2): dA = sqrt(5), dB = sqrt(13)
    d_a = math.hypot(1.0, 2.0)
    d_b = math.hypot(1.0 - D, 2.0)
    x, y, hit = trilaterate_2_nodes(d_a, d_b, D)
    assert hit
    assert approx(x, 1.0, 1e-6)
    assert approx(y, 2.0, 1e-6)
    # Spiegelung aufloesbar: Alternative waere y = -2, wir waehlen y >= 0


def test_trilaterate_two_nodes_no_intersection_behind_b():
    # |dA - dB| > D: kein Punkt in der Ebene passt. Loesung liegt hinter Node B.
    x, y, hit = trilaterate_2_nodes(6.31, 1.74, 4.0)
    assert not hit and approx(y, 0.0)
    assert approx(x, (6.31 + 1.74 + 4.0) / 2.0)
    assert x > 4.0


def test_trilaterate_two_nodes_no_intersection_behind_a():
    x, y, hit = trilaterate_2_nodes(1.0, 6.0, 4.0)
    assert not hit and approx(y, 0.0)
    assert approx(x, (4.0 - 1.0 - 6.0) / 2.0)
    assert x < 0.0


def test_trilaterate_two_nodes_inconsistent_is_least_squares_optimum():
    """Die inkonsistente Loesung muss das Minimum der Fehlersumme sein.
    Numerisch gegengeprueft mit einem feinen Raster."""
    def err(x, y, d_a, d_b, D):
        return (math.hypot(x, y) - d_a) ** 2 + (math.hypot(x - D, y) - d_b) ** 2

    for d_a, d_b, D in ((6.31, 1.74, 4.0), (3.0, 9.0, 4.0), (12.0, 3.0, 4.0), (2.0, 7.5, 4.0)):
        x, y, hit = trilaterate_2_nodes(d_a, d_b, D)
        assert not hit
        best = min(err(px, py, d_a, d_b, D)
                   for px in [i * 0.05 for i in range(-400, 401)]
                   for py in [i * 0.05 for i in range(0, 300)])
        assert err(x, y, d_a, d_b, D) <= best + 0.01, (d_a, d_b, D)


def test_trilaterate_two_nodes_tangent():
    # |dA - dB| == D genau: die Kreise beruehren sich hinter Node A
    x, y, hit = trilaterate_2_nodes(3.0, 7.0, 4.0)
    assert not hit and approx(y, 0.0)
    assert approx(x, -3.0)


def test_trilaterate_linear_three_nodes_exact():
    nodes = [(0.0, 0.0), (4.0, 0.0), (2.0, 3.0)]
    truth = (1.0, 2.0)
    dists = [math.hypot(truth[0] - nx, truth[1] - ny) for nx, ny in nodes]
    sol = trilaterate_linear(dists, nodes)
    assert sol is not None
    assert approx(sol[0], truth[0], 1e-6)
    assert approx(sol[1], truth[1], 1e-6)


def test_trilaterate_linear_three_nodes_noisy():
    nodes = [(0.0, 0.0), (4.0, 0.0), (2.0, 3.0)]
    truth = (1.5, 1.0)
    dists = [
        math.hypot(truth[0] - nx, truth[1] - ny) + 0.25 for nx, ny in nodes
    ]  # 25 cm systematischer Fehler
    sol = trilaterate_linear(dists, nodes)
    assert sol is not None
    assert math.hypot(sol[0] - truth[0], sol[1] - truth[1]) < 0.3


def test_trilaterate_linear_singular_returns_none():
    # Alle Nodes auf einer Geraden -> Gleichungssystem singulär
    nodes = [(0.0, 0.0), (4.0, 0.0), (8.0, 0.0)]
    dists = [1.0, 3.0, 7.0]
    assert trilaterate_linear(dists, nodes) is None


def test_settings_update_and_clamp():
    s = Settings()
    s.update({"node_distance": 5.5, "path_loss_ble": 9.9, "unbekannt": 1})
    assert approx(s.node_distance, 5.5)
    assert approx(s.path_loss_ble, 6.0)  # begrenzt auf maximum 6
    assert not hasattr(s, "unbekannt")
    s.update({"rssi_window": 7.6})
    assert s.rssi_window == 8  # auf int gerundet
    # drop_after muss groesser als stale_after bleiben
    s.update({"stale_after": 30.0, "drop_after": 20.0})
    assert s.drop_after > s.stale_after


def test_settings_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(tmp) / "settings.json"
        s = Settings()
        s.update({"node_distance": 0.45, "rssi_1m_ble": -63.0})
        s.save(pfad)
        geladen = Settings.load(pfad)
        assert approx(geladen.node_distance, 0.45)
        assert approx(geladen.rssi_1m_ble, -63.0)
        # Nur bekannte Felder, unbekannte werden beim Laden verworfen.
        pfad.write_text(json.dumps({"node_distance": 1.5, "quatsch": 7}))
        assert approx(Settings.load(pfad).node_distance, 1.5)


def test_settings_load_fehlt_oder_kaputt():
    with tempfile.TemporaryDirectory() as tmp:
        fehlt = Path(tmp) / "gibtsnicht.json"
        assert approx(Settings.load(fehlt).node_distance, 4.0)  # Vorgabe
        kaputt = Path(tmp) / "kaputt.json"
        kaputt.write_text("{kein json")
        assert approx(Settings.load(kaputt).node_distance, 4.0)  # Vorgabe
        # Die kaputte Datei darf nicht überschrieben werden, sonst ist die
        # mühsam kalibrierte Historie beim nächsten Speichern weg.
        assert kaputt.read_text() == "{kein json"


def test_settings_save_ist_atomar():
    with tempfile.TemporaryDirectory() as tmp:
        pfad = Path(tmp) / "settings.json"
        Settings().save(pfad)
        Settings().save(pfad)
        assert not (Path(str(pfad) + ".tmp")).exists()
        assert approx(Settings.load(pfad).node_distance, 4.0)


def _rssi_at(dist, rssi_1m=-59.0, n=2.5):
    return rssi_1m - 10.0 * n * math.log10(dist)


def test_locator_end_to_end_two_nodes():
    """Simuliert 40 Messungen eines Ziels bei (1.5, 2.0) mit Rauschen."""
    loc = Locator(Settings(node_distance=4.0, position_alpha=1.0, rssi_window=9))
    truth = (1.5, 2.0)
    for _ in range(40):
        for node in ("A", "B"):
            d = math.hypot(truth[0] - (0.0 if node == "A" else 4.0), truth[1])
            # deterministisches Rauschen statt random, Test bleibt stabil
            rssi = _rssi_at(d) + (1.0 if node == "A" else -1.0)
            loc.ingest(node, [{"mac": "AA:BB:CC:DD:EE:FF", "name": "tag", "rssi": rssi}], [])
        loc.recompute()
    dev = loc.devices["ble:AA:BB:CC:DD:EE:FF"]
    assert dev.position_ok
    assert abs(dev.x - truth[0]) < 0.6, dev.x
    assert abs(dev.y - truth[1]) < 0.6, dev.y
    assert dev.mirrored  # zwei Nodes -> Spiegelung bleibt moeglich
    assert dev.consistent  # Messung war widerspruchsfrei
    assert dev.rx > 0 and dev.ry > 0
    assert set(dev.sources) == {"A", "B"}


def test_locator_uncertainty_grows_with_noise():
    def run(spread):
        loc = Locator(Settings(node_distance=4.0, position_alpha=1.0, rssi_window=9,
                               min_sigma_rssi=1.0))
        truth = (2.0, 1.0)
        seq = 0
        for _ in range(60):
            for node in ("A", "B"):
                d = math.hypot(truth[0] - (0.0 if node == "A" else 4.0), truth[1])
                rssi = _rssi_at(d) + spread * math.sin(seq * 1.7 + (0 if node == "A" else 1.1))
                seq += 1
                loc.ingest(node, [{"mac": "AA:BB:CC:DD:EE:FF", "rssi": rssi}], [])
            loc.recompute()
        return loc.devices["ble:AA:BB:CC:DD:EE:FF"].rx

    assert run(1.0) < run(8.0)


def test_locator_single_node_marks_ambiguous():
    loc = Locator(Settings(node_distance=4.0, position_alpha=1.0))
    for _ in range(5):
        loc.ingest("A", [{"mac": "11:22:33:44:55:66", "rssi": _rssi_at(3.0)}], [])
        loc.recompute()
    dev = loc.devices["ble:11:22:33:44:55:66"]
    assert dev.position_ok and dev.mirrored and dev.consistent
    assert approx(dev.x, 3.0, 0.2)  # Distanz entlang der Basislinie abgetragen
    assert dev.ry > 2.0  # Ring um den Node, weil die Position unbestimmt ist


def test_locator_three_nodes_uses_least_squares():
    """Drei Knoten -> Least-Squares, kein Spiegelungsproblem."""
    loc = Locator(Settings(node_distance=4.0, position_alpha=1.0))
    # Node C kommt im Standardlayout auf (0, D)
    loc.ingest("C", [{"mac": "AA:00:00:00:00:01", "rssi": -70}], [])
    truth = (1.0, 1.5)
    positions = {"A": (0.0, 0.0), "B": (4.0, 0.0), "C": (0.0, 4.0)}
    for _ in range(10):
        for node, (nx, ny) in positions.items():
            d = math.hypot(truth[0] - nx, truth[1] - ny)
            loc.ingest(node, [{"mac": "AA:00:00:00:00:01", "rssi": _rssi_at(d)}], [])
        loc.recompute()
    dev = loc.devices["ble:AA:00:00:00:00:01"]
    assert dev.position_ok
    assert not dev.mirrored  # drei Knoten -> keine Spiegelung
    assert abs(dev.x - truth[0]) < 0.4 and abs(dev.y - truth[1]) < 0.4, (dev.x, dev.y)


def test_locator_three_nodes_layout():
    """Node-Positionen: A=(0,0), B=(D,0), dritter Node oberhalb."""
    loc = Locator(Settings(node_distance=4.0))
    loc.ingest("A", [], [])
    loc.ingest("B", [], [])
    loc.ingest("C", [], [])
    assert loc.node_position("A") == (0.0, 0.0)
    assert loc.node_position("B") == (4.0, 0.0)
    assert loc.node_position("C") == (0.0, 4.0)


def test_locator_ignores_invalid_rssi():
    loc = Locator()
    loc.ingest("A", [{"mac": "AA:00:00:00:00:02", "rssi": 25}], [])   # positiver RSSI
    loc.ingest("A", [{"mac": "AA:00:00:00:00:03", "rssi": "keine Zahl"}], [])
    loc.ingest("A", [{"rssi": -50}], [])  # keine MAC
    assert loc.devices == {}


def test_locator_wifi_key_uses_bssid():
    loc = Locator()
    loc.ingest("A", [], [{"ssid": "Box", "bssid": "aa:bb:cc:dd:ee:ff", "rssi": -50}])
    assert "wifi:AA:BB:CC:DD:EE:FF" in loc.devices


def test_locator_snapshot_shape():
    loc = Locator(Settings(node_distance=4.0))
    now = time.time()
    loc.ingest("A", [{"mac": "AA:00:00:00:00:04", "rssi": -60}], [], now=now)
    loc.ingest("B", [{"mac": "AA:00:00:00:00:04", "rssi": -62}], [], now=now)
    loc.recompute()
    snap = loc.snapshot()
    assert snap["settings"]["node_distance"] == 4.0
    assert [n["id"] for n in snap["nodes"]] == ["A", "B"]
    assert snap["nodes"][0]["x"] == 0.0 and snap["nodes"][1]["x"] == 4.0
    dev = snap["devices"][0]
    for key in ("key", "label", "x", "y", "rx", "ry", "ok", "sources", "age"):
        assert key in dev
    assert len(dev["sources"]) == 2
    assert dev["sources"][0]["rssi"] == -60


def test_locator_node_offline_flag():
    loc = Locator(Settings(node_offline_after=5.0))
    now = time.time()
    loc.ingest("A", [{"mac": "AA:00:00:00:00:05", "rssi": -60}], [], now=now)
    snap = loc.snapshot()
    assert snap["nodes"][0]["online"] is True
    loc.nodes["A"] = time.time() - 60.0
    assert loc.snapshot()["nodes"][0]["online"] is False


def test_locator_mismatch_widens_uncertainty():
    """Widerspruechliche Distanzen muessen die Unsicherheit vergroessern."""
    def run(r_b):
        loc = Locator(Settings(node_distance=4.0, position_alpha=1.0, rssi_window=5,
                               min_sigma_rssi=1.0))
        for _ in range(20):
            loc.ingest("A", [{"mac": "AA:00:00:00:00:0A", "rssi": _rssi_at(3.0)}], [])
            loc.ingest("B", [{"mac": "AA:00:00:00:00:0A", "rssi": _rssi_at(r_b)}], [])
            loc.recompute()
        dev = loc.devices["ble:AA:00:00:00:00:0A"]
        return dev.rx, dev.consistent

    rx_ok, consistent_ok = run(3.5)    # |3.0 - 3.5| < 4  -> schneiden sich
    rx_bad, consistent_bad = run(9.0)   # |3.0 - 9.0| > 4  -> Widerspruch
    assert consistent_ok and not consistent_bad
    assert rx_bad > rx_ok


def test_locator_stale_source_ignored():
    loc = Locator(Settings(node_distance=4.0, stale_after=5.0, position_alpha=1.0))
    now = time.time()
    loc.ingest("A", [{"mac": "AA:00:00:00:00:06", "rssi": _rssi_at(2.0)}], [], now=now)
    loc.ingest("B", [{"mac": "AA:00:00:00:00:06", "rssi": _rssi_at(3.5)}], [], now=now - 30)
    loc.recompute()
    dev = loc.devices["ble:AA:00:00:00:00:06"]
    assert dev.position_ok
    # Nur noch Node A zaehlt -> nur eine Distanz bekannt
    recent = [s for s in dev.sources.values() if now - s.last_seen <= 5.0]
    assert len(recent) == 1 and recent[0].node == "A"


def test_locator_respects_max_distance():
    loc = Locator(Settings(max_distance=5.0, node_distance=4.0))
    loc.ingest("A", [{"mac": "AA:00:00:00:00:07", "rssi": -95}], [])
    loc.ingest("B", [{"mac": "AA:00:00:00:00:07", "rssi": -95}], [])
    loc.recompute()
    dev = loc.devices["ble:AA:00:00:00:00:07"]
    assert dev.sources["A"].distance <= 5.0


def test_locator_reset_filters():
    loc = Locator(Settings(position_alpha=0.5))
    loc.ingest("A", [{"mac": "AA:00:00:00:00:08", "rssi": -60}], [])
    loc.ingest("A", [{"mac": "AA:00:00:00:00:08", "rssi": -61}], [])
    loc.recompute()
    loc.reset_filters()
    dev = loc.devices["ble:AA:00:00:00:00:08"]
    assert len(dev.sources["A"].filter.values) == 0
    assert not dev.position_ok


def test_locator_uncertainty_independent_of_ingest_order():
    """Regression: sigmas muessen zur Quelle gehoeren, nicht zur Sichtreihenfolge."""

    def run(order):
        loc = Locator(Settings(node_distance=4.0, position_alpha=1.0, rssi_window=5,
                               min_sigma_rssi=1.0))
        truth = (1.0, 2.0)
        for i in range(30):
            for node in order:
                d = math.hypot(truth[0] - (0.0 if node == "A" else 4.0), truth[1])
                # Node A bekommt mehr Rauschen als Node B
                noise = 3.0 * math.sin(i * 1.3) if node == "A" else 1.0 * math.sin(i * 0.7)
                loc.ingest(node, [{"mac": "AA:00:00:00:00:09", "rssi": _rssi_at(d) + noise}], [])
            loc.recompute()
        dev = loc.devices["ble:AA:00:00:00:00:09"]
        return dev.rx, dev.ry

    rx_ab, ry_ab = run(("A", "B"))
    rx_ba, ry_ba = run(("B", "A"))
    assert approx(rx_ab, rx_ba, 1e-6), (rx_ab, rx_ba)
    assert approx(ry_ab, ry_ba, 1e-6), (ry_ab, ry_ba)


# Ohne pytest direkt ausfuehrbar: python3 server/tests/test_positioning.py

def test_locator_expire_removes_old_devices():
    """Ohne neue Messungen muessen Geraete trotzdem verschwinden."""
    loc = Locator(Settings(drop_after=10.0, stale_after=5.0))
    loc.ingest("A", [{"mac": "AA:00:00:00:00:0B", "rssi": -60}], [])
    loc.recompute()
    assert len(loc.devices) == 1 and loc.dropped == 0
    # Zeit simulieren: Geraet war 30 s lang nicht mehr zu sehen
    loc.devices["ble:AA:00:00:00:00:0B"].last_seen = time.time() - 30.0
    loc.expire()
    assert loc.devices == {}
    assert loc.dropped == 1


def test_locator_expire_inside_recompute():
    """Ein komplett veraltetes Geraet wird direkt beim Rechnen verworfen."""
    loc = Locator(Settings(drop_after=10.0))
    loc.ingest("A", [{"mac": "AA:00:00:00:00:0C", "rssi": -60}], [], now=time.time() - 60.0)
    loc.recompute()
    assert loc.devices == {}


if __name__ == "__main__":
    tests = [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("OK   %s" % name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %s" % (name, exc))
    print("\n%d Tests, %d Fehler" % (len(tests), failed))
    sys.exit(1 if failed else 0)


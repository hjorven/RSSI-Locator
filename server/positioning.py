"""RSSI -> Distanz -> Position.

Alle Längen in Metern, RSSI in dBm, Zeiten in Unix-Sekunden.

Kern der Schätzung:
1. RSSI je (Gerät, Node) glätten (Median über die letzten N Messungen).
2. Aus der Streuung der Messungen eine RSSI-Unsicherheit ableiten.
3. Log-Distance-Modell: d = 10 ** ((RSSI_1m - RSSI) / (10 * n))
4. Position aus den Distanzen bestimmen:
   - 2 Nodes: Schnitt zweier Kreise, Spiegelung wird mit y >= 0 aufgelöst.
   - 3+ Nodes: Least-Squares-Trilateration ohne Spiegelungsproblem.
5. Position glätten (exponentieller Filter).
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Glättung
# ---------------------------------------------------------------------------

#: Standardkonfiguration, überschreibbar über die Weboberfläche.
DEFAULT_SETTINGS: "Settings" = None  # type: ignore[assignment]


def median(values: Sequence[float]) -> float:
    """Median einer Zahlenfolge (ungerade/gerde Länge)."""
    if not values:
        raise ValueError("leere Folge")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def mad_sigma(values: Sequence[float]) -> float:
    """Robuste Standardabweichung aus dem Median-Absolutabweichungswert.

    Outlier in RSSI-Messungen sind häufig (Funkstörung, Reflexion), deshalb MAD
    statt klassischer Standardabweichung. Skalierung 1.4826 macht MAD bei
    Normalverteilung zur Schätzerin der sigma.
    """
    if len(values) < 2:
        return 0.0
    m = median(values)
    return 1.4826 * median([abs(v - m) for v in values])


class RssiFilter:
    """Median-Glättung plus Streuungsschätzung über ein gleitendes Fenster."""

    def __init__(self, window: int = 7) -> None:
        self.window = max(1, int(window))
        self._values: deque = deque(maxlen=self.window)

    def add(self, rssi: float) -> float:
        self._values.append(float(rssi))
        return self.smoothed

    @property
    def values(self) -> List[float]:
        return list(self._values)

    @property
    def smoothed(self) -> float:
        return median(self._values)

    @property
    def sigma(self) -> float:
        """RSSI-Streuung in dB, mindestens `floor_sigma`."""
        if len(self._values) < 3:
            return 0.0
        return mad_sigma(self._values)

    def set_window(self, window: int) -> None:
        self.window = max(1, int(window))
        self._values = deque(self._values, maxlen=self.window)

    def clear(self) -> None:
        self._values.clear()


@dataclass
class Ema:
    """Exponentieller Mittelwert mit einstellbarem Glättungsfaktor."""

    alpha: float
    value: Optional[float] = None

    def update(self, x: float) -> float:
        a = min(1.0, max(0.0, self.alpha))
        if self.value is None:
            self.value = float(x)
        else:
            self.value += a * (float(x) - self.value)
        return self.value

    def reset(self) -> None:
        self.value = None


# ---------------------------------------------------------------------------
# Distanzmodell
# ---------------------------------------------------------------------------


def rssi_to_distance(rssi: float, rssi_1m: float, path_loss: float) -> float:
    """Log-Distance-Modell.

    d = 10 ** ((RSSI_1m - RSSI) / (10 * n))

    rssi_1m: gemessener RSSI in 1 m Abstand (negativ)
    path_loss: Umgebungsfaktor n, 2 = freie Sicht, 3 = Wohnung
    """
    n = max(0.5, float(path_loss))
    return 10.0 ** ((float(rssi_1m) - float(rssi)) / (10.0 * n))


def distance_sigma(dist: float, sigma_rssi: float, path_loss: float) -> float:
    """Unsicherheit der Distanz durch RSSI-Streuung (lineare Näherung).

    d(d)/d(RSSI) = -ln(10)/10n * d  =>  sigma_d = |d(d)/d(RSSI)| * sigma_RSSI
    """
    n = max(0.5, float(path_loss))
    return abs(math.log(10.0) / (10.0 * n)) * float(dist) * float(sigma_rssi)


# ---------------------------------------------------------------------------
# Geometrie
# ---------------------------------------------------------------------------


def trilaterate_2_nodes(
    d_a: float, d_b: float, node_distance: float
) -> Tuple[float, float, bool]:
    """Schnitt zweier Kreise, Nodes bei A=(0,0) und B=(D,0).

    Rückgabe (x, y, geschnitten):
    - geschnitten=True: Kreise schneiden sich, es gibt zwei spiegelbildliche
      Lösungen; wir wählen y >= 0.
    - geschnitten=False: die Distanzen widersprechen der Geometrie
      (|d_A - d_B| > D). Dann liegt kein Punkt in der Ebene beide Kreise.
      Zulässig sind nur die Punkte auf der Basislinie außerhalb der Strecke, und
      dort liegt das Optimum der kleinsten Quadrate exakt in der Mitte:
      x = (d_A + d_B + D)/2, wenn d_A > d_B (Punkt hinter Node B), sonst
      x = (D - d_A - d_B)/2 (Punkt hinter Node A). Der Punkt kann also durchaus
      außerhalb der Strecke A-B liegen — dort ist das Gerät weiter weg als D.
    """
    D = max(1e-6, float(node_distance))
    r1, r2 = float(d_a), float(d_b)
    if abs(r1 - r2) > D:
        x = (r1 + r2 + D) / 2.0 if r1 > r2 else (D - r1 - r2) / 2.0
        return (x, 0.0, False)
    x = (r1 * r1 - r2 * r2 + D * D) / (2.0 * D)
    y_sq = r1 * r1 - x * x
    if y_sq <= 0.0:
        # Tangentiale Berührung: ein Punkt auf der Basislinie.
        return (x, 0.0, False)
    return (x, math.sqrt(y_sq), True)


def _solve(matrix: List[List[float]], rhs: List[float]) -> Optional[List[float]]:
    """Lineares Gleichungssystem per Gauss-Elimination mit Spaltenpivotisierung."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-9:
            return None  # singulär: keine eindeutige Lösung (Nodes zu nah beieinander)
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            if factor:
                for k in range(col, n + 1):
                    a[row][k] -= factor * a[col][k]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        s = a[row][n] - sum(a[row][k] * x[k] for k in range(row + 1, n))
        x[row] = s / a[row][row]
    return x


def trilaterate_linear(
    dists: Sequence[float], node_pos: Sequence[Tuple[float, float]]
) -> Optional[Tuple[float, float]]:
    """Least-Squares-Trilateration für 3+ Nodes.

    Für jede Messung gilt: (x-x_i)^2 + (y-y_i)^2 = d_i^2. Nach Subtraktion der
    Gleichung des Referenz-Nodes bleibt ein lineares System in x, y, das über
    Normalengleichungen gelöst wird. Liefert None, wenn das System singulär ist
    (z. B. alle Nodes auf einer Geraden).
    """
    if len(dists) < 3 or len(dists) != len(node_pos):
        return None
    x0, y0 = node_pos[0]
    normal = [[0.0, 0.0], [0.0, 0.0]]
    rhs = [0.0, 0.0]
    for d, (xi, yi) in zip(dists, node_pos):
        dx = xi - x0
        dy = yi - y0
        # 2*dx*x + 2*dy*y = d0^2 - d^2 + (xi^2+yi^2) - (x0^2+y0^2)
        b = (dists[0] ** 2 - d ** 2) + (xi * xi + yi * yi) - (x0 * x0 + y0 * y0)
        for i, comp in enumerate((dx, dy)):
            rhs[i] += comp * b
            for j, comp2 in enumerate((dx, dy)):
                normal[i][j] += comp * comp2
    sol = _solve(normal, rhs)
    if sol is None:
        return None
    return (sol[0] / 2.0, sol[1] / 2.0)


# ---------------------------------------------------------------------------
# Settings und Datenstrukturen
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    """Laufende Parameter. Über `/api/settings` änderbar, wirkt sofort."""

    node_distance: float = 4.0
    rssi_1m_ble: float = -59.0
    rssi_1m_wifi: float = -45.0
    path_loss_ble: float = 2.5
    path_loss_wifi: float = 3.0
    rssi_window: int = 7
    position_alpha: float = 0.35
    min_sigma_rssi: float = 3.0
    stale_after: float = 10.0
    drop_after: float = 120.0
    node_offline_after: float = 5.0
    max_distance: float = 30.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "node_distance": self.node_distance,
            "rssi_1m_ble": self.rssi_1m_ble,
            "rssi_1m_wifi": self.rssi_1m_wifi,
            "path_loss_ble": self.path_loss_ble,
            "path_loss_wifi": self.path_loss_wifi,
            "rssi_window": self.rssi_window,
            "position_alpha": self.position_alpha,
            "min_sigma_rssi": self.min_sigma_rssi,
            "stale_after": self.stale_after,
            "drop_after": self.drop_after,
            "node_offline_after": self.node_offline_after,
            "max_distance": self.max_distance,
        }

    def update(self, values: Dict[str, float]) -> None:
        """Übernimmt nur bekannte Felder, clamp't sinnvolle Grenzen."""
        limits = {
            "node_distance": (0.1, 100.0),
            "rssi_1m_ble": (-100.0, 0.0),
            "rssi_1m_wifi": (-100.0, 0.0),
            "path_loss_ble": (1.0, 6.0),
            "path_loss_wifi": (1.0, 6.0),
            "rssi_window": (1, 51),
            "position_alpha": (0.01, 1.0),
            "min_sigma_rssi": (0.5, 30.0),
            "stale_after": (1.0, 300.0),
            "drop_after": (5.0, 3600.0),
            "node_offline_after": (1.0, 300.0),
            "max_distance": (1.0, 200.0),
        }
        for key, value in values.items():
            if key not in limits:
                continue
            lo, hi = limits[key]
            val = float(value)
            if key in ("rssi_window",):
                val = int(round(val))
            setattr(self, key, min(hi, max(lo, val)))
        if self.drop_after <= self.stale_after:
            self.drop_after = self.stale_after + 1.0


@dataclass
class Source:
    """Messreihe eines Geräts an einem Node."""

    node: str
    filter: RssiFilter
    last_seen: float
    distance: float = 0.0
    sigma_rssi: float = 0.0

    @property
    def rssi(self) -> float:
        return self.filter.smoothed


@dataclass
class Device:
    """Ein beobachtetes Gerät (BLE-Adresse oder WLAN-BSSID)."""

    key: str
    kind: str  # "ble" oder "wifi"
    label: str
    first_seen: float
    last_seen: float
    sources: Dict[str, Source] = field(default_factory=dict)
    x: float = 0.0
    y: float = 0.0
    rx: float = 0.0
    ry: float = 0.0
    position_ok: bool = False
    mirrored: bool = True     # mit 2 Nodes gibt es zwei gleichwertige Lösungen
    consistent: bool = True   # Kreise schneiden sich (Messung konsistent)
    _fx: Ema = field(default_factory=lambda: Ema(0.35))
    _fy: Ema = field(default_factory=lambda: Ema(0.35))

    @property
    def age(self) -> float:
        return time.time() - self.last_seen


class Locator:
    """Hält Nodes, Geräte und Einstellungen und liefert den Zustand für die UI."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.devices: Dict[str, Device] = {}
        self.nodes: Dict[str, float] = {}  # Node-ID -> letzte Empfangszeit
        self.started = time.time()
        self.dropped = 0  # Anzahl verworfener Geräte (Diagnose)

    # -- Aufrufe aus dem Server -------------------------------------------

    def ingest(
        self,
        node: str,
        ble: Iterable[dict],
        wifi: Iterable[dict],
        now: Optional[float] = None,
    ) -> None:
        """Übernimmt einen Messdatensatz eines Nodes."""
        ts = now if now is not None else time.time()
        self.nodes[node] = ts
        for entry in ble or []:
            self._add_observation(node, "ble", entry, ts)
        for entry in wifi or []:
            self._add_observation(node, "wifi", entry, ts)

    def _add_observation(
        self, node: str, kind: str, entry: dict, ts: float
    ) -> None:
        key = self._device_key(kind, entry)
        if not key:
            return
        try:
            rssi = float(entry.get("rssi"))
        except (TypeError, ValueError):
            return
        if not -120.0 <= rssi <= 0.0:
            return  # unplausibel, meistens Programmfehler im Node

        device = self.devices.get(key)
        if device is None:
            label = str(entry.get("name") or entry.get("ssid") or key)
            device = Device(
                key=key,
                kind=kind,
                label=label,
                first_seen=ts,
                last_seen=ts,
            )
            self.devices[key] = device

        device.last_seen = max(device.last_seen, ts)
        source = device.sources.get(node)
        if source is None or source.filter.window != self.settings.rssi_window:
            filt = RssiFilter(self.settings.rssi_window)
            if source is not None:
                for value in source.filter.values:
                    filt.add(value)
            source = Source(node=node, filter=filt, last_seen=ts)
            device.sources[node] = source
        source.filter.add(rssi)
        source.last_seen = max(source.last_seen, ts)
        source.sigma_rssi = source.filter.sigma
        source.distance = rssi_to_distance(
            source.rssi, *self._model(kind)
        )

    @staticmethod
    def _device_key(kind: str, entry: dict) -> str:
        if kind == "ble":
            mac = str(entry.get("mac") or "").strip().upper()
            return f"ble:{mac}" if mac else ""
        bssid = str(entry.get("bssid") or "").strip().upper()
        if not bssid:
            ssid = str(entry.get("ssid") or "")
            return f"wifi:{ssid}" if ssid else ""
        return f"wifi:{bssid}"

    def _model(self, kind: str) -> Tuple[float, float]:
        """(RSSI_1m, path_loss) je Protokoll."""
        s = self.settings
        if kind == "ble":
            return (s.rssi_1m_ble, s.path_loss_ble)
        return (s.rssi_1m_wifi, s.path_loss_wifi)

    # -- Berechnung --------------------------------------------------------

    def recompute(self) -> None:
        """Positionen aller Geräte neu bestimmen und veraltete entfernen."""
        s = self.settings
        for key, device in list(self.devices.items()):
            device._fx.alpha = s.position_alpha
            device._fy.alpha = s.position_alpha
            self._recompute_device(device)
        self.expire()

    def expire(self) -> None:
        """Geräte entfernen, die zu lange nichts mehr gesehen wurden.

        Wird auch ohne neue Messdaten regelmäßig aufgerufen, sonst bleiben
        Geräte endgültig im Speicher, wenn alle Nodes offline gehen.
        """
        now = time.time()
        stale = [k for k, d in self.devices.items() if now - d.last_seen > self.settings.drop_after]
        for key in stale:
            del self.devices[key]
        if stale:
            self.dropped += len(stale)

    def _recompute_device(self, device: Device) -> None:
        s = self.settings
        recent = [
            src
            for src in device.sources.values()
            if time.time() - src.last_seen <= s.stale_after
        ]
        if not recent:
            device.position_ok = False
            return
        for src in device.sources.values():
            src.sigma_rssi = max(s.min_sigma_rssi, src.filter.sigma)
            src.distance = min(
                rssi_to_distance(src.rssi, *self._model(device.kind)),
                s.max_distance,
            )
        sigmas = [
            distance_sigma(src.distance, src.sigma_rssi, self._model(device.kind)[1])
            for src in recent
        ]

        if len(recent) <= 2:
            self._solve_two_nodes(device, recent, sigmas)
        else:
            self._solve_least_squares(device, recent, sigmas)

        if device.position_ok:
            device.x = device._fx.update(device.x)
            device.y = device._fy.update(device.y)

    def reset_filters(self) -> None:
        """Alle Filter verwerfen — nötig, wenn sich Kalibrierwerte stark ändern."""
        for device in self.devices.values():
            for src in device.sources.values():
                src.filter.clear()
            device._fx.reset()
            device._fy.reset()
            device.position_ok = False

    def _solve_two_nodes(
        self, device: Device, sources: List[Source], sigmas: List[float]
    ) -> None:
        """Zwei Knoten: Schnitt zweier Kreise, Spiegelung per y >= 0 aufgelöst."""
        s = self.settings
        if len(sources) == 1:
            # Nur ein Knoten: nur die Distanz bekannt, die Position ist ein
            # Kreis um den Node. Wir zeigen den Punkt auf der Verbindungslinie
            # in Richtung des zweiten Knoten und die volle Distanz als ry.
            d = sources[0].distance
            device.x, device.y = d, 0.0
            device.rx = 1.96 * sigmas[0]
            device.ry = d
            device.position_ok = True
            device.mirrored = True
            device.consistent = True
            return

        # Quelle und ihre Unsicherheit zusammen sortieren, sonst werden die
        # sigma-Werte vertauscht, wenn die Reihenfolge der Sichtungen abweicht.
        pairs = sorted(zip(sources, sigmas), key=lambda p: p[0].node)
        (sa, sig_a), (sb, sig_b) = pairs[0], pairs[1]
        d_a, d_b = sa.distance, sb.distance
        D = s.node_distance
        x, y, hit = trilaterate_2_nodes(d_a, d_b, D)
        device.x, device.y = x, y
        device.position_ok = True
        device.mirrored = True  # mit 2 Knoten ist y nur "ungefähr" bekannt
        device.consistent = hit

        # Wie weit die beiden Distanzen der Geometrie widersprechen. Das ist ein
        # systematischer Anteil in der Unsicherheit, den das Rauschen allein nicht
        # abdeckt.
        mismatch = max(0.0, abs(d_a - d_b) - D)

        # Unsicherheit über die Fehlerfortpflanzung der Kreis-Intersection.
        dx_da, dx_db = d_a / D, -d_b / D
        sig_x = math.sqrt((dx_da * sig_a) ** 2 + (dx_db * sig_b) ** 2)
        device.rx = 1.96 * sig_x + mismatch / 2.0
        if hit and y > 0.25:
            dy_da = (d_a - x * dx_da) / y
            dy_db = (-x * dx_db) / y
            sig_y = math.sqrt((dy_da * sig_a) ** 2 + (dy_db * sig_b) ** 2)
            device.ry = 1.96 * sig_y
        else:
            # Auf der Basislinie ist die y-Richtung schlecht bestimmt: die
            # Unsicherheit ist dort mindestens so groß wie die Distanzunsicherheit.
            device.ry = 1.96 * max(sig_a, sig_b) + mismatch / 2.0

    def _solve_least_squares(
        self, device: Device, sources: List[Source], sigmas: List[float]
    ) -> None:
        """Drei oder mehr Knoten: Least-Squares ohne Spiegelungsproblem."""
        s = self.settings
        nodes = sorted(self.devices_node_ids())
        positions = [self.node_position(n) for n in nodes]
        index = {n: i for i, n in enumerate(nodes)}
        used = [(src, positions[index[src.node]]) for src in sources if src.node in index]
        if len(used) < 3:
            self._solve_two_nodes(device, [u[0] for u in used], sigmas)
            return
        dists = [src.distance for src, _ in used]
        sol = trilaterate_linear(dists, [pos for _, pos in used])
        if sol is None:
            self._solve_two_nodes(device, [u[0] for u in used], sigmas)
            return
        device.x, device.y = sol
        device.position_ok = True
        device.mirrored = False  # drei oder mehr Knoten: keine Spiegelung
        device.consistent = True
        mean_sigma = sum(sigmas) / len(sigmas)
        device.rx = device.ry = 1.96 * mean_sigma

    def devices_node_ids(self) -> List[str]:
        return sorted(self.nodes.keys())

    def node_position(self, node: str) -> Tuple[float, float]:
        """Node A = (0,0), Node B = (D,0), weitere Nodes auf der y-Achse.

        Layout ist bewusst simpel: die ersten beiden Knoten bilden die Basislinie,
        jeder weitere kommt um `node_distance` nach oben. Damit ist das Layout
        ohne Konfiguration verständlich und später per Node-Konfiguration austauschbar.
        """
        s = self.settings
        ids = sorted(self.nodes.keys())
        if node not in ids:
            return (0.0, 0.0)
        idx = ids.index(node)
        if idx == 0:
            return (0.0, 0.0)
        if idx == 1:
            return (s.node_distance, 0.0)
        return (0.0, s.node_distance * (idx - 1))

    # -- Ausgabe für die Weboberfläche ------------------------------------

    def snapshot(self) -> dict:
        now = time.time()
        s = self.settings
        nodes = []
        for node, ts in sorted(self.nodes.items()):
            x, y = self.node_position(node)
            nodes.append(
                {
                    "id": node,
                    "x": x,
                    "y": y,
                    "last_seen": ts,
                    "online": (now - ts) <= s.node_offline_after,
                }
            )
        devices = []
        for device in self.devices.values():
            if now - device.last_seen > s.drop_after:
                continue
            sources = []
            for src in sorted(device.sources.values(), key=lambda x: x.node):
                sources.append(
                    {
                        "node": src.node,
                        "rssi": round(src.rssi, 1),
                        "sigma": round(src.sigma_rssi, 1),
                        "dist": round(src.distance, 2),
                        "age": round(now - src.last_seen, 1),
                    }
                )
            devices.append(
                {
                    "key": device.key,
                    "kind": device.kind,
                    "label": device.label,
                    "x": round(device.x, 2),
                    "y": round(device.y, 2),
                    "rx": round(device.rx, 2),
                    "ry": round(device.ry, 2),
                    "ok": device.position_ok,
                    "mirrored": device.mirrored,
                    "consistent": device.consistent,
                    "age": round(device.age, 1),
                    "first_seen": device.first_seen,
                    "sources": sources,
                }
            )
        devices.sort(key=lambda d: (not d["ok"], d["age"]))
        return {
            "ts": now,
            "uptime": now - self.started,
            "dropped": self.dropped,
            "settings": s.to_dict(),
            "nodes": nodes,
            "devices": devices,
        }


DEFAULT_SETTINGS = Settings()
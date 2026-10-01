# Offene Punkte

## Erledigt

- Server mit `/ingest`, `/ws`, `/api/state`, `/api/settings`, `/api/reset`
- Weboberfläche: Canvas mit Meterraster, Unsicherheitsellipsen, Seitenliste,
  Online-Status, Einstellungen im UI
- Positionsberechnung: Median-Glättung, Log-Distance, Kreis-Intersection für
  zwei Nodes, Least-Squares ab drei Nodes, Unsicherheitsellipsen
- Simulator mit Bewegung, Rauschen, Ausreißern und Wegfallen der Geräte
- 33 Unit-Tests für die Rechnung, 8 für den Node-Parser, End-to-End-Rauchtest
  inklusive WebSocket
- Deployment auf dem Pi 4 B per venv und systemd, Autostart aktiv
- Firmware für Pico 2 W (WLAN, abwechselnder BLE-/WLAN-Scan, HTTP-POST per
  Socket, BLE-Beacon zur Node-Erkennung)
- Node-Client für Linux (`pi-node/`): WLAN-Vollscan über `iw` mit echten dBm,
  BLE-Scan über `bleak`, läuft als Node A auf dem Pi 4 B und liefert 39 Geräte
  in die Weboberfläche

## Offen

### Hardware

- Kein Pico 2 W angeschlossen. Die Firmware ist ungetestet; die ersten beiden
  Testläufe (WLAN, dann BLE, dann zusammen) stehen aus.
- Der angeschlossene Pico 2 (ohne W, CircuitPython 9.2.0-beta) kann weder
  scannen noch senden — ausgelesen und bestätigt, es fehlen `network`, `wifi`
  und `bluetooth`. Ein Pico 2 W ist eine andere Platine, MicroPython hilft dort
  nicht.

### Nodeabstand automatisch messen

Die Nodes erkennen sich gegenseitig über ihre BLE-Werbesendung
(`config.py: BEACON_ADVERTISE`). Der Wert `node_link` wird im Scan ausgewertet,
landet aber noch nicht im JSON-Payload des Nodes. Der Server könnte daraus den
gemessenen Nodeabstand ableiten und `D` vorschlagen — die UI müsste den Wert
übernehmen. Betrifft: `firmware/node/main.py` (Payload), `positioning.py`
(Vorschlag statt Fixwert), `index.html` (Button).

### Genauigkeit

- Kalibrierung mit echtem Beacon steht aus, siehe `docs/kalibrierung.md`.
- Ein dritter Node würde die Spiegelung auflösen und die Least-Squares-Lösung
  deutlich verbessern. Der Code unterstützt 3+ Nodes bereits, das Standardlayout
  legt aber jeden weiteren Node auf die y-Achse. Eine echte Knotenkonfiguration
  (`nodes.json` mit Koordinaten) fehlt.

### Bedienung

- Kein Verlauf, keine Heatmap, keine Geräteliste zum Ausblenden.
- Kein Filter je Gerät (nur global).
- Kein Logging der Rohdaten, was eine spätere Auswertung "wie sah der Raum aus"
  unmöglich macht. Ein Ringpuffer im Arbeitsspeicher wäre billig.

### Betrieb

- Der Dienst läuft ungesichert über HTTP. Wenn das WLAN nicht vertrauenswürdig
  ist, gehören Nodes und Browser hinter ein Passwort oder TLS.
- Kein Health-Check-Alarm: fällt der Dienst aus, fällt es nur auf, wenn man
  nachsieht.
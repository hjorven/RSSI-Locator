# Offene Punkte

## Erledigt

- Server mit `/ingest`, `/ws`, `/api/state`, `/api/settings`, `/api/reset`
- Weboberfläche: Canvas mit Meterraster, Unsicherheitsellipsen, Seitenliste,
  Online-Status, Einstellungen im UI
- Positionsberechnung: Median-Glättung, Log-Distance, Kreis-Intersection für
  zwei Nodes, Least-Squares ab drei Nodes, Unsicherheitsellipsen
- Simulator mit Bewegung, Rauschen, Ausreißern und Wegfallen der Geräte
- 36 Unit-Tests für die Rechnung, 8 für den Node-Parser, End-to-End-Rauchtest
  inklusive WebSocket
- Deployment auf dem Pi 4 B per venv und systemd, Autostart aktiv
- Einstellungen werden als `server/settings.json` gespeichert und überleben
  Neustart und Deployment; Messdaten bleiben im Arbeitsspeicher
- Simulator erfragt die Node-Geometrie beim Server, statt sie anzunehmen.
  Zusammen mit dem Rauchtest, der eigene Test-Nodes verwendet, stimmen
  Erwartungswerte und Serverrechnung wieder überein
- Firmware für Pico 2 W (WLAN, abwechselnder BLE-/WLAN-Scan, HTTP-POST per
  Socket, BLE-Beacon zur Node-Erkennung)
- Node-Client für Linux (`pi-node/`): WLAN-Vollscan über `iw` mit echten dBm,
  BLE-Scan über `bleak`, läuft als Node B auf dem Pi 4 B
- Pico 2 W mit MicroPython 1.29.0 geflasht und als Node A in Betrieb: BLE- und
  WLAN-Scan, HTTP-POST, Beacon aktiv. Sechs Fehler der ersten Firmware-Version
  sind gefunden und behoben (`bluetooth.ble` existiert nicht mehr, `wlan.scan()`
  nimmt kein Argument und liefert Tupel, Start-Timeout beim ersten Senden,
  fehlendes `global` bei `ble_buffer`/`wifi_buffer` und bei `scan_done`)

## Offen

### Hardware

- Ein zweiter Pico 2 W fehlt noch. Node B misst derzeit der Pi 4 B.
- Die serielle Ausgabe des Nodes ist die einzige Anzeige. Für den Dauerbetrieb
  wäre eine Logdatei auf dem Board oder ein Heartbeat-Feld in der Weboberfläche
  praktisch.
- Die beiden Nodes stehen derzeit nur 40 bis 50 cm auseinander. Das ist für die
  Positionierung zu wenig: bei 45 cm liegt der mittlere Positionsfehler bei
  1,9 m, bei 1,5 m Abstand nur noch bei 1,2 m, bei 2 m bei 1,1 m. Siehe
  [Nodeabstand D](kalibrierung.md#nodeabstand-d-der-wichtigste-wert-ueberhaupt).
  **Für brauchbare Positionen die Nodes etwa 2 m auseinanderstellen.**

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
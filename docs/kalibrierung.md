# Kalibrierung

Ohne Kalibrierung stimmen die angezeigten Meter nicht. Zwei Parameter müssen
passen: `RSSI 1 m` (Signalstärke in einem Meter Abstand) und `n`
(Umgebungsfaktor). Beides lässt sich live in der Weboberfläche verstellen und
wirkt sofort.

## 1. Nodeabstand D ausmessen

Lege ein Maßband entlang der Verbindung der beiden Nodes und miss den
Mittelpunkt zwischen den Antennen, nicht zwischen den Gehäusekanten. Den Wert
in `D` eintragen. Bei 1 cm Genauigkeit lohnt sich das: die Positionsschätzung
rechnet `D` direkt in die x-Koordinate ein.

## 2. RSSI 1 m und n bestimmen

Vorgehen: Ein Gerät (am besten ein BLE-Beacon mit festem Sendeleistung) an
definierte Punkte stellen, pro Punkt 20 bis 30 Messungen sammeln, RSSI im
Browser ablesen.

| Abstand | erwarteter RSSI laut Modell |
|---------|------------------------------|
| 1 m     | `RSSI_1m`                    |
| 2 m     | `RSSI_1m - 10 n lg 2`        |
| 4 m     | `RSSI_1m - 10 n lg 4`        |

`n` aus zwei Punkten bestimmen:

```
n = (RSSI_fern - RSSI_nah) / (10 * lg(d_fern / d_nah))
```

Beispiel: 1 m ergibt −60 dB, 4 m ergibt −78 dB
→ `n = (−78 + 60) / (10 * lg 4) = 18 / 6.02 = 3.0` (typische Wohnung).

`RSSI_1m` ist dann der auf 1 m hochgerechnete Wert. Einfacher in der Praxis:
`RSSI_1m` auf den bei 1 m **gemessenen** Wert stellen und `n` variieren, bis
die Anzeige bei allen Punkten passt.

Annahmen des Modells, die in Gebäuden nicht stimmen:

- Der Log-Distance-Ansatz ist für 1 bis 10 m brauchbar, nicht für 0 bis 1 m und
  nicht für > 15 m.
- Der RSSI eines Gerätes hängt im Raum stark davon ab, wo es steht (Türrahmen,
  Möbel, Körper). Deshalb ist die Anzeige der Messwerte in der Seitenliste
  wichtiger als die Position.

## 3. Filter einstellen

| Parameter | Bedeutung | Empfehlung |
|-----------|-----------|------------|
| `RSSI-Fenster` | Anzahl Messungen für den Median | 7 (bei 1 Hz ca. 7 s) |
| `Positionsfilter` | `alpha` des exponentiellen Filters, 0 = steht still, 1 = kein Filter | 0.35 |
| `max_distance` | Geräte darüber werden ignoriert | Raumgröße + 5 m |
| `stale_after` | Node-Messungen älter als das werden nicht mehr verwendet | 10 s |

Nach einer Änderung an `RSSI-Fenster` oder `max_distance` im Browser auf
**Filter zurücksetzen** drücken, sonst mischt sich alte Historie mit neuer
Kalibrierung.

## 4. Genauigkeit prüfen

Test-Beacon an 3 bis 5 bekannten Punkten platzieren, pro Punkt 1 bis 2 Minuten
messen lassen, dann mittleren Fehler und Streuung notieren. Erwartbar sind
1 bis 3 m. Wenn der Fehler stark richtungsabhängig ist (immer zu weit links),
stimmt der Umgebungsfaktor nicht oder die Antennen sitzen unterschiedlich.

## Einstellungen gehen bei einem Neustart verloren

Der Server hält die Einstellungen bewusst nur im Arbeitsspeicher (keine
Datenbank). Nach `systemctl restart rssi-locator` gelten wieder die Vorgaben.
Deshalb nach jedem Serverstart:

```bash
curl -X POST -H "Content-Type: application/json" -d '{"node_offline_after": 12}' \
  http://192.168.178.43:8099/api/settings
```

`node_offline_after` 12 s statt 5 s: ein Pico 2 W braucht bis zu 5 s für einen
BLE-Scan und nochmal bis zu 4 s für einen WLAN-Vollscan. Mit den Vorgabe-Werten
flackert der Node während des WLAN-Scans im Browser als "offline".

## Grenzen des Modells

Die angezeigte Unsicherheitsellipse kommt aus der **RSSI-Streuung** der letzten
Messungen (Median-Absolutabweichung, 95-%-Intervall). Sie erfasst nicht:

- Reflexionen und Mehrwege (diese machen RSSI eher *zu stark*),
- Abschirmung durch Möbel oder Wände (macht RSSI zu schwach),
- systematische Fehler durch unterschiedliche Antennen der beiden Nodes.

Deshalb ist die Ellipse eine Untergrenze der Unsicherheit, besonders bei
schwachen Signalen. Bei `ry` deutlich größer als `rx` liegt das Gerät nahe der
Verbindungslinie der Nodes — dort ist die y-Position am schlechtesten bestimmt.
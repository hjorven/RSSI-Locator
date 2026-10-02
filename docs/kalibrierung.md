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

Wie groß `D` sein sollte und warum dieser Wert wichtiger ist als alle
anderen, steht in [Nodeabstand D](#nodeabstand-d-der-wichtigste-wert-ueberhaupt).

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

## Nodeabstand D: der wichtigste Wert überhaupt

`D` ist der Abstand zwischen den beiden Antennen. Er entscheidet über die
Genauigkeit stärker als alle anderen Parameter zusammen, und zwar so:

| D | Gerät 1 m entfernt | 2 m | 4 m | Bewertung |
|---|------------------:|----:|----:|-----------|
| 0,45 m | 0,58 m | 1,29 m | 3,74 m | unbrauchbar |
| 1,5 m | 0,37 m | 0,70 m | 2,48 m | gut für 1 bis 2 m |
| 2,0 m | 0,85 m | 0,31 m | 2,18 m | gut für 1 bis 3 m |
| 3,0 m | 1,84 m | 0,73 m | 1,40 m | gut für 2 bis 5 m |
| 4,0 m | 2,83 m | 1,70 m | 0,62 m | gut ab 4 m |

Mittlerer Positionsfehler, 3 dBm Messrauschen, 60 Messungen je Gerät.

Der Grund ist geometrisch: aus zwei Kreisen um A und B mit Radius r1 und r2
berechnet sich die Position. Je näher A und B beieinander liegen, desto
schlechter sind diese beiden Kreise voneinander unterscheidbar. Bei 45 cm
schmolzen die Kreise zu fast gleichen Radien, und die Position konnte in
beliebiger Richtung verrutschen.

Faustregel: **D etwa halb so groß wie der größte Abstand, den du messen
willst.** Willst du Geräte bis 4 m orten, sind 2 m Nodeabstand richtig. Willst
du die ganze Wohnung abdecken, gehören die Nodes an gegenüberliegende Ecken.

Die beiden Nodes gehören auf dieselbe Höhe (gleiche Tischkante) und mit den
Antennen in dieselbe Richtung, sonst kommt ein systematischer Versatz dazu.

## Einstellungen bleiben erhalten

Der Server speichert die Einstellungen in `server/settings.json` und lädt sie
beim Start. Kalibrierte Werte überstehen damit Neustart und Deployment.
Ausschließlich die Einstellungen werden gespeichert, die Messdaten bleiben im
Arbeitsspeicher.

Die Datei steht in `.gitignore` und ist im `rsync` von `deploy/deploy.sh`
ausgenommen. Das ist beides nötig: `--delete` würde sie beim nächsten
Deployment sonst überschreiben, weil sie nicht im Repository liegt. Wer die
Datei versehentlich doch löscht, setzt die Werte einmal neu und sie werden
beim nächsten Speichern wieder angelegt.

Nach einem Neustart prüfen, ob die Datei da ist und gültig ist:

```bash
ssh pi@192.168.1.20 'cat ~/rssi-locator/server/settings.json'
ssh pi@192.168.1.20 'systemctl status rssi-locator --no-pager' | grep -i settings
```

Ist die Datei weg oder unlesbar, startet der Server mit den Vorgaben und
schreibt erst beim nächsten Speichern neu. Eine kaputte Datei wird bewusst
nicht überschrieben, damit die alten Werte nicht unbemerkt verloren gehen.

`node_offline_after` steht auf 12 s statt der ursprünglichen 5 s: ein Pico 2 W
braucht bis zu 5 s für einen BLE-Scan und nochmal bis zu 4 s für einen
WLAN-Vollscan. Mit den Vorgabe-Werten gilt der Node während des WLAN-Scans im
Browser kurzzeitig als "offline".

## Grenzen des Modells

Die angezeigte Unsicherheitsellipse kommt aus der **RSSI-Streuung** der letzten
Messungen (Median-Absolutabweichung, 95-%-Intervall). Sie erfasst nicht:

- Reflexionen und Mehrwege (diese machen RSSI eher *zu stark*),
- Abschirmung durch Möbel oder Wände (macht RSSI zu schwach),
- systematische Fehler durch unterschiedliche Antennen der beiden Nodes.

Deshalb ist die Ellipse eine Untergrenze der Unsicherheit, besonders bei
schwachen Signalen. Bei `ry` deutlich größer als `rx` liegt das Gerät nahe der
Verbindungslinie der Nodes — dort ist die y-Position am schlechtesten bestimmt.
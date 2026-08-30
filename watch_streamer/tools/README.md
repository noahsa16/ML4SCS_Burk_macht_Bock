# Die Wesen im Seitenrand zeichnen

Eine Fokus-Sitzung zeichnet ein kleines Tintenwesen in den Rand ihrer Seite,
Strich für Strich, während Schreibzeit zusammenkommt. Dieser Ordner enthält die
zwei Werkzeuge dafür.

## Warum nicht einfach Clipart

Die Mechanik braucht eine **geordnete Liste gestrichelter Pfade** — Linien, die
nacheinander erscheinen. Clipart und automatisch nachgezeichnete Scans liefern
dagegen **gefüllte Umrisse**. Zeichnet man eine gefüllte Silhouette fortschreitend,
wandert eine Kontur über den Bildschirm und ergibt optisch nichts.

Deshalb muss jeder Strich ein eigener Pfad sein, gezogen in der Reihenfolge, in
der ein Mensch das Tier zeichnen würde.

## Der Weg

### 1. Vorlage wählen

Gemeinfreie Drolerien, ohne Lizenzfragen für eine spätere Publikation:

- [Digital Bodleian](https://digital.bodleian.ox.ac.uk/collections/western-medieval-manuscripts/)
  — über eine Million frei ladbare Bilder, darunter 2500 mittelalterliche
  Handschriften.
- [Getty Open Content](https://www.getty.edu/art/collection/) — Bilder mit dem
  Vermerk *„available for download, without charge, under the Getty's Open
  Content Program"*.
- [PICRYL](https://picryl.com/topics/marginalia) — Suchmaschine ausschließlich für
  gemeinfreie Medien.

Besonders ergiebig sind der **Luttrell Psalter** (British Library, Add MS 42130,
über 600 Randzeichnungen) und der **Gorleston Psalter** (Add MS 49622). Die
British Library hat ihre Handschriften-Digitalisate vor 1800 gemeinfrei gestellt.

### 2. Nachzeichnen

In [Linearity Curve](https://www.linearity.io/curve/) (kostenlos für iPad, iPhone
und Mac). Vorlage als Hintergrundebene, darüber mit dem Stift nachziehen.

Drei Regeln, sonst kommt der Konverter nicht durch:

- **Ein Strich = ein Pfad.** Nicht mehrere Striche zu einer Form vereinen.
- **In Zeichenreihenfolge.** Die Ebenenreihenfolge ist die Zeichenreihenfolge.
  Wer die Ebenen später umsortiert, benennt sie stattdessen `1 rücken`,
  `2 bauch`, … — eine führende Zahl schlägt die Dateireihenfolge, aber nur wenn
  **jeder** Pfad eine hat.
- **Keine Formwerkzeuge.** Kreise, Rechtecke und Linien haben keine
  Strichreihenfolge; der Konverter weist sie mit einer Meldung ab. Alles mit dem
  Stift zeichnen, oder vor dem Export in Pfade umwandeln.

Auto-Trace ist zum *Anschauen* nützlich, aber sein Ergebnis ist ein gefüllter
Umriss — als Vorlage zum Drüberzeichnen gut, als Endergebnis nicht.

Zur Detailtiefe: 30 bis 50 Striche sind völlig in Ordnung. Mehr Striche heißt
nur, dass das Wesen feiner wächst. Die frühere Grenze von 6 bis 12 war eine
willkürliche Setzung, keine technische.

### 3. Exportieren

Als **SVG**, ein Wesen pro Datei, benannt in Reihenfolge des Bestiariums:

```
0-trompeten-hase.svg
1-panzerschnecke.svg
…
```

Der Dateiname wird zum angezeigten Namen. Die führende Zahl bestimmt die
Reihenfolge und verschwindet aus dem Namen.

### 4. Umwandeln

```bash
cd watch_streamer
python3 tools/svg_to_marginalia.py drawings/*.svg \
    --out WatchStreamer/Scrybe/Components/Marginalia.swift
```

Das Werkzeug skaliert jedes Wesen formattreu in ein 100×100-Feld mit 4 Einheiten
Rand, rechnet jede Kurve in eine kubische um und schreibt fertigen Swift-Code.
Es braucht keine Bibliotheken.

### 5. Ansehen

```bash
swiftc -O -o /tmp/render tools/render_marginalia.swift \
    WatchStreamer/Scrybe/Components/Marginalia.swift && /tmp/render
```

Schreibt `/tmp/marginalia.png` — alle Wesen als beschriftetes Raster mit
Grundlinie. Eine einzelne Art groß: `/tmp/render 5`.

**Immer hinsehen, bevor committet wird.** Der Renderer kippt die y-Achse, weil
SwiftUI sie nach unten zählt und AppKit nach oben; ohne diese Kippung prüfte man
ein gespiegeltes Bild. Ebenso zeigt er die Strichstärke abnehmend, wie eine Feder
Tinte verliert — so sieht man, ob die Reihenfolge stimmt.

### 6. Tests

```bash
xcodebuild test -project WatchStreamer.xcodeproj -scheme WatchStreamer \
    -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
    -only-testing:ScrybeTests/MarginaliaTests
```

Prüft Strichzahlen, dass jeder Strich im Feld bleibt, und dass jede Art benannt
ist. Der Bereich 6…12 in `MarginaliaTests` ist anzuheben, sobald die
nachgezeichneten Wesen mehr Striche haben.

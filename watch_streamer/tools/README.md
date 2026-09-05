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

### 2a. Automatisch nachzeichnen (ohne Zeichnen)

`trace_to_strokes.py` reduziert die Tinte eines Scans auf ihre Mittellinien und
schreibt daraus ein SVG mit einem Pfad je Federstrich. Damit braucht es weder
Zeichenkenntnis noch Zeit. **Jeder Pfad trägt zusätzlich die gemessene
Strichstärke** (`stroke-width`, Median der Tintenbreite unter der Mittellinie):
so bleibt eine Kontur im Ergebnis schwer und die Fellschraffur daneben fein,
statt dass beides zu einer Einheitslinie wird.

Die Vorlagen der aktuellen Wesen liegen in `drawings/sources/` (saubere
Strichzeichnungen, 1254×1254). Sie wurden so nachgezeichnet:

```bash
.venv/bin/python tools/trace_to_strokes.py drawings/sources/0-trompeten-hase.jpeg \
    --out drawings/0-trompeten-hase.svg \
    --max-side 1254 --min-blob 120 --min-stroke 12 --max-strokes 380 --tolerance 1.2
```

`--min-stroke 12` behält die kurzen Schraffurstriche, die das Fell ausmachen;
`--max-strokes 380` liegt über jedem der acht Wesen, sodass nichts weggelassen
wird; `--tolerance 1.2` hält die Kurven glatt. Für Bücherwurm und Federfisch
fehlt die Vorlage — ihre SVGs stammen aus einem früheren Lauf ohne
Strichstärken und werden mit einer Einheitsbreite gezeichnet, bis die Vorlage
wieder auftaucht.

Für einen Handschriften-Scan (Feder auf Pergament, fleckig) sind andere Werte
der Ausgangspunkt:

```bash
.venv/bin/python tools/trace_to_strokes.py ausschnitt.png --out 0-hase.svg \
    --window 41 --despeckle 1 --bridge 4 --min-blob 400 --min-stroke 30
```

Diese Werte stammen aus einem echten Beispiel (14. Jh., 480×780 Ausschnitt).

Was die Schalter tun, und warum die Reihenfolge zählt:

- `--window` schaltet auf eine **lokale** Schwelle (Sauvola). Eine globale
  Schwelle erfasst auf fleckigem Pergament nur die dunkelsten Teile jeder Linie
  und zerhackt sie.
- `--despeckle` entfernt alles, was **schmaler als ein Federstrich** ist. Genau
  das ist die Pergamentkörnung, und die Breite ist das einzige Merkmal, das sie
  von der Zeichnung trennt.
- `--bridge` schließt danach die Lücken, die eine springende Feder lässt.

**Öffnen muss vor Schließen kommen.** Umgekehrt schweißt man die Körnung an die
Zeichnung, und danach kann kein Filter sie mehr unterscheiden. Das war der Fehler,
an dem der erste Versuch an einer echten Handschrift scheiterte.

Vorher eng auf das Tier zuschneiden — Text und Zeilenlineatur werden sonst
mitgezeichnet.

**Ergebnis prüfen, nicht annehmen.** Eine Federzeichnung kommt mit Lücken heraus;
klein im Seitenrand liest sich das als Federtextur und ist stimmig, aber
ansehen muss man es.

### 2b. Selbst nachzeichnen

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

Zur Detailtiefe: 100 bis 350 Striche sind der aktuelle Stand. Mehr Striche
heißt nur, dass das Wesen feiner wächst; bei 30 Minuten je Wesen kommt bei 150
Strichen alle 12 s einer dazu, bei 350 alle 5 s.

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
Die Strichstärke wird mitskaliert; ein SVG ohne `stroke-width` bekommt eine
Einheitsbreite, die mit der Strichzahl feiner wird. Es braucht keine
Bibliotheken.

### 5. Ansehen

```bash
swiftc -O -o /tmp/render tools/render_marginalia.swift \
    WatchStreamer/Scrybe/Components/Marginalia.swift \
    WatchStreamer/Scrybe/Components/CreaturePen.swift && /tmp/render
```

Schreibt `/tmp/marginalia.png` — alle Wesen als beschriftetes Raster mit
Grundlinie. Eine einzelne Art groß: `/tmp/render 5`. Das Wachsen einer Art in
sechs Stufen: `/tmp/render grow 0` → `/tmp/marginalia_growth.png`.
`CreaturePen` ist derselbe Stift, den die App benutzt (Mindeststärke, Tonwert
für Haarlinien), damit das geprüfte Bild dem gezeichneten entspricht.

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

Prüft Strichzahlen (6…400), dass jeder Strich im Feld bleibt, eine plausible
Strichstärke trägt, und dass jede Art benannt ist.

# Scrybe: Fokus-Sitzung und Ernte-Geste (Design)

**Datum:** 2026-08-29
**Status:** Entwurf zur Review
**Vorarbeit:** `docs/specs/2026-08-28-on-device-deployment-design.md`,
`WatchStreamer Watch App/PassiveTracker.swift`, `Shared/PassiveTrackerEngine.swift`,
`models/runs/pod_raw50/` (deployter Checkpoint), Paritätsprüfung 24/24 auf Gerät

## 1. Ziel

Für ein **zweiminütiges Produktvideo** bekommt Scrybe zwei neue Oberflächen. Sie
sind keine Video-Requisiten, sondern echte Funktionen; das Video ist nur der
Anlass, sie in Filmqualität zu bauen.

1. **Fokus-Sitzung** — eine bewusst gestartete Schreib-Sitzung. Die Uhr
   klassifiziert live, auf dem iPhone wächst eine Tintenlinie mit. Setzt der
   Stift ab, reißt die Linie.
2. **Ernte-Geste** — beim Ziehen auf „Heute" fließen die seit dem letzten
   Abgleich neu erkannten Minuten sichtbar in den Tages-Ring.

Der Ganztag-Tracker bleibt unverändert. Die Fokus-Sitzung ist ein Opt-in-Modus
daneben, kein Ersatz.

### Nicht im Umfang

Live-Entscheidungen persistieren · Täusch-Spiel als Bühnenmodus · Federkiel-Streak ·
Tagesbrief mit Siegel · „Tinte trocknet" als eigenes Feature auf dem Tageszeitstrahl.

Begründung: bei 120 Sekunden Film bleiben nach Einstieg, Erklärung und Abspann
etwa 45–60 Sekunden für Produktmomente. Vier Features darin bekämen je ~12
Sekunden. Zwei Dinge in Filmqualität tragen den Film, vier durchschnittliche
nicht.

## 2. Leitprinzip

**Der Live-Pfad ist ein Sucher, nicht das Protokoll.**

Während einer Fokus-Sitzung rechnet die Uhr live und schickt Entscheidungen ans
Telefon, damit die Linie wächst. Diese Entscheidungen werden **nirgends
gespeichert**. Der Passiv-Pfad bleibt alleinige Quelle für Ring, Tag, Historie
und Archiv.

Grund: `PassiveDecision` ist über `startMs` idempotent, aber Live- und
Recorder-Fenster liegen nie auf denselben Grenzen. Zwei Produzenten für denselben
Zeitraum würden den Tag **doppelt zählen**, und die Idempotenz kann das nicht
abfangen. Die Alternative — „live gewinnt" mit Bereichsmarkierungen und
Cursor-Manipulation am Recorder — bräuchte genau die Sorte Zustand, in der sich
Fehler verstecken.

Zwei Folgen:

- **Der Ring bewegt sich während der Sitzung nicht.** Die Gutschrift kommt später
  über den Recorder. Das ist die Ernte-Einstellung: erst der Beweis, dann die
  Buchung.
- **Der Live-Kanal braucht keine Zustellgarantie.** Geht ein Fenster verloren,
  fehlt ein Stück Linie; der Datensatz ist unberührt. Durabilität, Wiederholung
  und Quittierung entfallen ersatzlos.

## 3. Uhr — `FocusSession`

Neuer Typ im Watch-Target (`WatchStreamer Watch App/FocusSession.swift`),
`@MainActor`, ohne Persistenz.

**Quelle.** `CMMotionManager.startDeviceMotionUpdates` mit
`deviceMotionUpdateInterval = 1/50` auf einer Background-`OperationQueue`, am
Leben gehalten von einer `HKWorkoutSession` nach dem Muster von
`MotionManager.beginWorkoutSession()`.

**Kanal-Rekonstruktion.** Pro Sample:

```
PassiveSample(x: userAcceleration.x + gravity.x,
              y: userAcceleration.y + gravity.y,
              z: userAcceleration.z + gravity.z)
```

Das ist `imu[:, :3] + imu[:, 3:]` aus `src/training/deep/data.py:110`, also exakt
der Kanalsatz `raw_accel`, auf dem das deployte Modell trainiert wurde. Deshalb
braucht es **kein neues Modell, keinen neuen Export und keine zweite
Paritätsprüfung**.

**Fenster und Klassifikation.** Derselbe
`PassiveWindowBuilder(seqLen: 250, strideSamples: 125, nominalHz: 50)` und
dasselbe `WatchScrybeModel` wie im Passiv-Pfad. Ergebnis: alle 2,5 s eine
`PassiveDecision`.

**Zeitachse.** Die monotone Sensoruhr wird beim ersten Sample einmal an die
Wanduhr geankert (Muster `anchorUptime` / `anchorWallMs` in `MotionManager`),
damit ein NTP-Sprung die Fenstergrenzen nicht verschiebt.

**Ausschluss.** Fokus-Sitzung und Studien-Aufnahme schließen sich gegenseitig
aus, in beide Richtungen. Sonst gäbe es zwei Eigentümer einer Workout-Session —
`MotionManager` beendet seine bewusst nie.

## 4. Transport

Zwei neue Fälle in `WatchCommandName`. Das Enum ist `CaseIterable` und
`WatchCommandRoutingTests` iteriert über alle Fälle, die Einordnung wird also
erzwungen:

| Kommando | `transport` | `bypassesRecordingDispatcher` | `mayFallBackToUserInfo` |
|---|---|---|---|
| `focus_start` | `.idempotentOperation` | ja | **nein** |
| `focus_stop` | `.idempotentOperation` | ja | **nein** |

Kein `transferUserInfo`-Rückfall: ein Sitzungsstart, der Minuten später
eintrifft, ist falsch, nicht spät.

**Rückkanal.** Jede fertige Entscheidung geht sofort per `sendMessage` mit neuem
Umschlag `focus_decision` (neuer `WatchPayloadKey`). Kein Reply, keine
Wiederholung. Ist das Telefon nicht erreichbar, wird verworfen — zulässig wegen
§2.

## 5. Telefon — `FocusSessionStore`

`WatchStreamer/Stores/FocusSessionStore.swift`, `@MainActor`, `ObservableObject`,
**rein im Speicher**.

```
phase:      idle | starting | running(startedAt, target) | finished(summary)
decisions:  [PassiveDecision]     // nur RAM
writtenSeconds / strokes          // abgeleitet
```

Berührt weder `PassiveDecisionStore` noch `FocusStore` noch `FocusArchive`.

Start und Stopp gehen über `ServerCommandListener.forwardToWatch` **mit
Zeitgrenze** (8 s, Muster `WatchDecisionSync.requestSync`). Antwortet die Uhr
nicht, bleibt die Sitzung `idle` mit sichtbarem Grund, statt in `starting`
hängenzubleiben.

## 6. Telefon — die Seite

`WatchStreamer/Scrybe/Components/WritingPageView.swift`, gezeichnet in einem
`Canvas` innerhalb einer `TimelineView(.animation)`.

### Aufbau

Eine **Seite**, kein Balken: die Linie läuft in Zeilen links nach rechts mit
Umbruch, Zeit wird Schreibrichtung.

| Größe | Wert |
|---|---|
| Zeilenhöhe | 32 pt |
| Linker Rand | 40 pt |
| Rechter Rand | 24 pt |
| Zeitskala | eine Zeile ≈ 2 Minuten reine Schreibzeit (Lücken zählen nach der Stauchungsregel unten) |
| Blindlinien | 0,5 pt, Papierton 6 % abgedunkelt |

Die Blindlinien sind funktional, nicht dekorativ: ohne sie liest sich eine Lücke
als Nichts statt als leere Zeile. Keine Karolinien, kein roter Heftrand.

### Der Strich

Basisbreite 2,5 pt, Variation ±35 % über Value-Noise mit Periode 80–120 pt, dazu
vertikales Jitter ±0,75 pt und unregelmäßige Welligkeit (Amplitude ~1 pt, Periode
40–80 pt). Zwei Lagen: breiter Außenstrich bei 70 % Deckkraft, schmaler Kern bei
100 % — das ergibt den dunklen Kern echter Tinte.

Ansatz: Breite wächst über 6–10 pt von null auf voll, mit minimalem Abwärtsbogen.
Absatz: Verjüngung über 10–16 pt mit leichtem Aufwärtszug, in etwa 30 % der Fälle
ein einzelner Mikropunkt (0,5–1 pt) dahinter. Nie hart gekappt.

### Der nasse Kopf

Die Entscheidung hinkt den Daten um ein Fenster (~5 s) hinterher. Das wird
gezeigt, nicht versteckt:

- Die Federspitze (kleiner Punkt) läuft in Echtzeit voraus.
- Dahinter eine 25-%-Spur über die Latenzstrecke — die Feder schreibt vor.
- Trifft die Entscheidung ein, füllt sich die Spur mit Tinte.
- Der zuletzt gefüllte Abschnitt ist 10 % dunkler und 110 % breit und
  „trocknet" über 4–6 s auf Normalzustand.

### Lücken

Bis 15 s linear, darüber logarithmisch gestaucht — sonst frisst eine Pause die
Seite. Ab 60 s Zeilenumbruch mit Einzug: eine lange Pause wird ein neuer Absatz.
Unter Lücken über 60 s eine Serifenziffer (`1:24`) in 10 pt bei 40 % Deckkraft.

### Signatur

Jede beendete Sitzung erhält unten rechts eine kleine Serifen-Kursive:
`29. Aug · 14:31–15:06`. Macht die Seite zum Dokument.

## 7. Ernte beim Ziehen

`FocusStore` bekommt eine persistierte Zahl `lastHarvestedSeconds` — wie viel
Schreibzeit der Nutzer bereits *gesehen* hat (UserDefaults, ein `Double`).

Bei einem erfolgreichen Pull mit neuen Daten:

```
delta = todayWritingSeconds - lastHarvestedSeconds
```

Ist `delta > 0`, läuft der Ring vom alten auf den neuen Wert und die vorhandene
Kapsel (`InkRefreshIndicator`) trägt statt „Zuletzt geschrieben …" den Text
**„+14 Minuten"**. Danach wird `lastHarvestedSeconds` gesetzt.

Zwei Kanten: ein zweiter Pull direkt danach zeigt **kein** Delta, und der
allererste Start beansprucht nicht die bisherige Historie als Ernte (Initialisierung
auf den aktuellen Stand).

## 8. Visuelle Gestaltung

Diese Regeln gelten für beide neuen Oberflächen und wurden 2026-08-29 bereits auf
den Bestand angewandt; diese Änderungen sind noch nicht committet.

### Verbindlich

- **Abstände** nur aus dem Raster 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48.
- **Deckkraft** nie an der Aufrufstelle erfinden. Getönte Flächen über
  `ScrybeTheme.wash(_:)`; Spuren über `theme.track`; Haarlinien über
  `theme.hairline`.
- **Maximal vier Schriftgrößen** pro Bildschirm.
- **Kurven nach Zweck**, nicht eine für alles: Ankommen bremst ab, Verlassen
  beschleunigt, gleichförmiger Fortschritt ist linear.
- **Kein `minimumScaleFactor`.** Passt Text nicht, wird der Text gekürzt oder das
  Layout korrigiert.

### Bewegung

| Vorgang | Dauer | Kurve |
|---|---|---|
| Linie wächst | fortlaufend | **linear** |
| Riss beim Absetzen | 250–300 ms | ease-out, kein Overshoot |
| Kopf trocknet | 4–6 s | nahezu linear |
| Ernte gesamt | 1,4 s | `timingCurve(0.2, 0.9, 0.3, 1.0)` |
| Ernte-Tropfen | gestaffelt 40–70 ms | ease-out |

Das lineare Wachsen ist die wichtigste Zeile: jedes Easing macht aus der Linie
einen Ladebalken. Ausdrücklich verboten sind `.bouncy` und jede Feder mit
`dampingFraction < 0.85` — Tinte federt nicht zurück.

**Reduce Motion:** Ernte als Crossfade plus Zahl; die Linie wächst weiter, denn
sie ist Information, keine Dekoration; der nasse Kopf entfällt, die Tinte
erscheint stufenweise.

### Typografie

New York (System-Serif) für Zahlen und Überschriften, SF Pro für UI-Kleinteile.
Die Ringzahl wird von `.semibold` auf **`.regular`** geändert: Serifen brauchen
keine Fettung, die Größe trägt die Hierarchie. Beim Live-Zählen tabellarische
Ziffern, in Ruhe proportional.

### Haptik

Ein einzelnes weiches Tap beim Abriss der Linie, zwei bis drei leichte Ticks
synchron zu den ankommenden Ernte-Tropfen. Sonst nichts.

### Dark Mode

Materialwechsel statt Invertierung: **weiße Tusche auf schwarzem
Baumwollpapier**. Geometrie, Rauschen und Bewegung bleiben identisch, nur die
zwei semantischen Token wechseln. `ScrybeTheme.dark` erfüllt das bereits
(`paperTop 0x221E18` warmschwarz, `ink 0xF2ECE0` knochenweiß); die Seite erbt
die Token, statt eigene Farben zu setzen. Der nasse Kopf wird dort **heller** und
gesättigter statt dunkler.

### Ausdrücklich vermieden

Vollausbau-Skeuomorphismus (Pergamenttextur, Federkiel-Icons, Wachssiegel,
Handschrift-Font) und Tinten-Simulation (Kleckse, Spritzer, Aquarell-Bleeding).
Beides ertränkt auf 6,1 Zoll die Lücken, die die eigentliche Information der
Seite sind. Die Metapher lebt in Ton, Strich und Typografie, nicht in Requisiten.

## 9. Fehler und Sicherheiten

| Fall | Verhalten |
|---|---|
| HealthKit nicht autorisiert | `focus_start` antwortet `ok: false` mit Grund; keine Sitzung |
| Uhr antwortet nicht | 8-s-Zeitgrenze → `idle` mit sichtbarem Grund |
| Aufnahme läuft bereits | Start abgelehnt (beidseitiger Ausschluss, §3) |
| Sitzung läuft zu lange | harte Obergrenze 60 min, automatischer Stopp |
| App beendet | Workout endet, Motion-Updates enden, Zustand ist ohnehin flüchtig |

Der Akku ist der Risikoposten: Deckel und garantiertes Aufräumen sind Pflicht.

## 10. Tests

- `FocusSession` erzeugt aus einer Fake-Motion-Quelle genau eine Entscheidung je
  125 Samples, und die Kanäle sind nachweislich `userAcceleration + gravity`
  (Prüfung gegen einen bekannten Vektor).
- Gegenseitiger Ausschluss Aufnahme ↔ Fokus, in beide Richtungen.
- `FocusSessionStore` schreibt nichts in `PassiveDecisionStore` — der Test, der
  §2 festnagelt.
- Ernte: kein Doppelzählen über zwei aufeinanderfolgende Pulls, kein Delta beim
  Erststart.
- `WatchCommandRoutingTests` deckt die zwei neuen Kommandos ab.
- Geometrie der Seite: Zeilenumbruch bei 60-s-Lücke, logarithmische Stauchung
  über 15 s — als reine Funktion getestet, ohne UI-Host.

## 11. Dateien

**Neu:** `WatchStreamer Watch App/FocusSession.swift` ·
`WatchStreamer/Stores/FocusSessionStore.swift` ·
`WatchStreamer/Scrybe/FocusSessionView.swift` ·
`WatchStreamer/Scrybe/Components/WritingPageView.swift`

**Geändert:** `Shared/WatchCommand.swift` (zwei Enum-Fälle, ein Payload-Key) ·
`WatchStreamer Watch App/MotionManager.swift` (Ausschluss) ·
`WatchStreamer/Stores/FocusStore.swift` (Ernte-Zähler) ·
`WatchStreamer/Scrybe/Components/InkRefreshControl.swift` (Kapseltext) ·
`WatchStreamer/Scrybe/Components/InkRing.swift` (Ringzahl-Gewicht)

## 12. Offene Punkte

Die Zahlenwerte in §6 (Strichbreite, Rauschperioden, Zeilenhöhe, Zeitskala) sind
belastbare Startwerte, keine Messergebnisse. Sie werden am Gerät nachgezogen; die
Spec wird dabei nicht erneut zur Review gestellt, solange Aufbau und Verhalten
gleich bleiben.

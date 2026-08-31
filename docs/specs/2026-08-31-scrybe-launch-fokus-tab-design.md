# Scrybe: Fokus als Bereich, Bühne statt Formular (Design)

**Datum:** 2026-08-31
**Status:** Entwurf zur Review
**Vorarbeit:** `docs/plans/2026-08-31-scrybe-launch-ui-and-focus-plan.md`
(Befundlage aus Screenshots und Code), `docs/specs/2026-08-29-scrybe-fokus-sitzung-design.md`
(die Sitzung selbst), Design-Zweitmeinung Fable 2026-08-31

## 1. Ziel

Die Fokus-Sitzung ist die Marquee-Handlung der App, wird aber wie ein
Untermenüpunkt behandelt: eine Listenzeile mit `chevron.right` zwischen
Tagesstatistiken (`Scrybe/TodayView.swift:130`), geöffnet als
`fullScreenCover` (`:74`), und dahinter zuerst ein Formular mit der Frage
„Wie lange willst du schreiben?" (`Scrybe/FocusSessionView.swift:102-125`).
Die kunstvolle Seite sieht man erst nach dem Start.

Dieser Pass macht drei Dinge:

1. **Fokus wird ein eigener Tab** und öffnet als fertige, startbereite Seite
   statt als Formular.
2. **Das Ziel bleibt offen formulierbar**, ohne dass eine Frage den Einstieg
   besetzt.
3. **Die Designsprache erreicht die Ränder** — Tab-Bar, Picker, Splash,
   Empty-States.

Dazu kommt der Teil des Statusvertrags, den der neue Tab zwingend braucht: der
Start muss zwischen gestartet, abgelehnt, Timeout und nicht erreichbar
unterscheiden.

### Nicht im Umfang

Der übrige Statusvertrag aus Phase A (Header, Profil und Offline-Banner auf eine
gemeinsame `WatchConnectionState`-Quelle) · Trends-Tagesauswahl und
Zeitraumnavigation · Verlauf-Aggregation auf Tageszusammenfassungen · das
adaptive Zielmaß des Heute-Rings · die Profilhierarchie.

Eine Ausnahme mit Begründung: ein **schlichter Einstieg von Trends in den
Verlauf** ist enthalten (§3). Ohne ihn wäre Verlauf nach der Tab-Umstellung
nicht mehr erreichbar — das wäre kein aufgeschobener Ausbau, sondern ein
Rückschritt.

Begründung: Diese Punkte stehen im Plandokument als Phase A, C und D und sind
jeder für sich abnehmbar. Zusammen mit dem Fokus-Tab ergäben sie einen Pass, den
niemand mehr am Stück prüfen kann. Der Fokus-Tab trägt nur den Ausschnitt des
Statusvertrags, ohne den seine eigenen Zustände nicht darstellbar wären.

## 2. Leitprinzip

**Der Bereit-Zustand zeigt, was gleich wachsen soll — nicht die Frage, wie
lange.**

Scrybe besitzt die Fokus-Mechanik bereits vollständig:
`BestiaryStore.addWritingSeconds` lässt genau eine Kreatur mit *gutgeschriebener
Schreibzeit* wachsen, 30 Minuten pro Tier
(`Shared/Bestiary.swift:97`), strichweise und sitzungsübergreifend. Was fehlt,
ist keine Mechanik, sondern eine Bühne: in der laufenden Sitzung ist die Kreatur
`creatureBoxSize = lineHeight` (`Scrybe/Components/WritingPageView.swift:162`),
also 32 Punkte — als Belohnung faktisch unsichtbar.

Die Anleihe bei Fokus-Timern wie Forest ist damit ein Prinzip, keine Optik:
*ein* lebendes Ding im Zentrum, das nur durch echte Arbeit wächst. Scrybes
Übersetzung ist nicht eine Pflanze, die wächst, sondern **eine Zeichnung, die
vollendet wird**.

**Ausdrücklich nicht übernommen wird das Sterben.** Ein abgebrochener Fokus
darf die Kreatur nicht beschädigen. Zwei Gründe: der Store hält Pausen bereits
still, statt zu reduzieren (`Stores/FocusSessionStore.swift`), und eine Strafe
auf Basis eines fehlbaren Klassifikators würde Menschen für Modellfehler
bestrafen — die Schreiberkennung hat dokumentierte False Negatives bei
Soft-Writern.

## 3. Navigation

Die Wurzel ist trotz ihres Namens eine Stock-`TabView`
(`Scrybe/RootPagerView.swift:25-39`). Die Tabs werden:

| Tab | Aufgabe |
|---|---|
| Heute | Wie stehe ich heute? |
| Trends | Wie entwickelt sich mein Schreiben? |
| Fokus | Jetzt bewusst schreiben |
| Profil | Ziel, Gerät, Datenschutz |

Verlauf verlässt die Leiste und wird Drilldown aus Trends (Plandokument §10,
Must-have). Der Fokus-Tab ist ein `NavigationStack` mit der Seite als Wurzel.

**Verlauf darf dabei nicht stranden.** Der im Plandokument vorgesehene Weg
hinein ist die Tagesauswahl in der Trends-Grafik — die steht hier unter „Nicht
im Umfang". Dieser Pass ergänzt darum das Minimum: eine Zeile „Verlauf öffnen"
am Fuß von Trends, die `HistoryView` pusht. Die reichhaltige Tagesauswahl
ersetzt sie später; ohne sie wäre ein bestehender Bereich nach diesem Pass nicht
mehr erreichbar.

**Die Karte „Fokus-Sitzung" fällt aus Heute** (`TodayView.swift:116-147`, samt
`fullScreenCover` in `:74-78`). An ihre Stelle tritt eine schmale Zeile
„Fokus läuft · 12:34 — öffnen", die **nur** bei laufender Sitzung erscheint und
in den Tab wechselt.

### Ruhe im Lauf-Zustand

`ScrybeHeader` steht als Geschwister der `TabView` in einem `VStack`
(`RootPagerView.swift:23-24`), ist also global. `.toolbar(.hidden, for:
.tabBar)` entfernt darum nur die untere Leiste. Der Header braucht eine eigene
Sichtbarkeitsbedingung in `RootPagerView`, gespeist aus der Fokus-Phase.

Das ist der einzige Punkt, an dem dieser Pass die Wurzel anfasst. Warum
trotzdem: ohne ihn bleibt im Lauf-Zustand eine Kopfzeile über einer Seite
stehen, die für sich allein wirken soll.

## 4. Die Zustände des Fokus-Tabs

**Bereit.** Eine leere linierte Seite; `WritingPageView` rendert mit leeren
Segmenten bereits die Regel-Linie. Darauf die aktuelle Kreatur bei 120–160
Punkten — `CreatureCanvas` aus `Scrybe/BestiaryView.swift` skaliert beliebig.
Darunter, in Serifenkursive, ihr Name und Zustand („Trompetenhase · im
Entstehen") und eine Zeile „Noch etwa 12 Minuten, bis er fertig gezeichnet ist",
abgeleitet aus `Bestiary.secondsPerCreature − writingSeconds` des laufenden
Tiers. Darunter der Dauersatz (§5) und eine aktive Startaktion.

**Verbindung wird geprüft.** Startaktion deaktiviert, Fortschrittsanzeige,
„Watch wird erreicht …", sichtbare Abbruchmöglichkeit.

**Läuft.** Header und Tab-Bar ausgeblendet, die Seite füllt sich. Die Kreatur
wandert per Transition aus der Mitte in die Marge — wie eine illuminierte
Initiale, die dem Text vorausgeht. Weil die Tab-Bar fehlt, trägt die Seite
selbst die einzige Ausstiegsaktion: „Beenden" am unteren Rand, im Ruhezustand
zurückgenommen, aber immer sichtbar und ohne Geste erreichbar.

**Abgelehnt / Timeout / nicht erreichbar.** Drei unterscheidbare Ausgänge mit
je eigener nächster Aktion (§7).

**Fertig.** Schreibzeit, Zielerreichung, die in dieser Sitzung gezeichneten
Striche, Weg ins Tagesdetail.

## 5. Die Dauer ist ein Wort, kein Feld

`targetMinutes` (`FocusSessionView.swift:34`) wechselt von `@State` auf
`@AppStorage`. Die Seite öffnet damit immer mit der zuletzt gewählten Dauer und
stellt nie eine Frage.

Unter der Kreatur steht ein Satz in der Sprache der App:

> Eine Sitzung von **25 Minuten**

Die Zahl ist getönt (derselbe Accent-Wash wie die heutigen Chips) und als
Schaltfläche ausgezeichnet. Ein Tap öffnet ein kompaktes Sheet
(`presentationDetents([.height(…)])`) mit:

- den drei Presets 15 / 25 / 45,
- einem validierten Feld für **5 bis 180 Minuten**, ganze Zahlen,
- der Option **„einfach schreiben"** ohne Ziel.

Das Formular verschwindet also nicht, es wird auf Abruf gestellt.

**Warum „ohne Ziel" ehrlich ist:** Das Ziel ist im Store bereits rein
darstellend — es liefert die Unterzeile „von 25 min". Beendet wird eine Sitzung
durch die Nutzerin oder den Hard-Cap, nie durch den Ablauf des Timers. Die
Option macht diese Semantik sichtbar, statt sie zu verstecken.

**Die Vorschau bleibt eine Vorschau.** Wird neben der Dauer eine erwartete
Strichzahl gezeigt, ist sie ausdrücklich als Erwartung formuliert. Die echte
Zeichnung wächst nach gutgeschriebener Schreibzeit; liefert die Uhr keine
Schreibfenster, steht der Fortschritt still. Ein Timer, der ein Tier von selbst
fertigzeichnet, wäre eine Lüge über die Messung.

## 6. Das Bestiarium zieht um

Heute hängt die Sammlung am Fuß von Verlauf (`Scrybe/HistoryView.swift:31`).
Da Verlauf die Tab-Bar verlässt, läge sie sonst drei Schritte tief — im selben
Pass, in dem die Kreatur zum Mittelpunkt wird.

Die Galerie wird deshalb ein Push aus dem Fokus-Tab: Tap auf die Kreatur öffnet
`BestiaryView`. Ein Weg, eine Geschichte — sehen, schreiben, vollenden, sammeln.
`HistoryView` verliert den Abschnitt.

## 7. Der Start sagt, was wirklich passiert ist

Heute werden drei verschiedene Lagen zu einem Satz: Der gemeinsame Decoder
macht aus einem `ok: false` mit unbekanntem Fehlertext ebenso `.noAnswer` wie
aus einem Transportfehler, und die UI zeigt „Die Uhr hat nicht geantwortet"
(`FocusSessionView.swift:272-285`, `Shared/WatchCommand.swift`).

Getrennt werden:

| Ausgang | Bedeutung | Nächste Aktion |
|---|---|---|
| `started` | Die Uhr misst | — |
| `refused(grund)` | Bewusste Ablehnung, etwa laufende Studien-Aufnahme oder fehlende Workout-Freigabe | Der Grund wird benannt, mit der passenden Abhilfe |
| `timeout` | Erreichbar, Antwort blieb binnen 8 s aus | „Erneut versuchen", Verbindungsdetails |
| `unreachable` | WatchConnectivity nicht erreichbar | Hinweis im Kontext der Aktion, kein dauerhafter Banner |

**Ein Timeout ist ein unbekannter Zustand, kein Stopp.** Er darf keine laufende
Messung beenden und keine Erfolgsmeldung erzeugen; der nächste Poll löst die
Anzeige auf.

**Der Start hängt nicht am Server.** `focus_start` und `focus_stop` sind
lokale WatchConnectivity-Fälle. Eine getrennte WebSocket-Verbindung zum
Forschungsserver darf den Start nicht verhindern.

**Während einer laufenden Studien-Aufnahme bleibt der Start abgelehnt**, mit
Erklärung. Das folgt dem im Branch etablierten Prinzip, dass der Forschungspfad
Vorrang vor der Verbraucherfunktion hat.

## 8. Die Ränder der Designsprache

Fünf Stellen, an denen die App heute in System-Chrome ausläuft:

1. **Tab-Bar** (`RootPagerView.swift:26-39`): `circle.dashed`,
   `chart.bar.fill`, `list.bullet`, `person.fill` weichen vier **neu
   gezeichneten `Shape`-Pfaden** im Federstrich-Duktus der App — je ein Glyph
   für Tag, Verlauf der Zeit, Feder und Person, einfarbig und auf 24 Punkten
   lesbar. Ausdrücklich **keine** Bestiariums-Kreaturen als Tab-Symbole: die
   Kreatur ist die Belohnung des Fokus-Tabs und darf nicht zur Ikone einer
   Navigationsleiste abgewertet werden. `UITabBarAppearance` bekommt die
   Theme-Tokens.
2. **Segmented-Picker** (`TrendsView.swift:35-38`): zwei getönte
   Serifen-Schalter statt Stock-iOS mitten auf dem Papier. Sie behalten die
   Rolle `.isButton` und die Auswahl-Ansage, die `Picker` heute liefert.
3. **`flame.fill`** (`TrendsView.swift:82`): die Fitness-Trope, die
   `Scrybe/Components/InkRing.swift:37-42` im Kommentar ausdrücklich ablehnt.
   Ersetzt durch einen gezeichneten Federstrich als Streak-Marke — dieselbe
   Formensprache wie die Tab-Glyphen.
4. **Splash-Typografie** (`Components/ScrybeSplashView.swift:21`):
   `AvenirNext-Heavy` ist eine fette Sans, die im Rest der App nicht vorkommt —
   Marke und Anwendung widersprechen sich im ersten Moment des Öffnens. Die
   Serife der App übernimmt, in derselben Größenrelation.
5. **Empty-States** (`HistoryView.swift:100`): statt `list.bullet.rectangle`
   eine leere linierte Seite als Vignette — dasselbe Motiv, das der
   Fokus-Bereit-Zustand groß zeigt, hier klein und ohne Kreatur.

Kein Redesign: Die Token-Ebene bleibt unangetastet.
`Scrybe/ScrybeTheme.swift` dokumentiert gemessene WCAG-Kontraste pro Token und
hat den Opacity-Wildwuchs bereits konsolidiert. Das Fundament ist nicht das
Problem.

## 9. Dateiaufteilung

`FocusSessionView.swift` ist mit 292 Zeilen bereits die größte Scrybe-View und
bekäme sonst vier Zustände dazu. Sie wird aufgeteilt, damit jede Datei einen
Zweck hat:

- `FocusTabView` — der `NavigationStack`, die Zustandsweiche
- `FocusReadyView` — Bereit-Zustand: Seite, Kreatur, Dauersatz, Start
- `FocusDurationSheet` — Presets, freies Feld, „einfach schreiben"
- `FocusOutcomeView` — abgelehnt, Timeout, nicht erreichbar, fertig
- Lauf-Zustand bleibt bei `WritingPageView`

## 10. Accessibility

- Der neue Tab bekommt eine eindeutige VoiceOver-Bedeutung; die Kreatur trägt
  Name und Fortschritt als Label, nicht nur als Bild.
- Der Dauersatz wird als Schaltfläche angesagt, mit aktuellem Wert; das freie
  Feld nutzt Numeric Keyboard, sein Fehlertext nennt Bereich und Einheit.
- Alle neuen Übergänge respektieren Reduce Motion — insbesondere die
  Transition der Kreatur in die Marge.
- Die neuen Tab-Symbole tragen weiterhin Textlabels; Form ist nie die alleinige
  Information.
- Bei den ersetzten Stock-Bauteilen darf kein Verhalten verlorengehen, das
  `TabView` und `Picker` heute geschenkt liefern.

## 11. Abnahme

**Logiktests** nach Muster der bestehenden Suite:

- Dauer-Validierung: leer, 0, Dezimalwert, 4, 5, 180, 181.
- Die vier Startausgänge, je einzeln, inklusive später Antwort nach Timeout.
- „Noch etwa N Minuten" über einen Tierwechsel hinweg.
- Eine Sitzung ohne Ziel läuft, wird nicht vom Timer beendet und schreibt
  korrekt gut.
- Der Bereit-Zustand stellt keine Frage: die geöffnete Seite trägt die
  gespeicherte Dauer.

**Auf dem Gerät**, weil kein Test es beweist:

- Header und Tab-Bar verschwinden im Lauf-Zustand und kommen zurück.
- Die Kreatur ist bei 120–160 Punkten als Zeichnung lesbar, auch bei großer
  Schrift und auf einem kleinen iPhone.
- Fokusstart bei getrennter Server-Verbindung, aber verbundener Uhr.
- VoiceOver über Tabs, Dauersatz und Kreatur.

## 12. Getroffene Annahmen

1. **Dauerbereich 5–180 Minuten.** Unter fünf Minuten ist keine Sitzung; über
   180 greift ohnehin der Hard-Cap.
2. **Presets bleiben 15 / 25 / 45.** Sie sind eingeführt; die freie Eingabe
   deckt den Rest ab.
3. **Die Strichvorschau ist optional.** Sollte sie die Bereit-Seite überladen,
   entfällt sie — der Zustandssatz der Kreatur trägt die Motivation bereits.

## 13. Was dieser Pass nicht behauptet

Er macht die App nicht launchfertig. Der gemeinsame `WatchConnectionState`
fehlt danach weiterhin, und damit bleibt der im Plandokument §3.3 beschriebene
Widerspruch bestehen: ein grünes Header-Symbol neben einem älteren
Pull-Fehler in Trends. Dieser Pass behebt den Widerspruch nur dort, wo der
Fokus-Tab selbst ihn erzeugen würde.

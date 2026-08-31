# Scrybe: Fokus als Bereich, Bühne statt Formular (Design)

**Datum:** 2026-08-31
**Status:** Entwurf, Review-Runde 1 eingearbeitet
**Vorarbeit:** `docs/plans/2026-08-31-scrybe-launch-ui-and-focus-plan.md`
(Befundlage aus Screenshots und Code), `docs/specs/2026-08-29-scrybe-fokus-sitzung-design.md`
(die Sitzung selbst), Design-Zweitmeinung Fable 2026-08-31, Spec-Review mit
zwölf Befunden 2026-08-31

## 1. Ziel

Die Fokus-Sitzung ist die Marquee-Handlung der App, wird aber wie ein
Untermenüpunkt behandelt: eine Listenzeile mit `chevron.right` zwischen
Tagesstatistiken (`Scrybe/TodayView.swift:130`), geöffnet als
`fullScreenCover` (`:74`), und dahinter zuerst ein Formular mit der Frage
„Wie lange willst du schreiben?" (`Scrybe/FocusSessionView.swift:102-125`).
Die kunstvolle Seite sieht man erst nach dem Start.

Dieser Pass macht vier Dinge:

1. **Fokus wird ein eigener Tab** und öffnet als fertige, startbereite Seite
   statt als Formular.
2. **Das Ziel bleibt offen formulierbar**, ohne dass eine Frage den Einstieg
   besetzt.
3. **Start und Stopp sagen die Wahrheit** — vier bzw. drei unterscheidbare
   Ausgänge statt eines Satzes.
4. **Die Designsprache erreicht die Ränder** — Tab-Bar, Picker, Splash,
   Streak-Marke, Empty-States.

### Nicht im Umfang

Trends-Tagesauswahl und Zeitraumnavigation · Verlauf-Aggregation auf
Tageszusammenfassungen · das adaptive Zielmaß des Heute-Rings · die
Profilhierarchie · der vollständige `WatchConnectionState` über Header, Profil
und Offline-Banner hinweg.

Zwei Ausnahmen mit Begründung:

- **Ein schlichter Einstieg von Trends in den Verlauf** ist enthalten (§3).
  Ohne ihn wäre Verlauf nach der Tab-Umstellung nicht mehr erreichbar — kein
  aufgeschobener Ausbau, sondern ein Rückschritt.
- **Der minimale Statusvertrag** ist enthalten (§9). Der Fokus-Tab zeigt einen
  Tracking-Zustand an; zeigte er ihn mit der heutigen Semantik, würde die neue
  Oberfläche den bekannten Widerspruch fortschreiben, statt ihn zu vermeiden.

## 2. Leitprinzip

**Der Bereit-Zustand zeigt, was gleich wachsen soll — nicht die Frage, wie
lange.**

Scrybe besitzt die Fokus-Mechanik bereits vollständig:
`BestiaryStore.addWritingSeconds` lässt genau eine Kreatur mit *gutgeschriebener
Schreibzeit* wachsen, 30 Minuten pro Tier (`Shared/Bestiary.swift:97`),
strichweise und sitzungsübergreifend. Was fehlt, ist keine Mechanik, sondern
eine Bühne: in der laufenden Sitzung ist die Kreatur
`creatureBoxSize = lineHeight` (`Scrybe/Components/WritingPageView.swift:162`),
also 32 Punkte — als Belohnung faktisch unsichtbar.

Die Anleihe bei Fokus-Timern wie Forest ist damit ein Prinzip, keine Optik:
*ein* lebendes Ding im Zentrum, das nur durch echte Arbeit wächst. Scrybes
Übersetzung ist nicht eine Pflanze, die wächst, sondern **eine Zeichnung, die
vollendet wird**.

**Ausdrücklich nicht übernommen wird das Sterben.** Ein abgebrochener Fokus
darf die Kreatur nicht beschädigen. Zwei Gründe: der Store hält Pausen bereits
still, statt zu reduzieren, und eine Strafe auf Basis eines fehlbaren
Klassifikators würde Menschen für Modellfehler bestrafen — die Schreiberkennung
hat dokumentierte False Negatives bei Soft-Writern.

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
Must-have). Dieser Pass ergänzt dafür das Minimum: eine Zeile „Verlauf öffnen"
am Fuß von Trends, die `HistoryView` pusht. Die reichhaltige Tagesauswahl
ersetzt sie später.

**Die Karte „Fokus-Sitzung" fällt aus Heute** (`TodayView.swift:116-147`, samt
`fullScreenCover` in `:74-78`). An ihre Stelle tritt eine schmale Zeile
„Fokus läuft · 12:34 — öffnen", die **nur** bei laufender Sitzung erscheint.

### Wo der NavigationStack sitzt

`HistoryView.swift:21` besitzt heute einen eigenen `NavigationStack`. Wird er
künftig aus Trends geschoben, entstünden verschachtelte Stacks — mit doppelten
Navigationsleisten und unvorhersehbarem Zurück-Verhalten.

**Regel: Der Stack gehört der Tab-Wurzel.** Trends und Fokus besitzen je einen.
`HistoryView` und `BestiaryView` geben ihren ab und werden reiner schiebbarer
Inhalt. (Der `NavigationStack` in `DayDetailView.swift:144` steht nur in einem
`#Preview` und bleibt unangetastet.)

### Ruhe im Lauf-Zustand

`ScrybeHeader` steht als Geschwister der `TabView` in einem `VStack`
(`RootPagerView.swift:23-24`), ist also global. `.toolbar(.hidden, for:
.tabBar)` entfernt darum nur die untere Leiste. Der Header braucht eine eigene
Sichtbarkeitsbedingung in `RootPagerView`, gespeist aus der Fokus-Phase.

Das ist der einzige Punkt, an dem dieser Pass die Wurzel anfasst.

## 4. Die Zustände des Fokus-Tabs

**Bereit.** Eine leere linierte Seite; `WritingPageView` rendert mit leeren
Segmenten bereits die Regel-Linie. Darauf die aktuelle Kreatur bei 120–160
Punkten. Darunter, in Serifenkursive, ihr Name und Zustand („Trompetenhase · im
Entstehen") und der Fortschrittssatz aus §7. Darunter der Dauersatz (§6) und
eine aktive Startaktion.

**Verbindung wird geprüft.** Startaktion deaktiviert, Fortschrittsanzeige,
„Watch wird erreicht …", sichtbare Abbruchmöglichkeit.

**Läuft.** Header und Tab-Bar ausgeblendet, die Seite füllt sich. Die Kreatur
wandert per Transition aus der Mitte in die Marge — wie eine illuminierte
Initiale, die dem Text vorausgeht. Weil die Tab-Bar fehlt, trägt die Seite
selbst die einzige Ausstiegsaktion: „Beenden" am unteren Rand, zurückgenommen,
aber immer sichtbar und ohne Geste erreichbar.

**Nicht gestartet.** Drei unterscheidbare Ausgänge (§8).

**Fertig.** Schreibzeit, gezeichnete Striche, Weg ins Tagesdetail. Zielerreichung
wird **nur** angezeigt, wenn ein Ziel gesetzt war.

### Die Kreatur in Zeichnungsgröße

`CreatureCanvas` ist heute `private` in `Scrybe/BestiaryView.swift:91` und
damit außerhalb der Galerie nicht verwendbar. Sie wird nach
`Scrybe/Components/CreatureCanvas.swift` gezogen, wird internal und nimmt ihre
Kantenlänge als Parameter.

`WritingPageView` behält seine 32 Punkte für die Marge; der Bereit-Zustand
fordert 120–160. Eine gemeinsame Komponente statt zweier Zeichenpfade, damit
Marge und Bühne dieselbe Kreatur zeigen.

## 5. Dauer und Hard-Cap

`FocusCommandPolicy.sessionCapSeconds` beträgt heute 60 Minuten
(`Shared/WatchCommand.swift:275`). Der Kommentar dort nennt den Grund: ein
Force-Quit hängt jeden Telefon-Pfad aus, während die Workout-Sitzung die
Sensoren weiterlaufen lässt, also muss der Cap dort liegen, wo der Sensor sitzt.

**Entscheidung: Der Cap steigt auf 120 Minuten, die Eingabe erlaubt 5–120.**

Damit deckt die App auch lange Schreibsitzungen ab. Der Preis ist benannt: das
Fenster, in dem ein abgestürztes iPhone die Uhr weiter messen lässt, verdoppelt
sich. Eine Dauer anzubieten, die die Uhr anschließend abschneidet, wäre die
schlechtere Alternative gewesen.

Die Konstante ist in `Shared/` definiert und wird an beiden Enden erzwungen; die
Änderung betrifft daher iPhone **und** Watch und braucht einen Gerätetest, der
eine Sitzung über 60 Minuten hinaus laufen sieht.

## 6. Die Dauer ist ein Wort, kein Feld

`targetMinutes` (`FocusSessionView.swift:34`) wechselt von `@State` auf
`@AppStorage` mit einem **eigenen Schlüssel**
`ScrybeSettings.focusDurationKey`, Default 25. Er darf nicht mit
`ScrybeSettings.goalKey` (Tagesziel, `ProfileView.swift:97`) verwechselt werden.
Eine Migration entfällt, weil es keinen Vorgänger gibt: fehlt der Schlüssel,
gilt der Default.

**Der neue Schlüssel muss in die Lösch-Liste** in `ProfileView.swift:265-267`.
Sonst überlebt die Fokusdauer ein „alle lokalen Daten löschen" — genau die
Klasse von Widerspruch zwischen Zusage und gespeicherten Daten, die Audit §6.2
geschlossen hat.

Unter der Kreatur steht ein Satz in der Sprache der App:

> Eine Sitzung von **25 Minuten**

Die Zahl ist getönt und als Schaltfläche ausgezeichnet. Ein Tap öffnet ein
kompaktes Sheet (`presentationDetents([.height(…)])`) mit:

- den drei Presets 15 / 25 / 45,
- einem validierten Feld für **5 bis 120 Minuten**, ganze Zahlen,
- der Option **„einfach schreiben"** ohne Ziel.

Das Formular verschwindet nicht, es wird auf Abruf gestellt.

### „Einfach schreiben" im Datenmodell

`Phase.running` trägt heute `targetSeconds: Double`
(`Stores/FocusSessionStore.swift:29`), ein Ziel ist also Pflicht. Das ändert
sich:

```swift
case running(startedAt: Date, targetSeconds: Double?)
```

- `nil` bedeutet: ohne Ziel.
- **Der Hard-Cap gilt unverändert**, er hängt nicht am Ziel. Eine Sitzung ohne
  Ziel endet durch die Nutzerin oder durch den Cap — nie durch einen Timer.
- Unterzeile mit Ziel: „12:34 von 25 min". Ohne Ziel: „seit 12:34".
- `finished` darf ohne Ziel keine Zielerreichung behaupten; die Fertig-Ansicht
  zeigt dann Schreibzeit und Striche, aber keinen Soll-Ist-Vergleich.

**Warum das ehrlich ist:** Das Ziel war schon vorher rein darstellend — es
liefert die Unterzeile. Die Option macht diese Semantik sichtbar, statt sie zu
verstecken.

## 7. Die Fortschrittsvorschau — eine Formel, drei Zustände

„Noch etwa N Minuten, bis er fertig gezeichnet ist" muss in Bereit-, Lauf- und
Fertig-Zustand denselben Wert liefern. Verbindlich:

```
verbleibend = Bestiary.secondsPerCreature − writingSeconds(aktuelles Tier)
```

- **Nur das aktuelle Tier.** Ein Tierwechsel wird nicht eingerechnet.
- Überschreitet die gewählte Dauer den Rest, sagt der Satz das in Worten
  („… und du beginnst ein neues"), **ohne die Zahl zu verändern**.
- Eine Funktion, an einer Stelle, von allen drei Zuständen aufgerufen und
  unit-getestet.

Wird zusätzlich eine erwartete Strichzahl gezeigt, ist sie ausdrücklich
Erwartung. Die echte Zeichnung wächst nach gutgeschriebener Schreibzeit;
liefert die Uhr keine Schreibfenster, steht der Fortschritt still. Ein Timer,
der ein Tier von selbst fertigzeichnet, wäre eine Lüge über die Messung.

## 8. Start und Stopp sagen, was passiert ist

Heute werden drei Lagen zu einem Satz: Der gemeinsame Decoder macht aus einem
`ok: false` mit unbekanntem Fehlertext ebenso `.noAnswer` wie aus einem
Transportfehler, und die UI zeigt „Die Uhr hat nicht geantwortet"
(`FocusSessionView.swift:272-285`).

### Start

| Ausgang | Bedeutung | Nächste Aktion |
|---|---|---|
| `started` | Die Uhr misst | — |
| `refused(grund)` | Bewusste Ablehnung: laufende Studien-Aufnahme oder fehlende Workout-Freigabe | Grund benennen, passende Abhilfe |
| `unconfirmed` | **Start unbestätigt — binnen 8 s kam keine Antwort.** Kein Beweis für Erreichbarkeit, aber auch keiner für Scheitern | „Erneut versuchen", Verbindungsdetails |
| `unreachable` | WatchConnectivity meldet einen Transportfehler | Hinweis im Kontext der Aktion, kein dauerhafter Banner |

**Ein unbestätigter Start ist ein unbekannter Zustand, kein Stopp.** Er darf
keine laufende Messung beenden und keine Erfolgsmeldung erzeugen; der nächste
Poll löst die Anzeige auf.

### Stopp

`stopUnconfirmed` existiert bereits (`Stores/FocusSessionStore.swift:41`) und
wird angezeigt (`FocusSessionView.swift:215`), ist aber nicht die ganze Matrix:

| Lage | Anzeige |
|---|---|
| Stopp ohne Antwort | „Beendet, aber die Uhr hat nicht bestätigt" — der Sensorstrom läuft womöglich weiter |
| Uhr durch Study Mode übernommen | Die Sitzung endete, weil eine Aufnahme sie verdrängt hat; das wird benannt |
| App beendet, Uhr läuft weiter | Beim nächsten Start findet die App eine laufende Sitzung vor und bietet an, sie zu übernehmen oder zu beenden — statt eine zweite zu öffnen |

**Der Start hängt nicht am Server.** `focus_start` und `focus_stop` sind lokale
WatchConnectivity-Fälle. Eine getrennte WebSocket-Verbindung zum
Forschungsserver darf den Start nicht verhindern.

## 9. Der minimale Statusvertrag

`WatchStatusDot.swift:21` und `TodayView.swift:37` fragen beide
`FocusStore.isRecentlyWriting()`, das mit einem Fenster von 15 Minuten arbeitet
(`Stores/FocusStore.swift:33`). Der Kommentar dort begründet das für den
passiven Pfad korrekt: `CMSensorRecorder` ist erst Minuten im Nachhinein
lesbar, „jetzt" wäre eine Behauptung ohne Deckung.

Für eine **laufende Fokus-Sitzung** liegt die Wahrheit dagegen live vor. Beides
über denselben Punkt auszudrücken, macht ihn mehrdeutig.

**Zwei Aussagen statt zweier Antworten auf dieselbe Frage:**

- „hat kürzlich geschrieben" — 15-Minuten-Fenster, speist den Tagesring und
  die passive Anzeige. Unverändert.
- „misst gerade" — nur bei aktiver Fokus- oder Recording-Ownership. Speist den
  Tracking-Punkt.

Der bestehende Kommentar in `FocusStore.swift` verlangt, dass Ring und Glyphe
auf demselben Schirm nie widersprechen. Diese Trennung erfüllt das, weil beide
danach verschiedene Dinge sagen — nicht dasselbe unterschiedlich.

Der vollständige `WatchConnectionState` über Header, Profil und Offline-Banner
bleibt außerhalb dieses Passes (§1).

## 10. Die Ränder der Designsprache

Fünf Stellen, an denen die App heute in System-Chrome ausläuft:

1. **Tab-Bar** (`RootPagerView.swift:26-39`): `circle.dashed`,
   `chart.bar.fill`, `list.bullet`, `person.fill` weichen vier neu gezeichneten
   `Shape`-Pfaden im Federstrich-Duktus — je ein Glyph für Tag, Verlauf der
   Zeit, Feder und Person, einfarbig und auf 24 Punkten lesbar. Ausdrücklich
   **keine** Bestiariums-Kreaturen als Tab-Symbole: die Kreatur ist die
   Belohnung des Fokus-Tabs und darf nicht zur Navigationsikone abgewertet
   werden.
2. **Segmented-Picker** (`TrendsView.swift:35-38`): zwei getönte
   Serifen-Schalter statt Stock-iOS mitten auf dem Papier.
3. **`flame.fill`** (`TrendsView.swift:82`): die Fitness-Trope, die
   `Components/InkRing.swift:37-42` im Kommentar ausdrücklich ablehnt. Ersetzt
   durch einen gezeichneten Federstrich in derselben Formensprache wie die
   Tab-Glyphen.
4. **Splash-Typografie** (`Components/ScrybeSplashView.swift:21`):
   `AvenirNext-Heavy` ist eine fette Sans, die im Rest der App nicht vorkommt —
   Marke und Anwendung widersprechen sich im ersten Moment des Öffnens. Die
   Serife der App übernimmt, in derselben Größenrelation.
5. **Empty-States** (`HistoryView.swift:100`): statt `list.bullet.rectangle`
   eine leere linierte Seite als Vignette — dasselbe Motiv, das der
   Bereit-Zustand groß zeigt, hier klein und ohne Kreatur.

### Auflage: kein Verhalten darf verlorengehen

Der Review hat zu Recht darauf hingewiesen, dass eigene Shapes plus
`UITabBarAppearance` natives Accessibility-Verhalten verschlechtern können. Die
Entscheidung, sie trotzdem in diesen Pass zu nehmen, gilt unter einer Auflage:

- Die `TabView` selbst bleibt Stock — ersetzt werden nur Symbole und Erscheinung,
  nie der Container. Auswahl, Zustandserhalt und Safe-Area-Verhalten bleiben
  damit unverändert.
- Jedes Tab-Item behält sein Textlabel. Form ist nie die alleinige Information.
- Die Serifen-Schalter in Trends behalten die Button-Rolle und die
  Auswahl-Ansage, die `Picker` heute liefert.
- Ist eine dieser Bedingungen nicht erfüllbar, fällt die betreffende Stelle aus
  dem Pass — nicht die Bedingung.

Kein Redesign darüber hinaus: `Scrybe/ScrybeTheme.swift` dokumentiert gemessene
WCAG-Kontraste pro Token und hat den Opacity-Wildwuchs bereits konsolidiert. Das
Fundament ist nicht das Problem.

## 11. Dateiaufteilung

`FocusSessionView.swift` ist mit 292 Zeilen bereits die größte Scrybe-View und
bekäme sonst mehrere Zustände dazu:

- `FocusTabView` — der `NavigationStack`, die Zustandsweiche
- `FocusReadyView` — Seite, Kreatur, Fortschrittssatz, Dauersatz, Start
- `FocusDurationSheet` — Presets, freies Feld, „einfach schreiben"
- `FocusOutcomeView` — die Start- und Stopp-Ausgänge, fertig
- `Components/CreatureCanvas.swift` — aus `BestiaryView` gezogen
- Lauf-Zustand bleibt bei `WritingPageView`

## 12. Accessibility

- Der neue Tab bekommt eine eindeutige VoiceOver-Bedeutung; die Kreatur trägt
  Name und Fortschritt als Label, nicht nur als Bild.
- Der Dauersatz wird als Schaltfläche mit aktuellem Wert angesagt; das freie
  Feld nutzt Numeric Keyboard, sein Fehlertext nennt Bereich und Einheit.
- Alle neuen Übergänge respektieren Reduce Motion, insbesondere die Transition
  der Kreatur in die Marge.
- Der Tracking-Punkt ist nie nur Farbe; sein Label sagt, was er behauptet.
- Die Auflagen aus §10 gelten als Abnahmekriterium, nicht als Absicht.

## 13. Abnahme

### Logiktests

- Dauer-Validierung: leer, 0, Dezimalwert, 4, 5, 120, 121.
- Die vier Startausgänge einzeln, inklusive später Antwort nach einem
  unbestätigten Start.
- Die drei Stopp-Lagen aus §8.
- Fortschrittsformel über einen Tierwechsel hinweg, in allen drei Zuständen
  identisch.
- Sitzung ohne Ziel: läuft, wird nicht vom Timer beendet, endet am Cap, zeigt
  keinen Soll-Ist-Vergleich.
- Der `focusDurationKey` wird vom Zurücksetzen erfasst.
- Der Bereit-Zustand stellt keine Frage: die geöffnete Seite trägt die
  gespeicherte Dauer.

### Auf dem Gerät, weil kein Test es beweist

- Fokusstart bei **getrennter Server-WebSocket-Verbindung**, aber erreichbarer
  Uhr.
- Watch-App im Vordergrund; Watch-App im Hintergrund.
- Workout-Berechtigung verweigert — die Ablehnung wird als solche erklärt.
- Eine Sitzung über 60 Minuten hinaus, gegen den neuen Cap von 120.
- Header und Tab-Bar verschwinden im Lauf-Zustand und kommen zurück.
- Die Kreatur ist bei 120–160 Punkten lesbar, auch bei großer Schrift und auf
  einem kleinen iPhone.
- VoiceOver über Tabs, Dauersatz, Tracking-Punkt und Kreatur.
- Physischer iPhone- **und** Watch-Build, nicht nur Simulator.

## 14. Getroffene Annahmen

1. **Presets bleiben 15 / 25 / 45.** Sie sind eingeführt; die freie Eingabe
   deckt den Rest ab.
2. **Die Strichvorschau ist optional.** Überlädt sie die Bereit-Seite, entfällt
   sie — der Fortschrittssatz trägt die Motivation bereits.

## 15. Was dieser Pass nicht behauptet

Er macht die App nicht launchfertig. Der vollständige `WatchConnectionState`
fehlt danach weiterhin, und damit bleibt der im Plandokument §3.3 beschriebene
Widerspruch zwischen Header-Symbol und älterem Pull-Fehler in Trends bestehen.
Dieser Pass sorgt nur dafür, dass der Fokus-Tab ihn nicht fortschreibt.

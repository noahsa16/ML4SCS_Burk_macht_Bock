# Scrybe Launch-Readiness: UI-, Fokus- und Datenplan

**Stand:** 31. August 2026  
**Status:** Dokumentation und Entscheidungsgrundlage — noch keine Produktcode-
Änderungen in diesem Pass.  
**Betroffene Flächen:** iPhone-App (`watch_streamer/WatchStreamer/Scrybe`),
WatchConnectivity und der lokale Fokus-/Bestiary-Store.

## 1. Ziel dieses Dokuments

Dieses Dokument übersetzt die aktuellen Screenshots und die gemeldeten
Geräteprobleme in einen konkreten, testbaren Arbeitsplan. Es trennt dabei:

1. **beobachtete Symptome** (was auf dem iPhone sichtbar ist),
2. **statisch belegte Ursachen oder Architekturspannungen** (was der Code
   aktuell tut),
3. **Produktentscheidungen** (wie sich Scrybe vor dem Launch anfühlen soll),
4. **technische Umsetzung und Abnahmekriterien** (wann ein Punkt wirklich
   erledigt ist).

Die fünf angehängten Screenshots sind dabei die visuelle Baseline: Heute,
Fokus-Sitzung, Trends, Verlauf und Profil.

## 2. Kurzfazit

Die App hat bereits eine erkennbare Identität: dunkles Papier, Serifentitel,
Gold als Scrybe-Farbe und ein klarer Schreibzeit-Ring. Vor dem Launch sind aber
vier Dinge wichtiger als weitere Dekoration:

- **Vertrauen:** Ein grünes Watch-Symbol darf nicht gleichzeitig mit „Uhr nicht
  erreichbar“ und „Watch getrennt“ auftreten.
- **Ein klarer Einstieg:** Fokus-Sitzung braucht einen eigenen Tab und darf
  nicht als zufällige Karte zwischen Tagesstatistiken versteckt sein.
- **Ein belastbarer Fokusstart:** „Sitzung starten“ muss zwischen
  *verbunden*, *Antwort unterwegs*, *abgelehnt* und *wirklich nicht
  erreichbar* unterscheiden.
- **Weniger Listenrauschen:** Verlauf soll Tage und Zeiträume zeigen. Einzelne
  0–1-Minuten-Entscheidungsphasen gehören in einen Drilldown, nicht in die
  primäre Navigation.

## 3. Ist-Zustand mit Codebelegen

### 3.1 Navigation und Informationsarchitektur

Die Root-Navigation hat aktuell vier Tabs: Heute, Trends, Verlauf und Profil
(`watch_streamer/WatchStreamer/Scrybe/RootPagerView.swift:3-39`). Die
Fokus-Sitzung wird dagegen als Full-Screen-Cover aus Heute geöffnet
(`watch_streamer/WatchStreamer/Scrybe/TodayView.swift:74-77,116-147`). Dadurch
ist die wichtigste aktive Handlung kein gleichrangiger Bereich und ein
laufender Fokus kann nur über Heute wiedergefunden werden.

**Konsequenz:** Zielstruktur sind vier Tabs **Heute · Trends · Fokus · Profil**.
Verlauf bleibt erreichbar, aber als Drilldown aus Trends und/oder einem
Tagesdetail.

### 3.2 Ring und vertikale Balance

Der Ring wird derzeit in einer `GeometryReader`-Klammer auf maximal 240 Punkte
begrenzt (`TodayView.swift:149-180`). Die Geometrie reserviert exakt diese
Höhe, während der Inhalt zusätzlich mit 8 Punkten Top-Padding versehen wird.
Auf dem Screenshot wirkt er dadurch kleiner als der verfügbare Bildschirmraum
und nicht als optischer Mittelpunkt der Seite.

**Konsequenz:** Ring als adaptive, zentral ausgerichtete Hero-Komponente mit
größerem Zielmaß (ca. 272–288 Punkte auf großen iPhones), ohne zusätzlichen
unsichtbaren Versatz. Kleine Geräte und Dynamic Type bleiben begrenzt.

### 3.3 Widersprüchlicher Watch-Status

Es gibt mehrere Wahrheitsquellen:

- Das Header-Symbol betrachtet `server.watchPolling || bridge.isConnected`
  (`Scrybe/Components/WatchStatusDot.swift:21-31`).
- Das Profil betrachtet ausschließlich `server.watchPolling`
  (`Scrybe/ProfileView.swift:164-170`).
- Trends und Verlauf zeigen `OfflineBanner`, sobald der **letzte Pull** keine
  Antwort hatte (`Scrybe/TrendsView.swift:28-34`,
  `Scrybe/HistoryView.swift:42-48`).
- `FocusStore.watchUnreachable` ist ausdrücklich ein Ergebnis des letzten
  Pulls, kein aktueller Verbindungsstatus (`Stores/FocusStore.swift:20-26,
  113-126`).

Das erklärt den Screenshot: ein frisches WatchConnectivity-Signal kann das
Header-Symbol grün machen, während ein alter Pull-Fehler weiter als gelbe
Warnung in Trends/Verlauf steht.

**Konsequenz:** Ein gemeinsames `WatchConnectionState` mit mindestens
`connected`, `polling`, `lastSeen`, `lastCommand`, `lastError` und optional
`tracking` wird die einzige UI-Wahrheit. Ein Pull-Fehler ist nur noch ein
kurzlebiges Refresh-Ergebnis, kein dauerhafter „Watch getrennt“-Banner.

### 3.4 Fokusstart und „keine Antwort“

Die UI startet aus `FocusSessionView.startSession()` ausschließlich über
`ServerCommandListener.startFocusSession()` und zeigt bei `.noAnswer` den
pauschalen Satz „Die Uhr hat nicht geantwortet“ (`FocusSessionView.swift:272-285`).
Der Listener sendet per `WCSession.sendMessage`, wartet bis zu acht Sekunden
und reicht Transportfehler ebenfalls als nicht erfolgreiche Antwort weiter
(`ServerCommandListener.swift:402-428,626-729`).

Auf der Watch wird `focus_start` zwar auf dem Main-Thread beantwortet
(`WatchStreamer Watch App/MotionManager.swift:1235-1242`), aber ein `ok: false`
mit unbekanntem Fehlertext wird im gemeinsamen Decoder ebenfalls zu
`.noAnswer` (`Shared/WatchCommand.swift:195-211`). Für die Nutzeroberfläche
gehen damit drei unterschiedliche Situationen verloren:

1. WatchConnectivity ist nicht erreichbar.
2. Die Watch ist erreichbar, aber die Antwort kam zu spät.
3. Die Watch hat die Anfrage bewusst abgelehnt (z. B. laufende Aufnahme oder
   fehlende Workout-Berechtigung).

**Konsequenz:** Transportstatus, Watch-Refusal und Timeout werden getrennt
modelliert und mit einer passenden nächsten Aktion dargestellt. Der Start darf
nicht vom WebSocket zum Server abhängen; der direkte WatchConnectivity-Pfad ist
die maßgebliche Verbindung für diese lokale Funktion.

### 3.5 Freie Fokusdauer fehlt

Die Auswahl ist aktuell auf `[15, 25, 45]` Minuten beschränkt
(`FocusSessionView.swift:48-49,102-124`). Der eigentliche Start verwendet den
ausgewählten Wert direkt (`FocusSessionView.swift:277-281`). Es gibt noch keine
validierte freie Eingabe und keine sichtbare Berechnung, wie viele
Bestiary-Striche das gewählte Ziel erzeugt.

**Konsequenz:** Presets bleiben als Schnellwahl; zusätzlich kommt ein
numerisches „Eigene Dauer“-Feld mit klarer Einheit und einem definierten
Bereich. Die ausgewählte Dauer wird vor dem Start als erwartete
Strich-/Fortschrittsmenge erklärt. Die bestehende Bestiary-Wahrheit bleibt
erhalten: Die tatsächliche Zeichnung wächst nach **gutgeschriebener
Schreibzeit**, nicht nach bloßem Ablauf des Timers (`BestiaryStore.swift:127-153`,
`Bestiary.swift:80-118`).

### 3.6 Trends sind zusammengefasst, aber nicht erkundbar

Trends besitzt nur einen Wochen-/Monat-Segmented-Picker und rendert danach
entweder `WeekStrip` oder `RangeBarChart` (`TrendsView.swift:28-72`). Die
Diagramme liefern keine ausgewählte Tagesansicht, keine Vor-/Zurück-Navigation
für Zeiträume und keinen offensichtlichen Weg in den Detailverlauf.

Die Datenbasis kann 90 Tage halten, bereitet aber nur `monthDays` und
Vergleichssummen vor (`FocusStore.swift:461-481`). Das ist genug für eine
interaktive erste Version, ohne den Serververtrag zu erweitern.

**Konsequenz:** Wochen- und Monatsansicht bekommen auswählbare Balken/Tage,
eine Detailkarte für den aktuellen Auswahlpunkt und eine Navigation zu den
aggregierten Tagesphasen. Vor-/Zurück-Navigation wird nur aktiviert, wenn der
Datensatz den angefragten Zeitraum tatsächlich enthält.

### 3.7 Verlauf zeigt zu viele Kleinstphasen

Verlauf rendert für jeden aktiven Tag jede einzelne Stretch-Zeile und packt
zusätzlich eine Sparkline in jede Zeile (`HistoryView.swift:42-75,
163-180`). Die zugrunde liegenden `FocusStretchDTO` sind technisch korrekt,
aber als Primäransicht führen sie zu vielen 0–1-Minuten-Einträgen wie im
Screenshot.

**Konsequenz:** Primäransicht = ein Tages-/Zeitraum-Row mit Gesamtzeit,
Anzahl fokussierter Phasen und Zielstatus. Tap öffnet `DayDetailView` mit den
einzelnen Phasen, Intensität und Zeitstempeln. Die Rohgranularität bleibt
erhalten, wird aber aus dem Einstieg entfernt.

### 3.8 Profil ist funktional, aber nicht launchfertig

Das Profil enthält bereits Ziel, Erinnerung, Watch, Einstellungen, Export und
Datenschutz (`ProfileView.swift:13-37,95-255`). Visuell fehlt jedoch eine
Hierarchie zwischen „mein Fortschritt“, „Gerät“ und „App“. Der Watch-Status
nutzt außerdem die falsche Einzelquelle (siehe 3.3). Die Admin-Funktion ist
absichtlich versteckt und darf nicht Teil der normalen Profil-Erzählung werden
(`ProfileView.swift:40-72`).

**Konsequenz:** Profil erhält eine kompakte Identitäts-/Fortschrittskopfleiste,
eine eindeutig beschriftete Gerätekarte, Einstellungen und Datenschutz als
sekundäre Bereiche. Keine zusätzlichen Gamification-Karten im Profil.

## 4. Zielbild für die Nutzerführung

### 4.1 Tabs

| Tab | Aufgabe | Primäre Aktion |
|---|---|---|
| Heute | „Wie stehe ich heute?“ | Daten per Pull aktualisieren |
| Trends | „Wie entwickelt sich mein Schreiben?“ | Zeitraum/Tage erkunden, Verlauf öffnen |
| Fokus | „Jetzt bewusst schreiben“ | Dauer wählen und Sitzung starten |
| Profil | „Ziel, Gerät, Datenschutz“ | Einstellungen ändern |

Der Header bleibt global. Sein Watch-Symbol zeigt nur den gemeinsamen
Verbindungszustand; ein winziger Akzentpunkt zeigt **aktives Fokus-Tracking**,
nicht rückwirkend erkannte Schreibzeit.

Die Karte „Fokus-Sitzung“ wird aus Heute entfernt. Wenn eine Sitzung läuft,
zeigt Heute höchstens eine schmale Statuszeile „Fokus läuft · 12:34 — öffnen“;
die Steuerung liegt im Fokus-Tab.

### 4.2 Fokus-Tab: Zustände

1. **Bereit:** Dauer-Presets, freie Dauer, erwartete Bestiary-Fortschrittsinfo,
   große Startaktion.
2. **Verbindung wird geprüft:** Startaktion deaktiviert, Fortschrittsanzeige,
   „Watch wird erreicht …“ und sichtbare Abbruchmöglichkeit.
3. **Läuft:** Timer, dezenter Tracking-Punkt, laufende Seite/Bestiary,
   „Pause/Beenden“ mit Bestätigung nur bei versehentlichem Tap.
4. **Abgelehnt:** konkrete Erklärung (laufende Aufnahme oder Berechtigung) und
   passende Aktion.
5. **Timeout:** „Keine Antwort in 8 s“ mit „Erneut versuchen“ und einem Link zu
   den Watch-/Verbindungsdetails — nicht „verbunden“ überschreiben.
6. **Fertig:** Schreibzeit, Zielerreichung, gezeichnete Striche und Link zum
   Tagesdetail.

### 4.3 Dauer- und Bestiary-Regel

Die UX zeigt neben den Presets ein Feld `Minuten`, akzeptiert nur ganze Werte im
definierten Produktbereich und validiert vor dem Start. Die geplante Strichzahl
ist eine **Vorschau**, abgeleitet von:

- gewählter Fokusdauer,
- der bereits gutgeschriebenen Zeit des aktuellen Tiers,
- `Marginalia.strokeCount(forSpecies:)`.

Die echte Zeichnung darf nicht vom Countdown allein abhängen. Wenn die Watch
keine Schreibfenster liefert, bleibt der Fortschritt stehen; das ist fachlich
ehrlicher als ein Timer, der ein Tier automatisch fertigzeichnet.

## 5. Verbindungs- und Datenvertrag

### 5.1 Eine Statusquelle

Ein zentraler, beobachtbarer Zustand soll aus folgenden Signalen gebildet
werden:

- `WCSession.activationState` und `WCSession.isReachable`,
- letzter erfolgreicher Watch-Poll (`watchPolling`, `watchPollAgeMs`),
- letzte erfolgreiche Entscheidungslieferung,
- laufende Fokus-/Recording-Ownership,
- letzter Fehler inklusive Quelle (`sync`, `focus_start`, `focus_stop`).

Priorität der Anzeige:

1. `tracking` (Fokus oder Recording aktiv) — grüner Punkt plus Watch-Symbol.
2. `connected` — grünes Watch-Symbol, kein Schreibpunkt.
3. `stale` — neutrales/amber Watch-Symbol mit „Zuletzt gesehen …“.
4. `unreachable` — Warnung nur im Kontext der fehlgeschlagenen Aktion.

### 5.2 Fokusstart darf nicht vom Server abhängen

`startFocusSession` und `stopFocusSession` müssen als lokaler
WatchConnectivity-Use-Case behandelt werden. Der WebSocket darf Status
spiegeln, aber keine notwendige Vorbedingung für den Start sein. Die Antwort
enthält immer `command_id`, `ok`, `error_code` und optional technische Details;
die UI übersetzt nur bekannte Fehlercodes.

### 5.3 Idempotenz und späte Antworten

Start/Stop behalten ihre Operation-ID. Eine späte Antwort darf keine bereits
beendete UI-Sitzung wieder öffnen. Ein Timeout ist ein unbekannter Zustand, kein
automatisches Stoppen. Der nächste Poll aktualisiert den tatsächlichen
Watch-Zustand und löst die offene Start-/Stop-Anzeige auf.

## 6. Trends-, Verlauf- und Insight-Konzept

### 6.1 Woche

- sieben klickbare Tagesbalken/-punkte;
- Auswahl zeigt Datum, Schreibzeit, Zielstatus, Anzahl Phasen und längste Phase;
- „Verlauf dieses Tages“ öffnet den Drilldown;
- Vor-/Zurück-Woche nur bei vorhandenem Datenfenster;
- Vergleich „gegen Vorwoche“ bleibt, bekommt aber eine erklärende
  Accessibility-Beschriftung.

### 6.2 Monat

- 30-Tage-Frieze statt 30 gleichgewichteter, schwer lesbarer Balken;
- Wochencluster als primäre Einheiten, einzelne Tage per Tap;
- Insights: aktive Tage, durchschnittliche Schreibzeit an aktiven Tagen,
  längste Phase, Zieltrefferquote;
- keine künstliche Aussage, wenn weniger als sieben Tage Daten vorhanden sind.

### 6.3 Verlauf

- tägliche Zusammenfassungen als Standard;
- konsolidierte Phasenanzeige mit einer klar dokumentierten Lückentoleranz;
- Detailseite mit den vorhandenen `FocusStretchDTO`-Daten;
- 0-Minuten-Zeilen werden nicht als eigene Nutzerzeile angezeigt, sofern sie
  keine echte Dauer oder Diagnoseinformation besitzen.

## 7. Visuelle Leitplanken

- Ring größer, horizontal exakt zentriert, vertikal mit dem Header als Hero
  balanciert.
- Eine dominante Aktion pro Screen; im Fokus-Tab ist das „Sitzung starten“.
- Gold bleibt für Ziele/Metadaten, Lavendel/Accent für aktive Auswahl, Grün nur
  für bestätigten Gerätezustand bzw. Erfolg.
- Kartenabstände reduzieren, wenn sie nur Containergruppen trennen; Verlauf
  soll wie ein Dokument wirken, nicht wie ein Diagnose-Log.
- Einheitliche Corner-Radius-/Inset-Tokens statt lokaler Einzelwerte.
- Statusmeldungen bleiben kurz und handlungsorientiert; keine dauerhaften
  Offline-Banner aus einem einzelnen fehlgeschlagenen Pull.

## 8. Accessibility und Robustheit

- Jeder Tab und jede Statusanzeige erhält eine eindeutige VoiceOver-Bedeutung;
  Farbe und Punkt sind nie die alleinige Information.
- Freie Dauer ist mit Numeric Keyboard, Dynamic Type und VoiceOver editierbar;
  Fehlertext nennt gültigen Bereich und Einheit.
- Diagramm-Balken werden als Buttons mit Datum und Wert angesagt.
- Animationen (Ring-Sweep, Puls, Übergänge) respektieren Reduce Motion.
- Große Touch-Ziele für Presets, Start, Stop und Tagesauswahl; kein
  ausschließliches Swipe-/Long-Press-Feature.
- Fokusstart/stop bleibt während Hintergrundwechseln deterministisch und zeigt
  bei unbekanntem Zustand keine falsche Erfolgsmeldung.

## 9. Umsetzungsreihenfolge

### Phase A — Vertrauen und Datenzustand

1. Gemeinsamen `WatchConnectionState` definieren.
2. Trends-/Verlauf-Banner an diesen Zustand oder an ein kurzes Refresh-Ergebnis
   binden; alte Pull-Warnung nicht persistieren.
3. Profil und Header auf dieselbe Quelle umstellen.
4. Fokusstart-Antworten in „started / refused / timeout / transport error“
   aufteilen und mit Tests abdecken.

### Phase B — Fokus als Produktbereich

1. Fokus als eigener Tab verschieben.
2. Heute-Karte durch eine knappe „läuft“-Statuszeile ersetzen.
3. Freie Dauer mit Validierung ergänzen.
4. Vorschau für Dauer, Schreibzeit und Bestiary-Striche hinzufügen.
5. Start-/Lauf-/Fehler-/Fertig-Zustände visuell und mit Accessibility testen.

### Phase C — Trends und Verlauf

1. Tagesauswahl in Wochen- und Monatsgrafik.
2. Insight-Karte und Drilldown-Link.
3. Verlauf auf Tageszusammenfassungen umstellen.
4. Bestehende Stretch-Details in `DayDetailView` behalten.

### Phase D — Polish

1. Ring auf adaptives Zielmaß und echte Zentrierung bringen.
2. Profilhierarchie und Gerätekarte überarbeiten.
3. Copy, Kontrast, Dynamic Type, Reduce Motion und leere Zustände prüfen.
4. Produktvideo-Szenario mit Demo-Daten und echter Watch-Verbindung separat
   abnehmen.

## 10. Abnahmekriterien

### Must-have vor Launch

- Kein Screen zeigt bei bestätigter Watch-Verbindung gleichzeitig „Uhr nicht
  erreichbar“.
- Fokusstart funktioniert ohne aktive Server-WebSocket-Verbindung, sofern
  WatchConnectivity erreichbar ist.
- Ein absichtlicher Watch-Refusal wird anders erklärt als ein Timeout.
- Fokus ist ein sichtbarer Haupt-Tab; Verlauf ist kein Haupt-Tab mehr.
- Freie Fokusdauer ist editierbar, validiert und wird im Lauf-/Fertigzustand
  korrekt angezeigt.
- Ring ist auf iPhone 15 Pro sichtbar größer und optisch zentriert, ohne auf
  kleinen Geräten oder bei größerer Schrift abgeschnitten zu werden.
- Trends-Tage sind auswählbar; Verlauf öffnet sich als Drilldown.
- Verlauf zeigt standardmäßig aggregierte Tage statt einer langen Liste von
  0–1-Minuten-Zeilen.
- Profil zeigt denselben Watch-Zustand wie Header und Fokus.

### Should-have

- Vor-/Zurück-Navigation für gespeicherte Wochen/Monate.
- Insights für aktive Tage, Durchschnitt und Zieltrefferquote.
- Erwartete Bestiary-Striche werden vor dem Start nachvollziehbar erklärt.
- Demo-Modus ist klar als Demo markiert und vermischt keine echten Daten.

## 11. Testmatrix für die spätere Umsetzung

### Unit-/Logiktests

- Statusaggregation: `bridge`, Poll, stale und Tracking ergeben die erwartete
  Anzeige.
- Fokusstart: `started`, bekannte Refusal-Codes, unbekannter Fehler,
  Transportfehler und Timeout.
- Freie Dauer: leer, 0, Dezimalwert, zu klein, zu groß, gültiger Grenzwert.
- Bestiary-Vorschau: Restfortschritt, Tierwechsel und Pausen.
- Trendauswahl und Zeitraumgrenzen.
- Verlauf-Aggregation inklusive Lückentoleranz und leerem Tag.

### UI-/Gerätetests

- Watch verbunden, App offen, Fokusstart und Fokusstop.
- Watch verbunden, App im Hintergrund, anschließender Poll.
- Watch nicht erreichbar: verständlicher Timeout und Retry.
- Server-WebSocket getrennt, WatchConnectivity verbunden: Fokus muss lokal
  startbar bleiben.
- Pull-to-refresh mit neuen, alten und keinen Daten.
- iPhone 15 Pro sowie kleines iPhone; Dynamic Type und Reduce Motion.
- VoiceOver auf Tabs, Dauerfeld, Diagramm-Tagen und Statuspunkt.

### Produktvideo-Szenario

1. App öffnen → grünes Watch-Symbol.
2. Fokus-Tab → z. B. 25 Minuten auswählen oder eigene Dauer eingeben.
3. Start → sichtbarer bestätigter Übergang in „läuft“.
4. Währenddessen: Punkt zeigt Tracking, Ring/Seite animiert ruhig.
5. Beenden → Schreibzeit, Striche und Tagesdetail.
6. Trends → Tag auswählen → Verlauf-Drilldown.

## 12. Offene Produktentscheidungen

Diese Punkte sollten vor der Implementierung einmal festgelegt werden:

1. **Dauerbereich:** z. B. 1–180 Minuten oder 5–480 Minuten wie beim Tagesziel.
2. **Bestiary-Vorschau:** nur Reststriche des aktuellen Tiers oder zusätzlich
   erwartete Striche für die gewählte Sitzung.
3. **Historienaggregation:** zulässige Pause zwischen zwei Schreibfenstern,
   bevor sie als getrennte Phase gelten.
4. **Zeitraumnavigation:** nur lokal vorhandene 90 Tage oder später ein
   Server-/Archiv-Endpunkt für ältere Daten.
5. **Fokus-Tab während laufender Aufnahme:** Fokusstart blockieren und klar
   erklären oder eine reine Beobachtungsansicht zulassen.

## 13. Was bewusst noch nicht geändert wurde

- Keine SwiftUI-Datei wurde in diesem Dokumentationspass verändert.
- Kein Watch-Build und kein Installationsversuch wurde als Produktbeweis
  gewertet; der letzte Simulator-Buildversuch war durch CoreSimulator-/Derived-
  Data-Berechtigungsfehler blockiert.
- Die gemeldete geringe Schreibzeit nach einer zweiminütigen Probe wird nicht
  durch eine neue Schwelle „wegoptimiert“. Das ist ein eigener
  Hardware-/Modellvalidierungsfall und muss mit Rohdaten, Watch-Entscheidungen
  und erwarteter Schreibphase reproduziert werden.

Dieses Dokument ist damit die gemeinsame Checkliste für den nächsten
Implementierungspass. Erst Phase A sollte begonnen werden; optisches Polish
ohne den Status-/Fokusvertrag würde die widersprüchlichen Zustände nur schöner
darstellen.

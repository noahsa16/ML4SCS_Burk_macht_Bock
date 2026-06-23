# Scrybe — iPhone-App-Redesign · Design-Spec

- **Datum:** 2026-06-22
- **Status:** Entwurf zur Review (Design im Brainstorming visuell bestätigt)
- **Scope:** Redesign der iOS-App (`watch_streamer/WatchStreamer/`) zu „Scrybe", einem Schreib-Fokus-Tracker, mit der bestehenden Betreiber-UI hinter einem Admin-Panel.
- **Kein Scope:** AirPods (überall entfernt), App-Store-Veröffentlichung, Redesign der Watch-App. Die Server-/ML-Pipeline bleibt unverändert.

## 1. Ziel & Kontext

Die iPhone-App ist heute reine Betreiber-/Bridge-Software (Tabs Dashboard/Session/Settings, Connectivity-Console, Repair, Recording-Health-Ampel). Scrybe dreht das um: **Held der App ist die schreibende Person**, nicht der Apparat. Die Hauptfläche ist ein ruhiges Tagesritual rund um die heutige Schreibzeit; der gesamte technische Betrieb wandert hinter ein verstecktes Admin-Panel.

Die Schreibdaten liefert der bestehende Server (Live-Inference + Focus-Aggregation) — Scrybe ist eine native, gestaltete Sicht darauf, keine neue Erkennungslogik.

## 2. Zwei Gesichter

| | Scrybe (vorne) | Admin (hinten) |
|---|---|---|
| Für wen | schreibende Person | Versuchsleitung |
| Inhalt | Schreibzeit, Streak, Trends, Verlauf | Verbindungen, Datenfluss, Session-Steuerung, Repair, Einstellungen |
| Zugang | App-Start | Langdruck auf die Wortmarke „Scrybe" → PIN |
| Stil | Tinte & Papier | Tinte & Papier (gleiche Welt, utilitaristischer) |

## 3. Informationsarchitektur & Navigation

- **Horizontaler Pager** mit Seiten-Punkten: **Heute ⟷ Trends ⟷ Verlauf**. Start auf „Heute".
- **Admin** ist keine Pager-Seite, sondern wird durch **2 s Langdruck auf die Wortmarke „Scrybe"** ausgelöst → **PIN-Gate** → Admin-Panel. (Spiegelt das Web-Dashboard, wo Triple-Klick aufs Logo den Admin öffnet.) Verlassen über „‹ Scrybe".
- Die PIN ist eine lokale Sperre gegen versehentliches/proband-seitiges Öffnen, kein Sicherheits-Feature.

## 4. Designsystem „Tinte & Papier"

Zentral in einem `ScrybeTheme` (über die Environment verteilt), keine verstreuten Konstanten.

- **Flächen:** warmes Papier, radialer Cremeverlauf (`#F6EFE0 → #ECE3D0`).
- **Tinte (Text):** `#2A2733`.
- **Tinten-Akzent (Indigo):** `#4B4E8C` (Ringe, aktive Elemente).
- **Sepia (warm/sekundär):** `#8A6D3B` (Streak, Hinweise).
- **Status:** Erfolg/Ink-Grün `#5A7D4E`, Warnung `#B8862F`, Gefahr/Ink-Rot `#A23B46`.
- **Typo:** Serife für Display-Zahlen und die Wortmarke; System-Schrift für Fließtext. Dynamic Type wird unterstützt (keine fixen Punktgrößen als alleiniges Mittel).
- **Signature-Komponenten:** `InkRing` (Tinten-Fortschrittsring mit runder Kappe), `WeekStrip` (7 Balken), `StreakCalendar` (Punkte-Raster).

## 5. Screens

### 5.1 Heute (Pager-Seite 1, Held)
- Wortmarke „Scrybe" + feiner Strich, Label „Heute".
- **InkRing** mit zentrierter Schreibzeit (`1h 47m`) und Fortschritt zum **Tagesziel** (`73 % · Ziel 2 h`).
- Zeile darunter: **Streak** (`5 Tage`, sepia; ein Tag zählt nur, sobald das **Tagesziel** erreicht ist) + Live-Chip **„schreibt gerade"** (aktiv bei `writing=true`, also Modell-Proba ≥ 0.5).
- **WeekStrip** (7 Tage, heute hervorgehoben) als Brücke zu Trends.

### 5.2 Trends (Pager-Seite 2)
- „Diese Woche" mit Wochensumme + Vergleich zur Vorwoche (z. B. `9h 12m · ▲ 1h 04m`).
- **Wochen-Balkenchart** (7 Tage, heute hervorgehoben).
- **Streak-Kalender** (Habit-Punkte-Raster, heute markiert).

### 5.3 Verlauf (Pager-Seite 3)
- Chronologische Tagesliste/Kalender vergangener Tage mit jeweiliger Schreibzeit; Tippen öffnet den Tagesdetail (Stretches/Tag-Timeline, analog zum Web-`#focus`-Tab).
- **Datenbedarf:** mehr als 7 Tage → siehe §6 (Verlaufs-Quelle).

### 5.4 Admin (versteckt)
- **PIN-Gate** in Papier-Optik (Tinten-Tastatur, Schloss-Glyphe, Hinweis „geöffnet durch langes Drücken").
- **Admin-Panel** (Tinte & Papier), Abschnitte:
  1. **Recording-Health-Ampel** — `Gesund` / `Upload staut sich` / Fehler, mit Flags WS · DATA · WATCH. Grün-Bedingung: **`dataFlowing && pollFresh`** (WS-Status separat sichtbar, *nicht* Grün-Bedingung — der WS ist nur Kommando-Kanal, Daten fließen über HTTP).
  2. **Datenfluss** — `In Queue` · `Hochgeladen` · `Verworfen` + Backlog-Sparkline. Queue wächst → gelb; `Verworfen > 0` → rot mit ⚠ „Daten verloren". Quelle: `PhoneBridge.{queuedBatchCount, uploadedSampleCount, droppedBatchCount}`.
  3. **Verbindungen** — Server · iPhone-Bridge · Watch (Status-Punkt + Detail). **Keine AirPods.**
  4. **Session** — laufende Session (ID · Person · Laufzeit) + STOP (Ink-Rot) bzw. START.
  5. **Reparatur** — „Gepufferte Daten senden" / „Puffer verwerfen".
  6. **Protokoll** — letzte Ereignisse (nur bei Zustandswechsel geloggt, kein 1-Hz-Spam).
  7. **Einstellungen** — Server-IP, Motion-Config.

## 6. Datenquellen

- **Heute:** `GET /focus/today` (heutige Schreibsekunden + Stretches).
- **Live „schreibt gerade":** WebSocket `live_inference` (`writing`, `proba`, `today_writing_seconds`).
- **Woche/Trends:** `GET /focus/week` (7 Tage Buckets + Wochen-Max).
- **Verlauf + langer Streak (> 7 Tage):** neuer Server-Endpunkt `GET /focus/history?days=N` (der Server hat das `inference_log` bereits; Single Source of Truth). SwiftData-Cache optional als spätere Offline-Optimierung, nicht im ersten Wurf.
- **Tagesziel:** lokale Einstellung (`AppStorage`, Default 2 h).
- **Admin:** ausschließlich bestehende, gerade gehärtete Manager (`PhoneBridge`, `ServerCommandListener`, `RecordingHealthStore`, `IMUDataStore`) — keine neuen Server-Aufrufe.

## 7. SwiftUI-Architektur & Dateistruktur

`iPhoneView_v4.swift` (2008 Zeilen) wird aufgeteilt (Feature-Ordner):

```
Scrybe/
  ScrybeApp.swift            App-Entry
  RootPagerView.swift        TabView(.page): Today/Trends/History + Langdruck→Admin
  TodayView.swift
  TrendsView.swift
  HistoryView.swift
  Components/                InkRing, WeekStrip, StreakCalendar, LiveChip
  ScrybeTheme.swift          Tinte-&-Papier-Tokens (Environment)
Admin/
  AdminGateView.swift        PIN-Gate
  AdminPanelView.swift
  Sections/                  RecordingHealthCard, DataflowCard, ConnectionsCard,
                             SessionCard, RepairCard, SettingsCard, LogCard
Stores/
  FocusStore.swift           lädt /focus/* + WS-Live, @MainActor
  ScrybeSettings.swift       Tagesziel etc.
  (bestehend, wiederverwendet: PhoneBridge, ServerCommandListener,
   RecordingHealthStore, IMUDataStore)
Networking/
  FocusAPI.swift             /focus-Client (URLSession, async/await, Timeouts)
```

- Reine Logik (Streak, Tagesziel-%, „data flowing", Zeitformat) lebt in testbaren, view-freien Typen.
- Nebenläufigkeit: Stores `@MainActor`; die gehärteten Lock-/Main-Hop-Muster der bestehenden Manager bleiben.
- Re-Render-Disziplin: hochfrequente Zähler nicht in views ziehen, die nicht darauf reagieren müssen (Befund aus dem Review).

## 8. Zustände: leer / offline / Fehler

- **Erster Start (keine Daten):** ruhiger Onboarding-Zustand statt leerer Ring („Trag die Watch und fang an zu schreiben").
- **Server offline:** letzte bekannten/gecachten Werte + dezenter Offline-Hinweis; kein Hängen.
- **Keine Session / `rate_mismatch`:** Live-Chip „schreibt gerade" inaktiv; Admin zeigt den realen Zustand.

## 9. Tests (Swift Testing)

Erstmals ein Test-Target für reine Scrybe-Logik (kein Simulator nötig):
- Streak-Berechnung (aufeinanderfolgende Tage, an denen das Tagesziel erreicht wurde).
- Tagesziel-Prozent + Rundung.
- „data flowing" (Zähler-Anstieg in Zeitfenster) inkl. Baseline-Skip beim Start.
- Wochen-Aggregation + Zeitformat (`h:mm`).

## 10. Verifikations-Modell (ehrlich)

- Die **Optik** ist im Browser-Begleiter festgenagelt (Mockups bestätigt).
- **SwiftUI kann hier nicht gebaut/gerendert werden** (kein Xcode/SDK/Simulator). Umsetzung daher in kleinen, überprüfbaren Schritten: ich schreibe SwiftUI, **du baust & schickst Screenshots**; alternativ treibt der `ios-simulator`-Skill das in einer Xcode-Umgebung auf deiner Seite.
- Code-Qualität wird mit den installierten Skills geprüft (`swiftui-pro`, `swiftui-design-principles`, `*-accessibility-auditor`, `swiftui-performance-audit`) — **nach Session-Neustart** (Skills laden beim Start).

## 11. Entschieden (Review 2026-06-22)

1. **Verlaufs-Quelle:** neuer Server-Endpunkt `GET /focus/history` (Single Source of Truth); SwiftData-Cache optional später.
2. **Streak-Definition:** ein Tag zählt nur, wenn das **Tagesziel** erreicht wurde (Streak reißt bei Zielverfehlung).
3. **Migrationsweg:** Scrybe **parallel** neben der bestehenden `iPhoneView` aufbauen, am Ende den Root umschalten (App bleibt jederzeit lauffähig).
4. **Live-Chip:** leuchtet bei `writing=true` (Modell-Proba ≥ 0.5), konsistent mit Server/Recording-Health.

## 12. Entscheidungslog

- Struktur: **Scrybe vorne, Betrieb hinter Admin-Panel**.
- Kern: **ruhiges Tagesritual** (Held = heutige Schreibzeit + Ziel + Streak).
- Visuell: **Tinte & Papier (A)**; Signature = **Tinten-Ring**.
- Navigation: **horizontaler Pager** (Heute/Trends/Verlauf).
- Trends: **Wochen-Chart + Streak-Kalender**.
- Admin-Zugang: **Langdruck Wortmarke + PIN**; Admin-Page **im gleichen Stil**.
- Admin zeigt **Datenfluss** (Queue/Verworfen sichtbar, Ampel kippt bei Stau).
- **Keine AirPods** in Scrybe oder Admin.
- Verlauf via **`/focus/history`**-Endpunkt; Streak = **Tage mit erreichtem Tagesziel**; Migration **parallel → umschalten**; Live-Chip ab **Proba ≥ 0.5**.

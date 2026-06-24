# Passiver On-Device-Tracker-Modus (Watch → iPhone)

**Datum:** 2026-06-24
**Status:** Design abgenommen, Implementierung ausstehend
**Vorarbeit:** `reports/acc_only_ablation.md`, `models/rf_acc_only_live.joblib`,
`models/hmm_live.json`, `src/evaluation/hmm.py` (`OnlineForwardFilter`)

## 1. Ziel & Kontext

Der Schreib-Detektor läuft heute server-seitig: die Watch streamt aktiv die volle
IMU (`CMDeviceMotion`, Accel + Gyro) in einer `HKWorkoutSession` an das iPhone,
das iPhone POSTet an den FastAPI-Server, der Server inferiert und broadcastet das
Ergebnis zurück. Ziel ist ein **passiver, server-freier Ganztags-Tracker**, der
ohne aktive Aufnahme-Session und ohne Server auf dem Gerät läuft: die Watch
zeichnet via `CMSensorRecorder` batteriesparend im Hintergrund auf, das iPhone
inferiert lokal und füllt die Scrybe-Ringe.

**Machbarkeit ist belegt** (`reports/acc_only_ablation.md`):
- `CMSensorRecorder` liefert laut Apple-Doc ausschließlich Accelerometer, kein
  Gyroskop. Das Headline-Modell nutzt 41 der 88 Features aus den Gyro-Achsen.
- Gepaarte LOSO-Ablation (N=15): der Gyro-Verzicht kostet ~1.9 pp roh@1s, am
  HMM-Live-Pfad nur noch **~1 pp** (full+HMM 0.902 vs. acc-only+HMM 0.893).
- Der Roh-Accel-Abschlag (`CMSensorRecorder` liefert *rohe* Gesamtbeschleunigung,
  nicht `userAcceleration`) wurde aus Modern-Sessions rekonstruiert gemessen und
  ist **≈ 0** (`scripts/ml/passive_raw_accel_loso.py`).
- Das Deployment-Modell (**30 gravity-invariante Features**, pooled Z-Score) ist
  trainiert: `models/rf_acc_only_live.joblib` — deployt ohne Filter und ohne
  Roh-vs-userAccel-Diskrepanz (Begründung §9).

**Harte Randbedingung:** Das bestehende **Studiendesign darf nicht beschädigt
werden**. Die aktive Datenerfassung (full-IMU + Pen-Ground-Truth + Server + Study
Mode) bleibt die Grundlage der laufenden Forschung. Der Passiv-Tracker ist die
spätere Ablösung; bis dahin koexistieren beide, und ein Interlock verhindert, dass
ein Studien-Gerät versehentlich in den Tracker-Modus rutscht.

## 2. Scope / Nicht-Ziele

- **Retrospektiv, nicht live.** `CMSensorRecorder` ist eine Aufzeichnungs-API
  (loggen, später abholen), kein Live-Stream. Tracker-Modus hat **keine
  „schreibt gerade"-Live-Pille**; die Ringe füllen sich rückwirkend per
  Background-Verarbeitung und beim App-Öffnen. Die Live-Pille bleibt dem
  Collection-Pfad vorbehalten.
- **iPhone-seitige Inferenz**, nicht Watch-seitig (Watch = nur Sensorik; Modell
  zentral aktualisierbar; kein zusätzlicher Watch-Compute/Akku).
- **JSON-Tree-Export** statt CoreML (transparent + parity-prüfbar; coremltools ist
  nicht installiert und der sklearn-Converter hinkt der sklearn-Version 1.7.2
  hinterher).
- **Kein Embedded Python.** Auf iOS unpraktikabel.
- Beide Modi laufen **nie gleichzeitig** (exklusiv).

## 3. Modus-Modell & Interlock

**Single source of truth:** `AppMode` enum `{ .collection, .tracker }`, persistiert
in `ScrybeSettings` als `scrybe.appMode` (`@AppStorage`, iPhone). Der Wert wird über
das bestehende `watchPayload` (`ServerCommandListener.swift:235`) an die Watch
gespiegelt, damit beide Seiten denselben Modus kennen.

**Verhalten je Modus (strikt entkoppelt):**

| | Collection (Default, heute) | Tracker (neu, passiv) |
|---|---|---|
| Watch | aktives `CMDeviceMotion` in Workout-Session, streamt auf Server-Kommando | `CMSensorRecorder` passiv accel-only; aktives Streaming **aus** |
| iPhone | POST /watch → Server, WS/`/focus`-Polling | Background-Batch-Pull → On-Device-Inferenz; **Server komplett aus dem Loop** |
| UI-Quelle | `liveInference` vom Server | lokaler `FocusStore` aus On-Device-Inferenz |

Der Collection-Pfad bleibt **unveränderter Code**. Tracker ist additiv.

**Interlock — vier unabhängige Garantien, je an einem konkreten Mechanismus:**

1. **Harter Block (Aktivierung):** Der Tracker-Toggle ist deaktiviert/verweigert
   mit Hinweis, solange eine Aufnahme-Session aktiv ist. `ServerCommandListener`
   kennt den Session-Zustand (Start/Stop laufen über ihn). Umschalten mitten in
   einer Studie ist unmöglich.
2. **Auto-Erzwingung (Session-Start):** Trifft ein `start`-Kommando vom Server ein
   (`ServerCommandListener.handle`, ca. Zeile 151), wird `appMode = .collection`
   erzwungen — war Tracker an, kippt er zurück + Warn-Log/Toast. Da Sessions
   server-getrieben starten, ist das der natürliche Hook.
3. **Sichtbarer Indikator:** Dauerhaft sichtbarer Modus-Status — dezenter,
   semantisch gefärbter Marker (System-Farben, eine Glyphe; `swiftui-design-
   principles`) im Scrybe-Header/Footer **und** prominent im Admin-Panel-Header.
4. **Fail-safe Default:** `@AppStorage`-Default ist `.collection`. Frische
   Installation, Reset, Update, korrupter/unbekannter Wert → immer Collection. In
   Tracker kommt man nur durch eine explizite Admin-Aktion hinter dem PIN.

**State-Machine:**
- `collection → tracker`: nur via Admin-Toggle, nur wenn keine Session aktiv (G1),
  hinter PIN.
- `tracker → collection`: via Admin-Toggle jederzeit, **oder** auto-erzwungen bei
  Session-Start (G2).
- Cold start / Fehler / Ambiguität → `collection` (G4).
- Jeder Modus-Wechsel pusht den neuen Wert an die Watch (Capture-Pfad umschalten)
  und cleared den jeweils anderen Puffer + `reset()` des HMM (kein Daten-Bleed).

## 4. Komponenten

**N** = neu, **M** = Änderung an Bestehendem. Jede Unit hat einen Zweck, eine klare
Schnittstelle, benannte Abhängigkeiten.

### Python-Fundament (dieses Repo, hier verifizierbar)
- **N `scripts/ml/export_rf_json.py`** — serialisiert `rf_acc_only_live.joblib` →
  `models/rf_acc_only_live.json` (pro Baum: feature_idx / threshold / children /
  leaf-class-1-proba; + Feature-Reihenfolge; + pooled µ/σ; + Metadaten). **Floats
  voll round-trip-fähig** serialisieren (`float.hex()` bzw. `repr`/`%.17g`) —
  gerundete RF-Thresholds oder µ/σ schicken den Swift-Baum an einem Knoten in den
  *falschen* Ast (Decision-Flip → komplett anderes Ergebnis). Round-Trip-Test im
  Export selbst.
- **N `PyReferenceEvaluator` + Paritätstest** — pure-Python-Evaluator, der aus dem
  JSON sklearns `predict_proba` reproduziert (assert max|Δ| ≈ 0 — bei voller
  Float-Präzision exakt). Die Spezifikation, die der Swift-Port treffen muss.
- **N `scripts/ml/dump_golden_vectors.py`** — N bekannte Fenster als Fixture:
  roh-Accel-Samples → erwartete 30 gravity-invariante Features → erwartete
  `proba_raw` → erwarteter HMM-Posterior (**kein Filter** — Features sind invariant).
  Ebenfalls **volle Float-Präzision** (sonst falsche Parität-Rotfärbung). JSON, wandert
  ins `ScrybeTests`-Target.
- **N `scripts/ml/validate_invariant_deploy.py`** — verifiziert die (b)-Kernannahme:
  die 30 Features sind auf roher Gesamtbeschleunigung == userAccel. Baut sie auf den
  Modern-Sessions beidseitig (userAccel vs. rekonstruierte Roh-Accel) und vergleicht
  Decision-Scale-Agreement — erwartet ~identisch (Rest = Within-Window-Gravity-Rotation,
  zweiter Ordnung).

### Watch (watchOS)
- **N `PassiveRecorder`** — kapselt `CMSensorRecorder`: Authorization, **rollierendes
  Re-Arming**. `recordAccelerometer(forDuration:)` erlaubt **max. 12 h pro Aufruf**
  (Apple-Limit) → in **Sub-12-h-Chunks** aufnehmen, vor Ablauf neu armen, mit
  *leichter Überlappung an der Naht* (sonst Gap). Re-Armen läuft im
  `WKApplicationRefreshBackgroundTask`-Fenster; die Wake-Kadenz deutlich unter 12 h
  als Sicherheitsmarge. **Pull-Kadenz ~stündlich** (kleine Dateien → kein iPhone-OOM,
  siehe R-Jetsam). Batch-Abruf seit `identifier`-Cursor. *Interface:* `start()` /
  `stop()` / `pullBatches(sinceIdentifier:) -> [AccelSample]` / `rearmIfNeeded()` ·
  *Dep:* CoreMotion, WatchKit-Background-Refresh, persistierter Cursor.
- **N `AxisCanonicalizer`** — `CMSensorRecorder` liefert **rohe Hardware-Achsen**,
  ohne die Wrist-/Crown-Korrektur, die die Sensor-Fusion in CMDeviceMotion ggf.
  vornimmt. Trägt der Nutzer „Crown links" statt der Trainings-Konvention, sind die
  physischen X/Y um 180° gedreht (×−1) → das achsen-spezifische RF-Modell (mean/min/
  max je Achse) versagt. Fix: `WKInterfaceDevice.current().wristLocation` +
  `.crownOrientation` abfragen und X/Y *am Source* (vor dem Batch-Write) auf die
  Trainings-Konvention kanonisieren. **Verifikation (Phase 0/früh):** die Trainings-
  Orientierungs-Konvention bestimmen *und* on-device prüfen, ob CMDeviceMotion- und
  `CMSensorRecorder`-Achsen tatsächlich auseinanderlaufen (simultane Kurzaufnahme,
  Achsen vergleichen) — die „CMDeviceMotion korrigiert automatisch"-Prämisse ist
  *nicht* gesichert; die Kanonisierung ist die Absicherung unabhängig vom Mechanismus.
- **M `MotionManager`** — Modus-Branch in `handleCommand` (ca. Zeile 808):
  `.collection` = heutiger aktiver Pfad (unverändert); `.tracker` = aktives
  Streaming aus, `PassiveRecorder` an. Gepullte Batches werden auf der Watch in eine
  **temporäre Binärdatei** geschrieben (Array-of-Structs via `Data`, volle
  Float-Präzision — keine Text-Serialisierung) und via **`WCSession.transferFile()`**
  ans iPhone geschickt (getaggt `mode: tracker`) — **nicht** `transferUserInfo`
  (Payload-Limit sprengt schon Minuten an 50 Hz). `transferFile` ist hintergrund-
  zuverlässig und weckt die iPhone-App für die Inferenz (siehe `InferenceTrigger`).
  **Temp-File-Cleanup zwingend:** `session(_:didFinish:error:)` löscht die eigene
  Temp-Datei rigoros nach Abschluss (die Watch hat wenig Speicher; ohne Cleanup
  Disk-full-Crash in Tagen). Fehlgeschlagene Transfers werden für Retry behalten,
  aber **gebounded** (harter Cap auf den Temp-Footprint), nicht unbegrenzt akkumuliert.
- **N `WritingTimeComplication`** — aktive Watch-Face-Complication (minimal, z. B.
  App-Glyph oder Schreibzeit-Kurzwert). **Betrieblich zwingend für 24/7:** watchOS
  drosselt das Background-Budget einer App ohne aktive Complication bis auf null →
  `WKApplicationRefreshBackgroundTask` feuert nicht mehr → 12-h-Aufnahme läuft ohne
  Re-Arm ab → echte Datenlücken. Mit Complication = „high priority" + garantiertes
  Budget (~4 Wake-ups/h). Teilnehmer-Onboarding instruiert das Platzieren aufs
  Zifferblatt; fehlt sie, **erkennt und meldet** die App es (statt still Lücken zu
  produzieren).

### iPhone — Inferenz-Kern (paritäts-kritisch, alles neu)
- **N `AccelFeatureExtractor`** — portiert die **30 gravity-invarianten Features**
  aus `src/features/windows.py::_window_features` bit-identisch: per-Achse std/range,
  rFFT (DC-Removal: dom_freq/centroid/entropy/Band 3–8 Hz), ZCR, Accel-Jerk,
  Accel-Korrelationen. **Kein High-Pass-Filter nötig** — diese Features sind
  schwerkraft-offset-*invariant*, also auf roher Gesamtbeschleunigung ==
  userAcceleration (by construction; gedroppt sind mean/min/max/rms je Achse +
  acc_mag, weil schwerkraft-dominiert). *Interface:* `features(window) -> [Double]`
  (Reihenfolge = `feature_cols` des Modells, 30) · *Dep:* vDSP/Accelerate-FFT.
- **N `RFEvaluator`** — lädt `rf_acc_only_live.json`, pooled-Z-Score, evaluiert alle
  Bäume → Klasse-1-Proba (Mittel der Leaf-Probas). *Interface:* `proba(features) ->
  Double` · *Dep:* JSON-Modell.
- **N `OnlineForwardFilter`** — Port von `src/evaluation/hmm.py::OnlineForwardFilter`
  (~20 Z.): `step(proba) -> Posterior`, `reset()`. *Dep:* `hmm_live.json`
  (2×2-Übergangsmatrix + Prior).
- **N `InferenceEngine`** — Orchestrator: roh-Accel → 1-s-Fenster (0.5 s Stride, wie
  Training) → Extractor (30 invariante Features) → RF → HMM → Schreib-Entscheidung →
  Schreibzeit-Buckets → `FocusStore`. **Kein Filter davor** — die Features sind
  schwerkraft-invariant. *Interface:* `process(samples)` (idempotent), `reset()` ·
  *Dep:* die drei oben + Dedup. Kennt weder `CMSensorRecorder` noch den Modus —
  allein gegen die Golden-Vektoren testbar.
- **N `ResumableState`** — der vollständige, persistierte Resume-Zustand, damit die
  Engine einen App-Kill zwischen Hintergrund-Läufen übersteht: `{
  lastProcessedIdentifier, sampleTail (~letzte 1 s), hmmAlpha, partialStretch }`.
  **Notwendig, nicht nur sauber:** die HMM-Memory ist ~16 s und ließe sich aus einem
  1-s-Overlap *nicht* rekonstruieren. *Dep:* File/UserDefaults.

### iPhone — Capture-Plumbing & Modus
- **N `PassiveBatchStore`** — empfängt Watch-Batches, Dedup/Idempotenz über den
  persistierten `lastProcessedIdentifier` (`CMRecordedAccelerometerData.identifier`,
  UInt64, garantiert streng monoton — NTP/DST/Drift-immun; der Timestamp bleibt für
  Windowing + Gap-Detection, *getrennte* Rolle). **Streaming-Read, nie alles in den
  RAM:** die empfangene Binärdatei wird **chunk-für-chunk** gelesen (memory-mapped
  `Data`), gefenstert, inferiert und der Chunk-Speicher sofort freigegeben — ein
  ganzer 12-h-Batch als Array im RAM würde das Jetsam-Background-Limit (~50 MB)
  sprengen und die App ohne Fehlermeldung killen (siehe R-Jetsam). **Data Protection:**
  alle im Hintergrund beschriebenen Stores (Cursor, `ResumableState`, `FocusStore`)
  laufen unter `NSFileProtectionCompleteUntilFirstUserAuthentication` (siehe
  R-DataProtection). *Interface:* `ingest(fileURL) -> [AccelSample]` (gestreamt, neu,
  dedupliziert).
- **N `InferenceTrigger` (WCSession-getrieben)** — der **primäre** Hintergrund-
  Trigger ist der `WCSessionDelegate.session(_:didReceiveFile:)`-Callback: iOS weckt
  die App bei Datenankunft und gibt garantierte (knappe) Hintergrundzeit. Darin:
  Datei → `PassiveBatchStore.ingest` → `InferenceEngine.process` → FocusStore,
  *chunked* und via `beginBackgroundTask` verlängert. **Strikt serielle FIFO-Queue**
  (`DispatchQueue(label:qos:.background)`): bei einem Backlog feuert WCSession die
  aufgestauten Dateien schnell/parallel — Datei B darf erst inferiert werden, wenn A
  ihren `ResumableState` (HMM/Cursor) persistiert hat, sonst korrumpieren parallele
  Callbacks den Zustand (siehe R-Serial). **Activation-Gate:** Transfers/Empfang erst
  nach `session(_:activationDidCompleteWith:)` == `.activated` (async; sonst landet
  `transferFile` im Nichts — siehe R-Activation). `BGAppRefreshTask` bleibt nur als
  **Fallback-Catch-up**; `BGProcessing` ist zu selten für den Primärpfad. Foreground:
  voll aufholen. *Dep:* `InferenceEngine`, `PassiveBatchStore`, WatchConnectivity,
  BackgroundTasks.
- **M `AppModeStore` (in `ScrybeSettings`)** — `AppMode`-Enum + `scrybe.appMode`
  (Default `.collection`, G4), `requestTrackerMode()` (verweigert bei aktiver
  Session, G1), `forceCollection(reason:)` (G2).
- **N `ModeToggle` (in `SettingsCard`)** — Admin-Toggle hinter PIN, deaktiviert mit
  Hinweis bei aktiver Session (G1). Native `Toggle`/`Picker`, System-Farben.
- **N `ModeIndicator`** — dauerhaft sichtbarer Modus-Badge (G3), Scrybe-Header/
  Footer + Admin-Header.
- **M Wiring** — `ServerCommandListener.handle("start")` → `forceCollection` (G2) +
  `mode` in `watchPayload`; `FocusStore.start` → in Tracker-Modus Server-Polling
  überspringen, lokale Engine konsumieren.

## 5. Datenfluss

**Collection-Modus — unverändert:**
```
Watch (CMDeviceMotion 50 Hz, Workout-Session) → WatchConnectivity → iPhone PhoneBridge
  → POST /watch → Server-Inferenz → WS live_inference + /focus → Scrybe-UI
```

**Tracker-Modus — neu, server-frei:**
```
Watch: CMSensorRecorder loggt accel passiv (App darf suspendiert/beendet sein),
       Re-Arm in Sub-12-h-Chunks via WKApplicationRefreshBackgroundTask
  → PassiveRecorder.pullBatches(sinceIdentifier:) → temporäre Binärdatei
  → WCSession.transferFile() (getaggt mode:tracker; NICHT in die Upload-Queue)
  → iOS weckt iPhone-App: WCSessionDelegate.didReceiveFile  [garantierte BG-Zeit]
  → iPhone PassiveBatchStore  [Dedup gegen lastProcessedIdentifier]
  → InferenceEngine (Resume-State restored): roh-Accel → kontinuierl. Stream
       → 1-s-Fenster (0.5 s Stride) → 30 gravity-invariante Features → RF(JSON)
       → OnlineForwardFilter → Schreib-Entscheidung → Schreibzeit-Buckets
       → FocusStore → Ringe füllen sich rückwirkend; Resume-State persistiert
```

**Dedup / Idempotenz** (mirror der server-seitigen `inference_log`+`/focus`-Semantik):
- Jedes `CMRecordedAccelerometerData` trägt einen `identifier` (UInt64, garantiert
  streng monoton). `PassiveBatchStore` persistiert `lastProcessedIdentifier` —
  drift-/NTP-/DST-immun, anders als ein Date-Timestamp. (Der Timestamp wird separat
  fürs Windowing + die Gap-Detection genutzt, nicht fürs Dedup.)
- Abruf immer `sinceIdentifier: cursor`; beim Ingest werden Samples
  `identifier ≤ lastProcessedIdentifier` verworfen → überlappende/doppelte Batches
  zählen nie doppelt.
- Die Engine schreibt **pro Zeit-Bucket** (per-window Schreibzustand, keyed by
  Bucket-Startzeit) per **Upsert** — Gesamt-Schreibzeit = Summe über Buckets.
  Re-Processing überschreibt identisch statt zu addieren → idempotent. Der Cursor
  rückt erst nach erfolgreichem Persist vor; ein Crash mitten drin re-prozessiert
  denselben Bucket folgenlos.

**Drei Subtilitäten:**
1. **Keine Batch-Grenzen-Naht.** Gefenstert wird der dedup-rekonstruierte
   *kontinuierliche* Sample-Stream, nicht pro Batch — ein Fenster darf zwei
   übertragene Batches überspannen.
2. **Prozess-Persistenz über App-Kills.** Der Stream ist nur in den *Daten*
   kontinuierlich; der *Prozess* wird zwischen Hintergrund-Läufen von iOS beendet und
   verliert den RAM-Zustand. Deshalb persistiert die Engine den vollen `ResumableState`
   `{lastProcessedIdentifier, sampleTail, hmmAlpha, partialStretch}` und stellt ihn
   beim nächsten Wake wieder her. Notwendig, nicht nur sauber: die HMM-Memory ist ~16 s
   und ließe sich aus einem 1-s-Overlap nicht rekonstruieren.
3. **HMM-Zustand & Reset.** Der `OnlineForwardFilter` läuft über kontinuierliche
   Samples (resume-restored) einfach weiter; nur bei einer echten Zeitlücke (Watch
   aus, Aufnahme pausiert, Sprung > Schwelle) macht die Engine `reset()` (identisch
   zur Live-Inferenz-Reset-Regel).

## 6. Fehlerbehandlung & Edge-Cases

Alle fail-safe, nie stiller Datenverlust:
- **iPhone-Background.** Primär-Trigger ist der `didReceiveFile`-Wake bei Datenankunft
  (zuverlässiger als BGTasks). Feuert er mal nicht (App vom Nutzer terminiert o. ä.),
  rekonziliert der App-Open-Catch-up vollständig. Ringe „meist aktuell", beim Öffnen exakt.
- **Watch re-armt nicht rechtzeitig (12-h-Limit).** Bekommt die Watch in einem
  12-h-Fenster keine Background-Runtime, stoppt `CMSensorRecorder` → Gap bis zum
  nächsten Re-Arm. Mitigation: Sub-12-h-Chunks mit Marge + Überlappung; die Lücke ist
  als echte Idle-Zeit zu behandeln (HMM-`reset()`), nicht zu interpolieren.
- **CMSensorRecorder-Auth verweigert** → Tracker kann nicht erfassen; Admin +
  Modus-Indikator zeigen es klar, kein Crash, UI sagt „Bewegung freigeben".
- **Modell-JSON fehlt/lädt nicht** → Inferenz aus, explizit angezeigt (nicht still
  0 Schreibzeit zeigen — das läse sich als „nichts geschrieben").
- **`hmm_live.json` fehlt** → graceful auf `proba ≥ 0.5` (wie server-seitig).
- **CMSensorRecorder-Retention** (OS hält ~3 Tage) → wer zu lange nicht pullt,
  verliert die ältesten Daten = Lücke. Für einen Tagestracker akzeptabel; häufig
  genug pullen. Dokumentierter Caveat.
- **Watch-seitige Pull-Latenz.** watchOS-Background-Runtime ist limitiert — die
  Watch pullt + transferiert, wenn das Watch-App-Target läuft (Foreground oder
  `WKApplicationRefreshBackgroundTask`-Fenster). Kombiniert mit der 3-Tage-Retention
  geht nichts verloren, es kommt nur verzögert an („eventually current"). Der
  iPhone-Catch-up rekonziliert beim nächsten Lauf vollständig.
- **Modus-Wechsel / Zeitlücke** → anderen Puffer leeren + HMM `reset()`.

### Plattform-Robustheit (Phase 2/3 — je ein Build-Phasen-Ticket)

Die fiesen iOS/watchOS-Edge-Cases, die im Unit-Test grün sind und erst in freier
Wildbahn crashen. Jeder Punkt wird ein eigenes Ticket der zugehörigen Phase.

- **R-DataProtection (Phase 2).** iOS weckt das iPhone oft *gesperrt* (in der Tasche).
  Default-`NSFileProtectionComplete` macht Dateien im gesperrten Zustand unbeschreibbar
  → Schreiben in Cursor/`ResumableState`/`FocusStore` crasht mit IOError. Fix: diese
  Stores explizit `NSFileProtectionCompleteUntilFirstUserAuthentication`.
- **R-Activation (Phase 2).** `WCSession.activate()` ist async. `transferFile()` direkt
  danach landet im Nichts (Status `.activating`). Fix: Transfer/Empfang erst nach
  `session(_:activationDidCompleteWith:)` == `.activated` (Wrapper mit Completion-Queue),
  beide Seiten.
- **R-Serial (Phase 2).** Nach Reconnect feuert WCSession den Backlog schnell/parallel.
  Parallele `didReceiveFile`-Callbacks korrumpieren HMM-State + Cursor. Fix: strikt
  serielle FIFO-Queue, Datei B erst nach Persist von A.
- **R-Jetsam (Phase 2).** Background-RAM-Limit ~50 MB; ein 12-h-Batch komplett in ein
  Array geladen → stiller OOM-Kill. Fix: ~stündliche kleine Pulls (Watch) + Streaming-
  Read chunk-für-chunk (iPhone), Speicher sofort freigeben.
- **R-DiskFull (Phase 2).** `transferFile` braucht Temp-Dateien auf der Watch (wenig
  Speicher); ohne Cleanup via `session(_:didFinish:error:)` → Disk-full-Crash in Tagen.
  Fix: rigoroses Löschen nach Abschluss, fehlgeschlagene Transfers gebounded.
- **R-Axis (Phase 2, Validierung Phase 0).** Rohe Hardware-Achsen ohne Wrist-/Crown-
  Korrektur → bei „Crown links" X/Y invertiert → achsen-spezifisches RF versagt. Fix:
  `AxisCanonicalizer` (siehe Komponente).
- **R-Complication (Phase 2/3).** Ohne aktive Watch-Face-Complication drosselt watchOS
  das Background-Budget auf null → 12-h-Aufnahme läuft ohne Re-Arm ab → permanente
  Lücken. Fix: `WritingTimeComplication` + Onboarding-Instruktion + Fehlt-Erkennung.
- **R-LowPower (Phase 3).** Stromsparmodus (Watch *oder* iPhone) setzt Background-
  Refresh + WCSession-Wakeups hart aus → Aufnahme läuft ab, permanente Lücken. Kein
  Code-Fix möglich; `ProcessInfo.processInfo.isLowPowerModeEnabled` abfragen und im
  Tracker-Modus deutlich warnen („funktioniert nicht zuverlässig im Stromsparmodus").

## 7. Tests

- **Golden-Vektor-Parität (Kern):** Fixture (roh-Accel → 30 gravity-invariante Features
  → proba_raw → HMM-Posterior) im `ScrybeTests`-Target; Swift-Tests asserten
  **Extractor / RF / HMM / Engine** gegen das Fixture. **Test-Form (ehrlich statt naiv „bit-identisch"):**
  volle Float-Präzision im Fixture eliminiert die *vermeidbare* Divergenz; echte
  Bit-Identität über numpy↔vDSP-FFT ist *nicht* garantiert (ULP-Differenzen durch
  andere Summationsreihenfolge). Daher: **tight Feature-ε** (fängt echte Bugs) **+
  exakte Übereinstimmung der binären Schreib-Entscheidung** (kein Decision-Flip — das,
  was zählt). Fängt die Sort-Stability/Capture-Clock-Bug-Klasse auf der Swift-Seite —
  der Grund für JSON-Trees + Referenz-Evaluator.
- **Python-Parität:** `PyReferenceEvaluator` vs. sklearn `predict_proba` (≈0) → in
  der bestehenden `pytest`-Suite.
- **Dedup/Idempotenz:** überlappende/doppelte Batches → identische Schreibzeit wie
  ein sauberer Durchlauf; Re-Process ab Cursor → kein Doppelzählen.
- **Interlock-Unit-Tests:** `AppModeStore`-State-Machine — G1 (verweigert Tracker
  bei aktiver Session), G2 (erzwingt Collection bei Session-Start), G4 (Default
  Collection bei unset/korrupt). Reine Logik, unit-testbar.
- **Hardware-Loops manuell** (CMSensorRecorder, BG-Tasks, WC-Transfer) —
  gerätegebunden, konsistent mit der bestehenden „manual smoke"-Haltung.

## 8. Build-Phasen (je ein eigener Implementierungsplan)

- **Phase 0 — Python-Fundament** *(hier voll verifizierbar)*: Deployment-Modell auf
  30 gravity-invariante Features trainiert (✅); + **Invarianz-Validierung** (die 30
  Features sind auf roher Gesamtbeschleunigung == userAccel — auf den Modern-Sessions
  gegen die echte userAccel decision-scale verifiziert) + JSON-Export + Referenz-
  Evaluator + Paritätstest + Golden-Vektor-Dump. Landet zuerst, grün, vor jeglichem Swift.
- **Phase 1 — iPhone-Inferenz-Kern** *(Swift, gerätegeprüft)*: Extractor (30 invariante
  Features) + RF + HMM + Engine + ResumableState, getrieben nur von den Golden-Vektoren
  (keine Sensoren, kein Filter). Beweist On-Device-Parität + Resume isoliert.
- **Phase 2 — Passive Erfassung**: PassiveRecorder (Watch, `CMSensorRecorder` +
  12-h-Re-Arm) + `AxisCanonicalizer` + `WCSession.transferFile`-Transport +
  `didReceiveFile`-Trigger + PassiveBatchStore/Identifier-Dedup + ResumableState-
  Persistenz (BGAppRefresh-Fallback). **Plus Robustheits-Tickets** R-DataProtection,
  R-Activation, R-Serial, R-Jetsam, R-DiskFull, R-Axis, R-Complication (siehe §6).
  Verdrahtet echte Daten in die bewiesene Engine.
- **Phase 3 — Modus & Interlock**: AppModeStore + ModeToggle + ModeIndicator +
  Wiring + die vier Garantien. **Plus** R-LowPower-Warnhinweis + R-Complication-
  Onboarding/Fehlt-Erkennung (siehe §6).

Phase 0 unblockt alles und ist hier abschließbar; Phasen 1–3 werden inkrementell aufs
Gerät gebaut und verifiziert.

## 9. Annahmen

- Tracker-Modus ist **vollständig server-unabhängig** (offline-fähig); kein
  hybrider „Server wenn verfügbar"-Pfad (YAGNI).
- **Betriebliche Voraussetzungen für zuverlässiges 24/7-Tracking:** aktive
  Watch-Face-Complication (Background-Budget, R-Complication), kein Stromsparmodus
  (R-LowPower), Motion-Authorization erteilt. Fehlt eine, degradiert der Tracker zu
  „eventually/lückenhaft" — die App erkennt und meldet das, statt still falsche Zahlen
  zu zeigen.
- **Trainings-Orientierungs-Konvention** (Wrist/Crown) ist in Phase 0 zu bestimmen und
  ist das Ziel der `AxisCanonicalizer`-Normalisierung (R-Axis). Default-Annahme: Left
  Wrist / Crown Right — vor dem Swift-Port bestätigen.
- **Roh-Accel-Deployment GELÖST via gravity-invariante Features (Pivot weg vom High-Pass).**
  Der ≈0-Roh-Accel-Befund (`passive_raw_accel_loso.py`) lief unter *per-session* Z-Score;
  das Deployment-Modell nutzt *pooled* µ/σ → die offset-sensitiven Features (mean/min/max/
  rms je Achse + acc_mag) trügen bei Roh-Accel einen Schwerkraft-Offset. Der ursprünglich
  geplante Komplementär-High-Pass (`GravityHighPass`) wurde **verworfen**: die
  Decision-Scale-Validierung zeigte **4–7 pp systematische Kosten** — der HMM *verstärkt*
  den Fehler, statt ihn zu glätten (zeitlich korreliert; der 1-Pol-Filter ist eine zu grobe
  Schwerkraft-Schätzung ggü. CoreMotions Gyro-Fusion). **Stattdessen (b):** das Modell
  trainiert nur auf den **30 schwerkraft-offset-invarianten Features**
  (std/range/FFT-DC-removed/zcr/jerk/corr), die auf roher Gesamtbeschleunigung ==
  userAccel sind (by construction). Kein Filter, null Diskrepanz, volle N=15-Daten.
  LOSO-Kosten ggü. den vollen 47 acc-only: **+0.4 pp (n.s.)**; per-fold nur P09 −1.6 pp
  (Soft-Writer-Amplitude, lag in den gedroppten Features), P17 +1.1 pp (Offset-Features
  sind ein Personalisierungs-, kein Generalisierungs-Signal), kein Kollaps. (a)
  Roh-Accel-Retraining wäre schlechter: nur N=5 Modern + lernt Orientierung.
- `CMSensorRecorder` zeichnet ~50 Hz auf → Raten-Match zum 50-Hz-Legacy-Modell.
- Die HMM-Parameter (`hmm_live.json`) sind modell-agnostisch (Übergangsmatrix =
  Label-Dynamik) und gelten auch für das acc-only-Modell; bei Bedarf später aus
  acc-only-OOF nachgezogen.
- Background-Aktualität ist „eventually current" (iOS-opportunistisch), exakt beim
  App-Öffnen — bewusst akzeptiert für die Passiv-/Akku-Ziele.

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
- Das acc-only-Deployment-Modell (47 Features, pooled Z-Score eingebacken) ist
  trainiert: `models/rf_acc_only_live.joblib`.

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
  leaf-class-1-proba; + Feature-Reihenfolge; + pooled µ/σ; + Metadaten).
- **N `PyReferenceEvaluator` + Paritätstest** — pure-Python-Evaluator, der aus dem
  JSON sklearns `predict_proba` bit-genau reproduziert (assert max|Δ| ≈ 0). Die
  Spezifikation, die der Swift-Port treffen muss.
- **N `scripts/ml/dump_golden_vectors.py`** — N bekannte Fenster als Fixture:
  roh-Accel-Samples → erwartete 47 Features → erwartete `proba_raw` → erwarteter
  HMM-Posterior. JSON, wandert ins `ScrybeTests`-Target.

### Watch (watchOS)
- **N `PassiveRecorder`** — kapselt `CMSensorRecorder`: Authorization, rollierendes
  `recordAccelerometer(forDuration:)`, Batch-Abruf seit Cursor.
  *Interface:* `start()` / `stop()` / `pullBatches(since:) -> [AccelSample]` ·
  *Dep:* CoreMotion, persistierter Cursor.
- **M `MotionManager`** — Modus-Branch in `handleCommand` (ca. Zeile 808):
  `.collection` = heutiger aktiver Pfad (unverändert); `.tracker` = aktives
  Streaming aus, `PassiveRecorder` an, Batches via bestehende WatchConnectivity-
  Bridge ans iPhone (getaggt `mode: tracker`).

### iPhone — Inferenz-Kern (paritäts-kritisch, alles neu)
- **N `AccelFeatureExtractor`** — portiert die 47 acc-only-Features aus
  `src/features/windows.py::_window_features` bit-identisch (per-axis Stats; rFFT
  mit DC-Removal für Centroid/Entropy/Band 3–8 Hz; ZCR; Accel-Jerk; Accel-
  Magnitude; Accel-Korrelationen). *Interface:* `features(window) -> [Double]`
  (Reihenfolge = `feature_cols` des Modells) · *Dep:* vDSP/Accelerate-FFT.
- **N `RFEvaluator`** — lädt `rf_acc_only_live.json`, pooled-Z-Score, evaluiert alle
  Bäume → Klasse-1-Proba (Mittel der Leaf-Probas). *Interface:* `proba(features) ->
  Double` · *Dep:* JSON-Modell.
- **N `OnlineForwardFilter`** — Port von `src/evaluation/hmm.py::OnlineForwardFilter`
  (~20 Z.): `step(proba) -> Posterior`, `reset()`. *Dep:* `hmm_live.json`
  (2×2-Übergangsmatrix + Prior).
- **N `InferenceEngine`** — Orchestrator: Accel-Samples → 1-s-Fenster (0.5 s Stride,
  wie Training) → Extractor → RF → HMM → Schreib-Entscheidung → Schreibzeit-Buckets
  → `FocusStore`. *Interface:* `process(samples)` (idempotent), `reset()` · *Dep:*
  die drei oben + Dedup. Kennt weder `CMSensorRecorder` noch den Modus — allein
  gegen die Golden-Vektoren testbar.

### iPhone — Capture-Plumbing & Modus
- **N `PassiveBatchStore`** — empfängt Watch-Batches, timestamp-basiertes
  Dedup/Idempotenz, persistierter `lastProcessedTimestamp`-Cursor. *Interface:*
  `ingest(batch) -> [AccelSample]` (neu, dedupliziert).
- **N `BackgroundScheduler`** — registriert `BGAppRefreshTask`/`BGProcessingTask`;
  bei Wake: Batches verarbeiten → FocusStore → neu planen; bei Foreground: voll
  aufholen. *Dep:* `InferenceEngine`, `PassiveBatchStore`, BackgroundTasks.
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
Watch: CMSensorRecorder loggt accel passiv (App darf suspendiert/beendet sein)
  → PassiveRecorder.pullBatches(since: cursor)  [bei Watch-Background-Runtime]
  → WatchConnectivity (bestehende Bridge, getaggt mode:tracker; NICHT in die Upload-Queue)
  → iPhone PassiveBatchStore  [Timestamp-Dedup gegen lastProcessed-Cursor]
  → BackgroundScheduler (BGAppRefresh/BGProcessing) | Foreground-Catch-up
  → InferenceEngine: kontinuierlicher Sample-Stream → 1-s-Fenster (0.5 s Stride)
       → 47 Features → RF(JSON) → OnlineForwardFilter → Schreib-Entscheidung
       → Schreibzeit-Buckets → FocusStore → Ringe füllen sich rückwirkend
```

**Dedup / Idempotenz** (mirror der server-seitigen `inference_log`+`/focus`-Semantik):
- Jedes Sample trägt einen monotonen `CMSensorRecorder`-Timestamp.
  `PassiveBatchStore` persistiert `lastProcessedTimestamp`.
- Abruf immer `since: cursor`; beim Ingest werden Samples `≤ lastProcessed`
  verworfen → überlappende/doppelte Batches zählen nie doppelt.
- Die Engine schreibt **pro Zeit-Bucket** (per-window Schreibzustand, keyed by
  Bucket-Startzeit) per **Upsert** — Gesamt-Schreibzeit = Summe über Buckets.
  Re-Processing überschreibt identisch statt zu addieren → idempotent. Der Cursor
  rückt erst nach erfolgreichem Persist vor; ein Crash mitten drin re-prozessiert
  denselben Bucket folgenlos.

**Zwei Subtilitäten:**
1. **Keine Batch-Grenzen-Naht.** Gefenstert wird der dedup-rekonstruierte
   *kontinuierliche* Sample-Stream, nicht pro Batch — ein Fenster darf zwei
   übertragene Batches überspannen.
2. **HMM-Zustand über Batches.** Der `OnlineForwardFilter` läuft über kontinuierliche
   Samples einfach weiter; nur bei einer echten Zeitlücke (Watch aus, Aufnahme
   pausiert, Sprung > Schwelle) macht die Engine `reset()` (identisch zur
   Live-Inferenz-Reset-Regel).

## 6. Fehlerbehandlung & Edge-Cases

Alle fail-safe, nie stiller Datenverlust:
- **Background feuert nicht** (iOS opportunistisch) → App-Open-Catch-up rekonziliert
  immer vollständig. Ringe sind „meist aktuell", beim Öffnen exakt.
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

## 7. Tests

- **Golden-Vektor-Parität (Kern):** Fixture (roh-Accel → 47 Features → proba_raw →
  HMM-Posterior) im `ScrybeTests`-Target; Swift-Tests asserten Extractor / RF / HMM /
  Engine gegen das Fixture mit winzigem ε. Fängt die Sort-Stability/Capture-Clock-
  Bug-Klasse auf der Swift-Seite — der Grund für JSON-Trees + Referenz-Evaluator.
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

- **Phase 0 — Python-Fundament** *(hier voll verifizierbar)*: acc-only-Modell
  trainiert (✅); + **Deployment-Modell-Validierung** (siehe Annahme unten:
  pooled-Z-Score gegen Roh-Accel); + JSON-Export + Referenz-Evaluator +
  Paritätstest + Golden-Vektor-Dump. Landet zuerst, grün, vor jeglichem Swift.
- **Phase 1 — iPhone-Inferenz-Kern** *(Swift, gerätegeprüft)*: Extractor + RF + HMM +
  Engine, getrieben nur von den Golden-Vektoren (keine Sensoren). Beweist
  On-Device-Parität isoliert.
- **Phase 2 — Passive Erfassung**: PassiveRecorder (Watch) + PassiveBatchStore/Dedup
  + BackgroundScheduler + WC-Transfer. Verdrahtet echte Daten in die bewiesene Engine.
- **Phase 3 — Modus & Interlock**: AppModeStore + ModeToggle + ModeIndicator +
  Wiring + die vier Garantien.

Phase 0 unblockt alles und ist hier abschließbar; Phasen 1–3 werden inkrementell aufs
Gerät gebaut und verifiziert.

## 9. Annahmen

- Tracker-Modus ist **vollständig server-unabhängig** (offline-fähig); kein
  hybrider „Server wenn verfügbar"-Pfad (YAGNI).
- **Pooled-Z-Score gegen Roh-Accel (offene Validierung, Phase 0).** Der ≈0-Befund
  des Roh-Accel-Abschlags (`passive_raw_accel_loso.py`) lief unter *per-session*
  Z-Score, der den Schwerkraft-Offset pro Session absorbiert. Das Deployment-Modell
  nutzt *pooled* (eingebackene) µ/σ; die offset-sensitiven Features (mean/min/max/
  rms der Accel-Achsen) tragen bei Roh-Accel einen Schwerkraft-Offset, den auf
  userAcceleration gefittete µ/σ nicht re-zentrieren. Vor dem Swift-Port in Phase 0
  zu klären: entweder (a) das Deployment-Modell auf rekonstruierter Roh-Accel
  trainieren (passt µ/σ an das Deploy-Signal an), oder (b) auf die mean-invarianten
  Features beschränken (std/jerk/FFT/ZCR/corr — unter beiden Signalen äquivalent).
  Bis dahin gilt `rf_acc_only_live.joblib` (userAccel + pooled) als vorläufig.
- `CMSensorRecorder` zeichnet ~50 Hz auf → Raten-Match zum 50-Hz-Legacy-Modell.
- Die HMM-Parameter (`hmm_live.json`) sind modell-agnostisch (Übergangsmatrix =
  Label-Dynamik) und gelten auch für das acc-only-Modell; bei Bedarf später aus
  acc-only-OOF nachgezogen.
- Background-Aktualität ist „eventually current" (iOS-opportunistisch), exakt beim
  App-Öffnen — bewusst akzeptiert für die Passiv-/Akku-Ziele.

# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

ML4SCS (Machine Learning for Smart and Connected Systems) — semester
project by Noah Samel, Ben Kriegsmann, and Tajuddin Snasni. Goal: a
general writing-activity detector from **Apple Watch IMU data alone** —
binary classification (writing vs. not writing) on the wrist-worn IMU
stream, independent of who is wearing the watch or what is being written.

The Moleskine Smart Pen is used **only during data collection** as
ground truth: pen stroke events (`dot_type`) label the watch samples at
the matching timestamp. Once trained, the pen is no longer needed —
inference runs on the watch.

Sensors during training-data collection:
- **Moleskine Smart Pen (NWP-F130)** — ground truth; x/y, pressure,
  tilt at ~80–90 Hz over BLE.
- **Apple Watch (Series 7)** — primary model input; accelerometer +
  gyroscope at 50 Hz via CoreMotion → iPhone bridge → FastAPI server.
- **AirPods (Pro / 3rd Gen)** — additional head-IMU stream via
  `CMHeadphoneMotionManager`, captured alongside the watch through the
  same iPhone bridge. Currently logged but not yet used by the model.

Status: data collection + preprocessing + watch-base merge + quality
checks + sliding-window features + Random Forest baseline + LOSO
cross-validation + Study Mode (counterbalanced protocol runner with
fullscreen proband UI and VL admin monitor) + Live-Inference im
Dashboard (Topbar-Pill, Recording-Page-Card, eigener `#focus`-Tab
mit persistenter Schreibzeit-Aggregation) + Modell-Switcher
(Personal ↔ Generic) are operational. **Current headline (15-person
cross-subject LOSO seit 2026-06-13 — 10 Legacy-Probanden + P12–P15 +
P17 als 50hz-Views via Downsample-Bridge; RF + per-session z-score +
`max_gap_ms=2500` label closing; **Capture-Clock-Fix** angewandt):
accuracy 0.872 ± 0.037, ROC-AUC 0.947 ± 0.026, F1(writing) 0.873.
Burst-aggregiert **kausal** (trailing / `center=False` —
live-tracker-ehrlich, seit 2026-06-11): @5s acc 0.860 ± 0.044,
AUC 0.933 ± 0.032; @10s acc 0.825 ± 0.049, AUC 0.906 ± 0.040;
@30s acc 0.771 ± 0.051, AUC 0.856 ± 0.049.**
**Capture-Clock-Fix (2026-06-13):** Merge-/Window-Zeitachse läuft jetzt
auf der per-Sample-Watch-Uhr `ts` statt der Batch-Ankunftszeit
`local_ts_ms`. Letztere ist batch-quantisiert (alle Samples eines POSTs
teilen einen Wert) und bei Spill-Drain-Strecken Minuten verspätet
(S019/P07: 33 % der Samples >2,5 s versetzt, max 42 s; S043: 5,3 %,
max 13,6 s), wodurch Labels zeitversetzten Pen-Aktivitäten zugeordnet
wurden. Gepaarter Vorher/Nachher-Vergleich (Wilcoxon, N=15):
**15/15 Folds besser, mean +2,4 pp acc, p = 0,0001** auf acc/AUC/F1.
Größter Gewinner **P07 +8,5 pp acc / +9,3 pp AUC** — die
„Signal-Ambiguitäts-Decke" dieses Folds war zu großen Teilen
zeitversetztes Labeling, kein irreduzibles Signal-Problem.
Wichtig: die **früheren zentrierten** Burst-Zahlen waren ~5–6 pp höher,
weil `rolling(center=True)` Zukunfts-Fenster mit-mittelte — nicht-kausal
und für eine als live verkaufte Metrik unzulässig. Unter kausaler
Glättung hebt Burst-Aggregation die Metrik **nicht** über das
1-s-Window-Level; der scheinbare Gewinn war das Artefakt.
**Alle anderen Burst-Zahlen in dieser Datei (CNN-Deep, harnet
frozen/finetune, harnet↔RF-Fusion) wurden noch unter `center=True`
UND vor dem Capture-Clock-Fix gerechnet und sind regenerations-
pflichtig** (beide Code-Fixes sind global, Zahlen noch nicht nachgezogen).
Für gepaarte
Within-Kohorten-A/Bs gibt es `src/evaluation/significance.py`
(Wilcoxon signed-rank); kleine pp-Differenzen ohne p < 0.05 sind als
Rauschen zu reporten. Kanonische
Artefakte (`rf_all.joblib`, `loso_cv.csv`, `loso_oof.csv`) sind auf
N=15 + Capture-Clock-Fix retrainiert (Promotion via
`--pool legacy --no-pool-suffix`); `rf_all_live.joblib` ist noch auf
N=14 pre-fix und retraining-pflichtig. Vorgänger-Headlines:
**14-Probanden (pre Capture-Clock-Fix): acc 0.855 ± 0.034 /
AUC 0.929 ± 0.034 / F1(w) 0.862.**
**10-Probanden (post Sort-Stability-Fix): acc 0.863 ± 0.032 /
AUC 0.935 ± 0.032 / F1(w) 0.875; @5s 0.902/0.968, @30s 0.844/0.922.**
Davor (vor Sort-Stability-Fix,
siehe `reports/sort_stability_bug.md`): 10-Probanden 0.856 / 0.928;
8-Probanden gap=2500 acc 0.861 ± 0.035 / AUC 0.932 ± 0.035;
7-Probanden gap=2500 acc 0.868 ± 0.024 / AUC 0.943 ± 0.014;
7-Probanden gap=2000 acc 0.864 ± 0.026 / AUC 0.940; 5-Probanden
gap=2000 acc 0.872 ± 0.020 / AUC 0.940; 3-Probanden gap=300 acc
0.842 ± 0.007 / AUC 0.909 (ExtraTrees). Alle Pre-Fix-Zahlen wurden
auf systematisch verrauschten Features gerechnet (Trainings- und
Test-Daten symmetrisch betroffen, relative Vergleiche bleiben gültig).

## Setup

```bash
pip install -r requirements.txt
```

Dependencies: `pandas`, `numpy`, `scikit-learn`, `matplotlib`, `bleak`,
`fastapi`, `uvicorn`, `websockets`, `pytest`, `jupyter`, `notebook`.

## Running

**Server (required for data capture):**
```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```
Dashboard at `http://localhost:8000`.

**Pen logger standalone (no server):**
```bash
python pen_logger.py [--password XXXX] [--session S001]
```
With `--session`, output goes to `data/raw/pen/{session}_pen.csv`;
otherwise to `pen_log_YYYYMMDD_HHMMSS.csv` in the working directory.

**Test the watch HTTP endpoint:**
```bash
./scripts/ops/test_server.sh [IP]    # defaults to 127.0.0.1
```

**Convenience scripts:**
- `scripts/ops/start.sh` — boots the server and (optionally) a Cloudflare
  tunnel in one TTY UI; Ctrl+C cleans up both.
- `scripts/ops/tunnel.sh` — standalone Cloudflare quick tunnel
  (`https://*.trycloudflare.com → localhost:8000`).
- `scripts/plots/plot_alignment.py` — runs the pen↔IMU alignment for a
  session and renders the explanatory 4-panel figure (top: variance
  with stroke overlay raw vs δ-shifted; bottom: J(δ) coarse + fine).

**Merge / features / train / evaluate (full ML pipeline):**
```bash
python -m src.merge S029                          # watch-base merge → data/processed/S029_merged.csv
python -m src.features S029 --max-gap-ms 300      # sliding-window features → data/processed/S029_windows.csv
python -m src.training.train_loso                 # LOSO cross-validation (headline metric)
python -m src.training.deep --model cnn --pool legacy  # ein Deep-Modell, LOSO vs RF
python -m src.training.deep.harnet --model harnet5          # Transfer-Learning Stufe 1 (frozen) vs RF
python -m src.training.deep.harnet_finetune --model harnet5 # Stufe 2 (end-to-end fine-tune)
python -m src.training.train_loso --save-oof      # + OOF-CSV für Regression
python -m src.evaluation.regression               # Schreib-Prozent: MAE/RMSE/Bias + Plots
python -m src.evaluation.engagement               # Schreibzeit-Anteil pro Aufgabe + Heatmap
python -m src.training.within_session.train_rf S029   # within-session 80/20 RF (debug/feature-iteration)
python -m src.evaluation.evaluate S029            # placeholder, prints label distribution
python scripts/plots/plot_merged.py S029 --max-gap-ms 300   # visualize IMU + label overlay
```
Without args, `src.merge` / `src.features` operate on the most recent session.

**Run smoke tests:**
```bash
pytest tests/         # 346 tests, ~10 s
```

**Study Mode (counterbalanced data collection):**
From the dashboard's Recording page, toggle to Study Mode → the
protocol dropdown defaults to `v2` (the current protocol; `v1` still
selectable) → START STUDY. The proband side
enters a fullscreen takeover (Watch-style UI: pre-task countdown,
audio cues, instructions, last-5s urgent pulse); the VL controls
Pause / Next / Abort. Once running, the `#admin` page (hidden from
the tab strip — reached by **triple-clicking the brand logo**) gives
a second-screen monitor view for the experimenter without leaving
the proband's screen. See *Study Mode* below.

## Architecture

```
Apple Watch (MotionManager.swift)
  → batches of 10 samples at 50 Hz via WatchConnectivity
  → iPhone (PhoneBridge.swift)
  → HTTP POST /watch
  → server.py → data/raw/watch/{session}_watch.csv

AirPods (CMHeadphoneMotionManager on iPhone)
  → HTTP POST /airpods
  → server.py → data/raw/airpods/{session}_airpods.csv

Moleskine Smart Pen (BLE)
  → pen_logger.py (subprocess spawned by server.py)
  → data/raw/pen/{session}_pen.csv
                    ↓
       src/alignment/pen_match.py    (recover per-session δ via
                                      stroke-variance minimization;
                                      σ ≤ -3 → use for ML)
                    ↓
       src/merge/merge.py            (watch-base: 1 row per watch
                                      sample with label_writing from
                                      pen activity in ±40 ms)
                    ↓
         data/processed/{session}_merged.csv  (50 Hz watch + raw label)
                    ↓
       src/features/windows.py       (sample-level label closing,
                                      max_gap_ms=2500 → "writing mode"
                                      semantics; sort by per-sample
                                      `ts` with kind='stable' to match
                                      live-inference ordering — see
                                      reports/sort_stability_bug.md;
                                      then 1 s / 0.5 s sliding windows
                                      → 88 features in 6 groups:
                                      time-stats, spectral (FFT), jerk,
                                      ZCR, magnitude, cross-axis
                                      correlations)
                    ↓
         data/processed/{session}_windows.csv  (1 row per window)
                    ↓
       src/training/train_loso.py    (HEADLINE: LOSO by person, N=15,
                                      RF 200 trees + per-session z-score,
                                      class_weight=balanced, then per-
                                      session rolling-mean burst-agg
                                      @1s/5s/10s/30s decision-windows)
       src/training/within_session/  (debug only — temporal 80/20 split
         train_rf.py                  for feature/smoothing iteration)
       scripts/ml/train_noah_personal.py    (Personal-Modell auf S032+
                                      S033 ohne Z-Score → rf_noah)
       scripts/ml/train_rf_all_live.py      (Deployment-Variant des
                                      Generic-Modells mit eingebackener
                                      pooled mu/sigma → rf_all_live)
                    ↓
         models/rf_all.joblib        (LOSO-Headline-Artefakt)
         models/rf_noah.joblib       (Personal-Modell, Live-Default,
                                      100 Hz, ohne Z-Score)
         models/rf_all_live.joblib   (Generic-Modell mit pooled
                                      Z-Score, Live-tauglich)
         models/loso_cv.csv          (per-fold metrics)
                    ↓
         acc 0.872 ± 0.037  |  AUC 0.947 ± 0.026  |  F1(w) 0.873
         burst @5s: acc 0.860 / AUC 0.933  (kausal/trailing)
         burst @30s: acc 0.771 / AUC 0.856  (Schreibzeit-tracking)
                    ↓
       src/server/inference.py       (Live-Inference-Singleton, lazy
                                      Modell-Load, Rolling-Buffer,
                                      Rate-Mismatch-Guard)
                    ↓
       src/server/focus_log.py       (Append-only inference_log.csv
                                      @1 Hz aus _status_loop)
                    ↓
         /focus/today + /focus/week (Aggregator-Endpoints für
                                     Recording-Page-Card + #focus-Tab)
```

### Server (`server.py` + `src/server/`)

`server.py` is a thin entry point (~50 lines). All logic lives in
`src/server/`. Dependency order (no backwards imports):

```
config.py          paths, field names, sessions.csv init
                   (re-exports PEN_FIELDNAMES from src/pen_schema.py)
utils.py           pure helpers (_now_ms, _as_float, _mad …)
state.py           SessionState class + global `state` object
logging_setup.py   RotatingFileHandler + EventLog handler wiring
csv_io.py          read/write watch + pen + airpods + sessions CSVs;
                   _next_session_id() (scans raw/{pen,watch,airpods}
                   to avoid ID reuse); _pen_recent_dots() for the live
                   whiteboard preview
status.py          connection status + _status_payload() for WS broadcasts
issues.py          ISSUE_SPECS table + _TARGET_WATCH_HZ / _TARGET_AIRPODS_HZ;
                   single source of truth for issue codes/severities
sync.py            sync-confidence helpers around the alignment output
timelines.py       per-session timeline reconstruction for validation views
quality.py         _session_facts() = single source of truth for facts;
                   _session_quality / _session_validation / _session_report
                   (re-exports ISSUE_SPECS for external consumers)
broadcast.py       _broadcast() + _status_loop() (1-s tick); calls
                   live.predict() + focus_log.log_tick() each cycle
pen_proc.py        starts/stops pen_logger.py as a subprocess
models.py          Pydantic schemas (WatchEnvelope, SessionStartBody …)
study.py           Study Mode internals: protocol loader (Pydantic
                   schema), balanced_latin_square(n) (Williams-design
                   counterbalance, scales to any writing-task count),
                   scheduler that interleaves writing tasks with
                   pauses, and the runtime state machine (idle / running
                   / paused / done). Pure Python — no FastAPI imports,
                   fully unit-testable.
inference.py       LiveInference singleton: rolling watch-sample buffer,
                   lazy joblib load (rf_noah preferred, fallback chain
                   rf_all_live -> rf_all), per-window predict() with
                   rate-mismatch guard, sparkline ring, daily-aggregate
                   counter. Reuses _window_features() from
                   src.features.windows so live + training share the
                   exact same feature extractor.
focus_log.py       Append-only CSV writer at data/inference_log.csv
                   (gitignored). One row per 1-Hz predict tick;
                   rate_mismatch ticks skipped. Persists writing
                   activity across server restarts so /focus aggregates
                   are truthful.
training.py        Web-Training-Cockpit: TrainingRun-State-Machine (idle/
                   running/done/error, genau EIN Lauf gleichzeitig), startet
                   train_loso als Subprozess mit --emit-json (Muster pen_proc),
                   parst JSON-Events → State, psutil-HW-Sampling, Graceful Stop
                   (SIGINT → Teilergebnis). Reine Event-Handler unit-testbar.
                   train_loso bekam dafür on_event/run_dir + --emit-json/
                   --run-dir; CLI ohne diese Flags bit-identisch.
training_runs.py   Nicht-destruktiver Run-Store: models/runs/{run_id}/
                   (cv.csv/oof.csv/model.joblib/config.json). promote() ist der
                   EINZIGE Schreibpfad auf die kanonischen Artefakte
                   (rf_all.joblib/loso_cv.csv/loso_oof.csv). Modell-Menü +
                   Pool-Validität: src/training/registry.py; Event-Schema:
                   src/training/events.py.
routes/            FastAPI endpoint package — one APIRouter per concern
                   (watch.py, airpods.py, pen.py, sessions.py,
                    study.py, dashboard.py, inference.py, focus.py,
                    training.py, ws.py, _helpers.py); __init__.py aggregates
                    them into a single `router`. training.py: /training/
                    {models,start,stop,current,runs,runs/{id},runs/{id}/
                    promote,runs/{id}/sandbox} — Frontend: static/js/pages/
                    training.js (Training-Tab, Live-Cockpit via WS-Snapshot).
```

`src/pen_schema.py` is a top-level shared module (no deps) so
`pen_logger.py` can stay a standalone script while still sharing the
canonical `PEN_FIELDNAMES` with the server.

The pen logger runs as an `asyncio.create_subprocess_exec` child;
`POST /pen/connect` and `/pen/disconnect` control it independently, and
session start/stop start/stop it automatically.

### Key endpoints

- `GET /` — `dashboard.html`
- `POST /session/start` / `POST /session/stop` — write `data/sessions.csv`
- `POST /watch` — receives IMU batches; supports both flat list and
  `{samples: [...]}` envelope formats
- `POST /airpods` — same envelope shape, head-IMU stream
- `GET /sessions/quality` — quality snapshot for every session
- `GET /sessions/{id}/validation` — deep validation (timeline, drift, sync)
- `GET /sessions/{id}/report?format=json|md` — full per-session report;
  Markdown form is the "⤓ md" link in the dashboard
- `POST /sessions/{id}/mark-test` — retroactive flip of a session to
  `study_mode='test'`, prepends `[TEST] ` to description; the
  resulting session is excluded from Latin-Square counting and from
  default LOSO inclusion
- `GET /study/protocols` — lists available protocols in
  `study_protocols/` (`v1.json`, `v2.json`; v2 is the default)
- `POST /study/start` — boots a Study-Mode session: loads protocol,
  computes Latin-Square ordering from `subject_index`, starts the
  session, writes the first marker to `data/raw/markers/{id}_markers.csv`
- `POST /study/next` / `POST /study/pause` / `POST /study/abort` —
  drive the state machine; emits markers on every transition
- `GET /inference/models` — lists available joblibs in `models/` with
  metadata (`id`, `person_id`, `sample_rate_hz`, `trained_on`,
  `n_windows`, `normalisation`). Whitelist of user-facing models:
  `rf_noah`, `rf_all_live`, `rf_all`.
- `GET /inference/current` — currently loaded model id + meta
- `POST /inference/model {id}` — swap the live model; clears the
  inference buffer for a clean restart. 404 on unknown id.
- `GET /focus/today` — today's writing stretches (consecutive
  `writing=1` ticks, gaps ≤ 2.5 s forgiven) + total seconds + tick
  count, scoped to local-time day bounds.
- `GET /focus/week` — last 7 days as `{date, weekday, writing_seconds,
  is_today}` buckets, oldest first, plus week-max for bar scaling.
- `WebSocket /ws` — dashboard status (1 s tick) + iPhone bridge
  messages + per-tick `study` payload (current task, time-remaining,
  next-task preview) + per-tick `live_inference` payload (writing,
  proba, model_id, fs_hz, today_writing_seconds; or `rate_mismatch:
  true` when buffer fs diverges >20 % from trained fs)

`_status_loop` broadcasts `_status_payload()` once a second, updates
rolling Hz estimates, and maintains a 60-point rolling chart buffer
(acc magnitude, gyro magnitude, pen writing state).

### Dashboard frontend (`dashboard.html` + `static/`)

`dashboard.html` is a thin shell: head with stylesheet + module
preload tags, topbar markup (Recording · Focus · Sessions · Settings,
plus hidden Admin), the `liveInferencePill` next to the status cluster,
six empty `<div data-view="..."></div>` page slots, and
`<script type="module" src="/static/dashboard.js">`.

`static/dashboard.js` is the bootstrap (~165 lines). On `hashchange` it
calls `showPage(pageId)`, which lazy-fetches the matching partial from
`static/views/<page>.html` (cached after first fetch), injects it via
`DOMParser` + `replaceChildren`, calls the page module's `mount(slot)`
exactly once, then `onShow()`. Switching away calls the previous page's
`onHide()`. WS ticks go through `setActivePageDispatcher`, which routes
`onStatus(payload)` to the active page only — hidden pages do no
per-tick work. Session Detail's `onHide` calls `_destroyAlignCharts()`
to tear down the alignment-plot canvases when leaving (the main perf
mechanism, since that page is the heaviest).

Page modules live in `static/js/pages/{recording,recording-study,
focus,sessions,session_detail,settings,admin}.js` and all export the
same four-function contract: `mount(container)`, `onStatus(payload)`,
`onShow()`, `onHide()`.

`focus.js` is the dedicated Focus-Tracker tab — contemplative
counterpart to the Recording cockpit. Hero `h:mm` clock left, 24-hour
day-timeline strip right (with writing stretches as gradient blocks +
"now" marker that advances on every WS tick), seven-bar week frieze
below (today highlighted, peak day tagged). Reads `/focus/today` and
`/focus/week` on mount and re-polls every 5 s while visible; live pill
updates from each WS tick. Styles in `static/css/focus.css` with its
own background slash glyph (mirror-flipped vs Recording's). The
Recording-page also exposes an embedded inference card (writing-now
state + 60-s sparkline + "writing time tracked" counter) with an
in-place model picker (Personal ↔ Generic ↔ Generic-per-session)
that calls `POST /inference/model`.

`recording-study.js` is the **fullscreen takeover** for the proband
side once Study Mode is running. It is a sibling of `recording.js`:
the recording view switches between the two depending on whether
study runtime state is active. When active, it adds the
`body.study-active` class which takes over the whole viewport (topbar
hidden), performs a FLIP-style animation between tasks, and plays
two audio cues — an 880 Hz tick during the last-5-second urgent pulse
and an E5/B5 two-note chime at task transitions. Markup is built via
the DOM API (no template string innerHTML) to avoid re-mounting the
same nodes between ticks. Styles live in `static/css/study-mode.css`.

The `#admin` page is **hidden from the tab strip** (intentionally —
the proband must not see it). It is reached by triple-clicking the
brand logo in the topbar (the easter-egg lives in `dashboard.js`).
It mirrors the live status / chart / connections summary so the VL
can monitor the recording from a second device (iPad) without
intruding on the proband's screen. Files: `static/js/pages/admin.js`,
`static/views/admin.html`, `static/css/admin.css`.

Cross-cutting concerns in `static/js/core/`:
- `state.js` — `S` object + `updateFromStatus(payload)` + named getters
- `ws.js` — WebSocket connection, reconnect with backoff. On each
  message: `updateFromStatus(msg)` → `handleStatus(msg, prevSessionId)`.
  Note the second arg: it carries the pre-update `S.lastStatus.session_id`
  so cross-session canvas clearing still works after state mutation moved
  into `state.js`.
- `status_cluster.js` — `handleStatus` updates the topbar pills/badges
  and ends with `_activePageDispatch(s)`.
- `router.js` — hash routing, tab indicator, `closeSessionDetail`.
  `closeSessionDetail` sets `location.hash = 'sessions'` (not
  `history.replaceState`) so `hashchange` fires and the bootstrap's
  `activePage` stays in sync.
- `api.js`, `dom.js`, `format.js`, `theme.js`, `anim.js`, `toast.js` —
  pure helpers + leaf services.

Per-page styles live in `static/css/<page>.css`; cross-cutting tokens and
layout are in `static/css/base.css` + `static/css/topbar.css`.

**Inline `onclick=` handlers in view partials** reference functions as
`window.foo()`. Since the bootstrap is a module (functions are not global
by default), `dashboard.js` ends with an explicit
`Object.assign(window, { ... })` block exposing every handler name. If
you move or rename a function called from inline HTML, update that block.

**Static-asset HTTP smoke test** at `tests/test_dashboard_static.py`
parametrises every JS module / view partial / stylesheet path. Catches
the silent-404 failure mode (browsers serve `text/html` for missing
`.js` and ES modules fail to parse opaquely). When you add a new file
under `static/js/`, `static/views/`, or `static/css/`, add the path to
the parametrise list.

### iOS / watchOS app (`watch_streamer/`)

Two Xcode targets:

- **WatchStreamer Watch App** (`MotionManager.swift`): captures
  `CMDeviceMotion` over `WCSession.sendMessage` (or `transferUserInfo`
  background fallback). Streamt seit 2026-05-26 **9 Werte pro Sample**:
  `motion.userAcceleration` (ax/ay/az), `motion.rotationRate`
  (rx/ry/rz) und `motion.gravity` (gx/gy/gz). Das sind **6 Sensor-Achsen**
  (Accel + Gyro); gx/gy/gz ist die Schwerkraft-Komponente desselben
  Beschleunigungssensors, kein eigener Kanal — siehe *Pool architecture*. Sample-Rate und Batch-Größe sind konfigurierbar
  (Phone-App → Settings → Motion; Default 50 Hz / Batch 10) — die Werte
  kommen über jeden `command`/Poll-Reply als `requested_hz`/`batch_size`
  und werten `effectiveHz`/`effectiveBatchSize` aus (H3). Was sonst
  gedroppt würde (Buffer-Overflow, volle `transferUserInfo`-Queue), geht
  als JSON-Zeile in `watch_spill.jsonl` auf die Watch-Disk und wird per
  Drain-Timer über den Live-Pfad nachgeliefert — verlustfrei, übersteht
  App-Kill (H1). Motion-Callbacks laufen auf einer Background-
  `OperationQueue`, nicht auf Main; der Callback staged nur, `drainStaging()`
  speist die Main-Pipeline (H4).
  **Spill-Flush (seit 2026-06-13).** Der Spill-Drain-Timer läuft ab
  `init()` unabhängig von `isRunning` — d. h. eine gestoppte App liefert
  beim nächsten Reconnect verwaiste Samples einer längst beendeten Session
  nach (S044-Folgeproblem: Force-Quit löscht den persistenten Spill nicht).
  Drei Hebel: (1) `forceDrainSpill()` / Command `drain_spill` — sendet den
  ganzen Spill im **Burst** (Erfolgs-Handler kettet, statt 1 Zeile/3 s),
  nicht-destruktiv; (2) `clearSpill()` / Command `clear_spill` — verwirft
  den Spill, **Guard `!isRunning`** (Live-Stau einer laufenden Aufnahme ist
  echte Daten und darf von einem evtl. stale via `transferUserInfo`
  zugestellten Lösch-Befehl nie weggeworfen werden); (3) `discardForeignSpill()`
  **bei Session-Start** — trägt die älteste Spill-Zeile eine fremde
  `sessionId`, wird der Spill vor dem Aufnehmen verworfen (Strukturfix gegen
  das „nächster-Morgen"-Problem). iPhone-Seite: `ServerCommandListener.{drain,
  clear}WatchSpill()` + zwei Buttons in der Repair-Sektion von
  `iPhoneView_v4.swift` („Spill senden" / „Spill verwerfen" mit
  Bestätigungsdialog). Beide Commands werden als `watch_ack` quittiert und
  landen via Ack-Persistenz im `server.log`. **Herrenlose Samples
  serverseitig:** `POST /watch` schreibt ohne aktive Session nach
  `unsessioned_watch.csv` statt an die vom iPhone gemeldete (zuletzt
  gestreamte) Session-ID anzuhängen (`routes/watch.py`) — Quarantäne gegen
  genau diese Reconnect-Verschmutzung.
- **WatchStreamer (iPhone)** (`PhoneBridge.swift`): receives
  WatchConnectivity messages, normalises payload, queues HTTP POSTs
  to `http://{serverIP}:8000/watch`. Server IP in `UserDefaults`
  (`"serverIP"`).

Watch ↔ iPhone start/stop commands flow over WatchConnectivity. The
server broadcasts `{type: "start"/"stop", session_id: …}` over the WS;
the iPhone bridge forwards to the watch.

**WS connection epoch (`ServerCommandListener.swift`):** each
`connect()` bumps `connectionEpoch`. Receive/send callbacks capture
the epoch at registration; if it has moved on by callback time the
callback returns silently. This prevents a cancelled task's `.failure`
from scheduling a reconnect that kills the live connection — was the
root cause of an earlier 3 s reconnect storm.

**Haptic feedback** is gated on actual transitions (false→true /
true→false) rather than every `@Published` re-emit, so the iPhone
no longer vibrates continuously when the server is down.

### ML pipeline (`src/`)

- `src/alignment/pen_match.py` — `pen_match()`, `match_pen_data()`,
  `strokes_from_dot_types()`, `reconstruct_watch_wall_clock()`. Recovers
  the per-session pen↔watch clock offset δ via stroke-window variance
  minimization (ETH Zürich algorithm, see *Sample-level merge alignment*
  below). Replaces the planned tap-sync recording protocol.
- `src/merge/prep.py` — per-stream cleaning helpers (`prepare_pen_data()`,
  `prepare_watch_data()`, `load_csv()`). Still exported for external use;
  the canonical ML merge no longer needs the pen-side per-sample features.
- `src/merge/merge.py` — `merge_watch_pen()`: **watch-base merge**.
  Join-Achse ist die per-Sample-Capture-Uhr `ts` (interne Hilfsspalte
  `_wall_ms`, vor Return gedroppt; Fallback `local_ts_ms` nur ohne
  ts-Spalte) — **nicht** `local_ts_ms` (siehe *Capture-Clock-Fix* in den
  Gotchas). Sortiert watch + pen `kind="stable"` (siehe *Sort-Stability-Bug*
  + `reports/sort_stability_bug.md`). Calls `match_pen_data`, applies δ to
  the pen wall-clock when σ ≤ -2 (δ wurde schon immer gegen `ts` optimiert),
  then `merge_asof` with **watch as base** within ±`label_tol_ms`
  (default 40 ms). Result: 1 row per watch sample, with `label_writing`
  = 1 iff nearest pen `dot_type` ∈ {PEN_DOWN, PEN_MOVE} within tolerance,
  else 0. Watch samples in pen-gaps → label 0 (the negative class —
  critical for binary classification).
- `src/merge/__main__.py` — CLI: `python -m src.merge [SESSION_ID]`,
  writes per-session to `data/processed/{session}_merged.csv` (no
  overwriting).
- `src/features/windows.py` — `smooth_labels()` + `build_windows()`.
  Sort wird per-Sample-monotonic via `ts`-Spalte mit `kind='stable'`
  gemacht (siehe Sort-Stability-Note in den Gotchas — pre-fix wurde
  unstable by `local_ts_ms` sortiert, was bei Batch-Ties Samples
  scrambled und Trainings- von Live-Features divergent machte).
  Sample-level **morphological closing** on the binary label sequence
  (idle gaps ≤ `max_gap_ms` between writing runs → flipped to writing;
  default 300 ms) before windowing. Then 1 s sliding windows with
  0.5 s stride → **88 features per window**, in 6 semantic groups:
  *time_stats* (36: mean/std/min/max/rms/range per axis), *spectral*
  (24: dominant frequency, spectral centroid, spectral entropy, 3–8 Hz
  band ratio per axis via rFFT — DC-bin removed before centroid/
  entropy), *zcr* (6 per-axis zero-crossing rates), *jerk* (8: std +
  mean-abs of d/dt on accel axes + magnitudes; `× fs_hz` for scale
  invariance), *magnitude* (6 accel/gyro mag mean/std/energy), and
  *correlation* (6 cross-axis Pearson pairs, accel-pairs + gyro-pairs,
  zero-std-safe). Window label = 1 iff ≥ 60% of samples in the window
  have `label_writing == 1`. Optional opening (`--max-spike-ms`) is
  implemented but defaults off — empirically didn't help on S029.
- `src/features/__main__.py` — CLI: `python -m src.features [SESSION_ID]
  [--max-gap-ms 300] [--max-spike-ms 0]`, writes
  `data/processed/{session}_windows.csv`.
- `src/training/within_session/train_rf.py` — **debug/feature-iteration
  baseline, not the headline metric.** `RandomForestClassifier` (200
  trees, `class_weight="balanced"`) with a temporal 80/20 split by
  `t_center_ms` plus a 4-window gap at the cut to prevent overlap
  leakage (adjacent windows share 50% of samples). Use this for fast
  iteration on features or label-smoothing parameters, *not* to claim
  generalisation — within-session metrics only measure "can the model
  finish this session given the start of it". Loads cached
  `{session}_windows.csv` if present, else builds on the fly. Dumps
  to `models/rf_{session}.joblib`.
- `src/training/train_loso.py` — **headline metric for the project
  goal.** Leave-One-Out cross-validation. Default `--by person` (true
  LOSO — the right metric for the "general writing detector" promise);
  fallback `--by session` for leave-one-session-out, useful while only
  one subject has been recorded. Filters sessions via
  `verdict ∈ {trainable, usable}` from `sessions.csv` (override with
  `--include-all`). No `temporal_split` needed — the
  subject/session-hold-out is a strictly stronger leakage guarantee
  than zeitliche Trennung (held-out windows were never seen). Reports
  per-fold accuracy/ROC-AUC plus mean ± std summary, **plus
  burst-aggregated metrics at multiple decision-window scales**
  (1 s / 5 s / 10 s / 30 s — controlled by `BURST_SCALES_SEC`).
  Probabilities are smoothed via per-session **causal** (trailing,
  `center=False`) rolling mean — `_causal_rolling_mean()`, no
  look-ahead so the number matches what a live tracker achieves at
  time `t` (stride derived from median Δ`t_center_ms`, robust to
  non-default window configs), then re-thresholded at ≥ 0.5. Critical:
  smoothing groups
  by `session_id` so predictions from temporally-distant sessions in
  the same fold are never mixed. The burst scales surface the share
  of model error that is high-frequency noise versus systematic, and
  give the user-facing metric for aggregated use-cases (e.g.
  Schreibzeit-tracking) without retraining. Per-session z-score
  normalization of features is on by default (`--no-zscore` to
  disable). It standardises each feature column per `session_id`
  before fitting so subject-dependent baselines (wrist size,
  handedness, watch position) don't shift the model's decision
  threshold. Empirically: jumped acc from 0.812 → 0.838 on the
  3-person dataset and tightened fold-σ 4× (0.042 → 0.009) — the
  biggest single ML-side improvement of the project.
- `src/training/deep/` — **Deep-Sequenz-Modell-LOSO** (Roadmap
  Prio 3/4). 1D-CNN / LSTM / GRU auf rohen IMU-Sequenzen statt der 88
  Features, im identischen LOSO-by-person-Protokoll wie `train_loso.py`
  (importiert dessen `_select_sessions` / `_burst_metrics`). `data.py`
  baut rohe Fenster (6 Kanäle; `load_session_raw` nimmt `merged_suffix`
  für die Legacy-View-Quelle + `zscore`-Schalter), `models.py` die drei
  kleinen `nn.Module`-Klassen (seq-len-agnostisch via `AdaptiveAvgPool1d`
  / letztem Hidden-State, daher laufen 50- und 100-Hz-Fenster ohne
  Architektur-Änderung), `train_loso.py` den Trainings-Loop (Early
  Stopping auf rotierendem Person-Holdout) + pool-fähigen LOSO-Runner.
  **Genau ein Modell pro Aufruf**, mit `--pool`-Auswahl analog zum RF:
  `seq_len`/`stride` werden aus der Pool-Sample-Rate abgeleitet
  (`POOL_FS`, ein 1-s-Fenster = 50 Samples legacy / 100 modern),
  `_pool_plan()` mappt jede Session über `watch_profile` auf die
  merged-Quelle (50hz nativ → `_merged.csv`, Modern → downsampled
  `_merged_legacy.csv`-View). Kein `auto` — rohe Sequenzen können keine
  Sample-Raten mischen; fehlende Legacy-View → Skip mit Hinweis statt
  Crash. **Per-Session-Z-Score ist hier standardmäßig AUS** (anders als
  beim RF): gepaartes A/B (CNN, legacy, N=14) ergab Δacc −0.002 / ΔAUC
  −0.001 bei p≈0.65 — statistisch nicht unterscheidbar, weil die
  `BatchNorm1d` nach jeder Conv die Aktivierungs-Skala re-normalisiert
  und das Netz scale-tolerant macht (BatchNorm ≠ Per-Session-Z-Score
  mechanistisch, aber im Effekt ausreichend). Ohne Z-Score ist das CNN
  direkt deploybar — keine Per-Stream-Kalibrierphase für μ/σ. `--zscore`
  schaltet ihn opt-in ein (→ `deep_loso_{pool}_zscore.csv`). Caveat: nur
  fürs CNN belegt; LSTM/GRU haben keine Input-Normalisierung, dort kann
  Z-Score sehr wohl zählen. CLI:
  `python -m src.training.deep --model {cnn|lstm|gru} [--pool legacy|modern] [--win 1|5|both] [--zscore]`
  → `models/deep_loso_{pool}.csv` + Vergleichstabellen gegen die
  RF-Headline (legacy = N=14-Baseline; modern ohne RF-Zeile).
  Legacy-Headline (CNN @1s, N=14, **no-zscore**): acc 0.873 ± 0.035,
  AUC 0.936, @5s 0.897/0.963, @30s 0.843/0.918 — auf Augenhöhe mit dem
  RF (Train/Test-Gap 0.016 = data-limited, nicht Overfit).
- `src/training/deep/harnet*.py` — **Transfer-Learning-Vergleich mit dem
  Oxford `ssl-wearables`-Foundation-Model (harnet)**, im identischen
  LOSO-by-person-Protokoll wie `train_loso.py` (importiert nur
  `_select_sessions` / `_burst_metrics`). Drei Dateien: `harnet_data.py`
  (Bridge merged-CSV → harnet-Fenster: stable-sort `ts`, Label-Closing
  @2500 ms, `scipy.signal.resample_poly` 50→30 = 3/5 bzw. 100→30 = 3/10,
  Labels nearest-sample, `(N,3,150)`-Fenster für harnet5 / `(N,3,300)`
  für harnet10 — **alle Magic Numbers zentral**, `HARNET_VARIANTS`),
  `harnet_frozen.py` (Stufe 1: frozen Conv-Trunk `model.feature_extractor`
  → 512-dim Embedding (harnet5) / 1024-dim (harnet10), pro Session als
  `.npz` unter `data/processed/embeddings/{variant}/` gecached
  (gitignored); darauf LOSO mit zwei Köpfen: LogReg mit C-Sweep
  {0.01,0.1,1} per innerem GroupKFold + RF 200 Trees), `harnet_finetune.py`
  (Stufe 2: volles Modell end-to-end fine-tunen — LR 1e-4, Early Stopping
  auf Val-Person, Modell pro Fold frisch pretrained), `harnet.py` (CLI
  frozen). **Input = `userAcceleration` ohne Gravity** — bewusster
  Distribution-Shift ggü. dem Biobank-Total-Accel-Pretraining (Legacy-Pool
  hat kein Gravity), **kein Per-Session-Z-Score** (Netz erwartet g). CLIs:
  `python -m src.training.deep.harnet [--model harnet5|harnet10]` (frozen,
  Stufe 1) und `python -m src.training.deep.harnet_finetune [--model …]`
  (Stufe 2). Output variantenbewusst: harnet5-frozen ist kanonisch
  (`models/harnet_loso.csv` + `reports/harnet_transfer.md`), andere Varianten
  bzw. Fine-Tuning schreiben klar benannte Siblings
  (`harnet_loso_harnet10.csv`, `harnet_finetune_{variant}.csv/.md`).
  Vergleich immer auf nativer Decision-Skala (harnet5 = 5 s, harnet10 = 10 s).
  **Ergebnisse (N=14):**
  - *harnet5 frozen, LogReg:* per-window (5s) acc 0.896 / AUC 0.958 —
    **gleichauf mit RF@5s** (0.899/0.962).
  - *harnet10 frozen, LogReg:* per-window (10s) acc 0.909 / AUC 0.966 —
    **schlägt RF@10s** (0.882/0.952); @30s 0.881/0.950 vs RF 0.838/0.917
    (+4,3 pp acc). Längerer Kontext hilft dem Foundation-Model spürbar.
  - *harnet5 fine-tuned (Stufe 2):* per-window 0.896 / AUC 0.965 — **kein
    klarer Gewinn vs. frozen** (ΔAcc +0.001, ΔAUC +0.007, in der
    Fold-Streuung). mean best_epoch 0.8 + Train/Test-Gap +0.042 ⇒ die
    vortrainierten Features sind nahe optimal, Fine-Tuning überanpasst bei
    N=14 fast sofort.
  Über alle harnet-Varianten gleiche schwache Folds wie RF (P07/P09/P12),
  per-Fold-AUC r≈0.92 mit RF — modellunabhängige Bestätigung der
  Signal-Ambiguitäts-Decke (siehe `reports/harnet_transfer.md` +
  `feature_engineering_ceiling`-Memory).
  **Fusion-Falsifikation (`scripts/ml/harnet_rf_fusion.py` +
  `harnet_frozen.harnet_oof()`, harnet5, N=14):** koppelt harnets
  frozen-Repräsentation an den 88-Feature-RF — als Proba-Ensemble
  (Mittel zweier OOF-Vorhersagen, sauber) und als Stack (harnet-OOF als
  89. Feature). Auf der **nativen 5-s-Decision-Skala hebt Fusion die
  Headline nicht**: Ensemble ΔAcc −0.011 / ΔAUC +0.001, Stack ΔAcc
  +0.005 / ΔAUC +0.006 vs. RF-baseline-88 im selben Lauf — alles in der
  Fold-Streuung. Per-**window** glänzt die Fusion zwar (RF-AUC 0.923 →
  Stack 0.946 / Ensemble 0.949, +0.023–0.026), aber dieser Gewinn ist
  reines De-Noising der 1-s-RF-Zappelei und damit **redundant zur
  Burst-Aggregation**, die auf 5 s ohnehin glättet → der Vorsprung
  verpufft beim Aggregieren. Entscheidender Window-Level-Test: die
  **Residuen-Korrelation r=+0.574** (Fehler RF vs. Fehler harnet) — beide
  Modelle irren an denselben Fenstern, kein Fusions-Spielraum. Bestätigt
  Szenario (a) window-genau: die Decke ist Signal-Ambiguität, kein freier
  Headline-Sprung durch ein größeres/zweites Modell. Output:
  `reports/harnet_rf_fusion.md` + `models/harnet_fusion_harnet5.csv`
  (+ OOF-Cache `models/harnet_oof_harnet5.csv`). Erste-Setup-Hürde:
  macOS-Framework-Python braucht ein CA-Bundle für `torch.hub`
  (`_ensure_ca_bundle()` setzt `SSL_CERT_FILE` via certifi). Modell-Download
  lazy beim ersten Lauf (~40 s, dann `~/.cache/torch/hub`).
- `scripts/ml/compare_models.py` — runs LOSO on the same splits with
  RF / ExtraTrees / HistGradBoost / LogReg / MLP / SVM-RBF to verify
  RF is still competitive. Same `--no-zscore` flag. Liest
  vor-generierte `{session}_windows.csv` aus `data/processed/`.
- `scripts/ml/compare_models_at_gap.py` — gleiches Modell-Panel, aber
  baut die Features on-the-fly bei beliebigem `--gap` neu, ohne die
  Cache-Dateien anzufassen. Nützlich, um Modell-Rangfolge bei
  alternativen Label-Closing-Werten zu prüfen ohne Re-Generation.
- `scripts/ml/sweep_window_size.py` — **Feature-Window-Größen-Sweep**
  (das *Feature*-Fenster, nicht das Burst-Decision-Window): rechnet die 88
  Features über *längere* Roh-IMU-Fenster (3–5 s statt 1 s, längerer Stride)
  statt 1-s-Predictions nachträglich zu mitteln. Reproduziert den
  N=14-Legacy-Pool exakt (pro Session `*_merged_legacy.csv` bevorzugt, sonst
  native), schreibt in den **separaten** Ordner `data/processed/windows_sweep/`
  (kanonischer `windows/50hz/`-Cache unangetastet), nutzt ausschließlich den
  **kausalen** `train_loso._burst_metrics`. Wichtig: **nicht**
  `compare_models._eval_fold`/`_burst_auc` wiederverwenden — die glätten noch
  `center=True` (nicht-kausal, ~5–6 pp inflationiert). CLI:
  `--pool {legacy,modern}`, `--models` (kuratiertes Panel RF/ExtraTrees/
  HistGradBoost/LogReg), `--config W,S` (mehrfach). Output:
  `models/window_sweep*_cv.csv` (kompatibel mit `src.evaluation.significance`).
  **Befund (2026-06-11, N=14 Legacy):** ein 5-s-**natives** Feature-Fenster
  schlägt 1-s-Features + Burst@5s bei *fixer 5-s-Decision-Latenz* um
  **+2.8 pp acc / +2.3 pp AUC** (gepaarter Wilcoxon p≈0.011, **12/14 Folds
  besser**) — bestätigt den harnet10-Befund (echter Längs-Kontext in der
  Repräsentation > Prediction-Mittelung) jetzt auch für den RF. Mechanik:
  FFT-Auflösung 0.2 statt 1 Hz + Statistik über 250 statt 50 Samples. **Beste
  Parameter:** `5s/2.5s` oder `3s/1.5s` (je 50 % Overlap, statistisch
  ununterscheidbar Δ p=0.71); dichte `5s/1.0s` lohnt nicht (per-window minimal
  höher, @5s schlechter, 2,5× redundante Fenster). **Modell-robust:**
  RF/ExtraTrees/HistGradBoost/SVM-RBF signifikant (+2.0–2.8 pp, p<0.05) über
  vier Modellfamilien (Bagging/Extra-Random/Boosting/Kernel), LogReg gleiche
  Richtung/Größe aber n.s. (schwächstes Modell, höchste Fold-σ) → Feature-
  Qualitäts-Effekt, kein RF-Artefakt. SVM-RBF ist bestes 1-s-Modell (0.862)
  und teilt den 5-s-Spitzenplatz (0.875); Auswahl via `--model SVM-RBF`
  (langsam, SVC probability=True auf ~24k 1-s-Fenstern — nicht im Default-Panel).
  **Gravity-robust nur richtungs-
  konsistent:** Modern-Pool N=4 (92 Features inkl. Gravity) zeigt Tree-Modelle
  +3.8–5.0 pp mit deutlich schrumpfender Fold-σ, aber N=4 ist für den Wilcoxon
  strukturell unterpowert (min erreichbares p=0.125) — corroborating, nicht
  confirming. Der Gewinn sitzt bei **5–10 s** Latenz (10 s noch p<0.001) und
  konvergiert bei 30 s gegen die Baseline (acc-Δ n.s., AUC-Δ noch signifikant).
  Per-Fold: **P09 (Soft-Writer) +0.057 größter Gewinner** (5-s-Fenster mittelt
  Mikropausen *im* Feature weg), **P07 (Denkpausen) einzige echte Regression
  −0.038** (längeres Fenster + 60%-Regel schmiert lange Idle-Stretches
  Richtung writing) — exakte Bestätigung der P07/P09-Failure-Mode-Dichotomie.
  **Noch NICHT adoptiert:** Live-Inference (`_window_features`) + deployte
  Joblibs rechnen weiter auf 1 s; ein Headline-Wechsel müsste durch
  `inference.py` + Retraining gezogen werden und kostet 1-s-Zeitauflösung.
- `scripts/ml/ablate_gap_loso.py` — Label-Closing-**Sensitivitätsanalyse**:
  fährt den vollen LOSO-Lauf bei mehreren `max_gap_ms`-Werten und reportiert
  per-Fold + Mean/Std. **Methodik-Hinweis (Reviewer 2026-06-11):** `max_gap_ms`
  ist *nicht* per nested CV auf dem Test-Fold optimiert — das wäre Test-Set-
  Tuning. Der Wert ist **a-priori durch die Label-Semantik fixiert**
  (Schreibmodus inkl. Mikropausen ≤ 2.5 s = die User-facing-Wahrheit eines
  Schreibzeit-Trackers, siehe *Label smoothing* unten), und dieser Sweep ist
  eine **Robustheits-/Sensitivitätsprüfung** der Wahl, kein Selektions-
  kriterium. Die gemessenen Effekte (gap 2000→2500: +0.4 pp acc) liegen
  ohnehin innerhalb der Fold-σ (~3.4 pp) und sind ohne gepaarten Test
  (`src/evaluation/significance.py`) nicht als Gewinn zu lesen.
- `scripts/ml/label_kinematics_check.py` — falsifiziert den Varianz-
  Alignment-Bias-Verdacht: pooled writing-vs-idle Jerk/Varianz (Kern
  `src/evaluation/label_diagnostics.py::class_kinematics_summary`). Befund:
  8/8 Jerk-Features bei writing höher (Median-Ratio 1.35) → Schreiben ist
  die dynamischere Klasse, Labels nicht auf Ruhephasen invertiert (siehe
  *Sample-level merge alignment* oben). Kein Ersatz für Video-Ground-Truth.
- `scripts/ml/sync_audit.py` — Sync-Audit: prüft, ob residualer Pen↔Watch-
  Alignment-Fehler die LOSO-Fehlerdecke erklärt. Drei Teiltests: (A) σ ↔
  Fold-Accuracy-Korrelation, (B) δ-Drift erste vs. zweite Session-Hälfte
  + Drift↔Accuracy-Korrelation, (C) Label-Kippung bei ±50 ms δ-Störung.
  Ergebnis (2026-05-22): r(σ,acc)=−0.22, r(Drift,acc)=−0.18 — beide
  null/falsch-vorzeichig; Sync erklärt die Decke **nicht**, die Diagnose
  „echte Signal-Mehrdeutigkeit" bleibt. Output: `reports/sync_audit.md` +
  `models/sync_audit.csv`.
- `scripts/ml/per_subject_threshold.py` — testet leakage-frei, ob ein
  per-Person kalibrierter Entscheidungs-Schwellwert (statt global 0.5) die
  schwachen Folds hebt. Eichphase = erstes Session-Drittel; Eval = restliche
  2/3; Oracle-Spalte als Leakage-Obergrenze. Ergebnis (2026-05-22): hilft
  nicht (F1w 0.858→0.846, Oracle nur +0.007) — widerlegt die „P09 braucht
  Per-Subject-Threshold"-Hypothese. Output: `reports/per_subject_threshold.md`
  + `models/per_subject_threshold.csv`. Siehe *Negative result* unten.
- `scripts/ml/train_noah_personal.py` — Personal-Modell für die Focus-
  Tracker-Live-App. Trainiert RF auf Noahs 100-Hz-Sessions (S032 + S033),
  A/B mit/ohne Z-Score (datengetrieben entschieden — Δ AUC = 0.000, daher
  ohne). Speichert `models/rf_noah.joblib` mit `person_id`, `sample_rate_hz`,
  optional `zscore_mu/sigma` als Metadata. Within-Noah-LOSO: acc 0.878,
  AUC 0.939, @5s AUC 0.973, @30s AUC 0.949 (post Sort-Stability-Fix).
- `scripts/ml/honest_live_loso.py` — misst die ehrliche, deploybare
  Live-Zahl: fährt denselben LOSO zweimal (per-Session-Z-Score vs.
  leak-frei pooled via `_zscore_train_pooled`) und testet die Differenz
  gepaart (Wilcoxon). Ergebnis 2026-06-11: pooled 0.863 ≥ per-session
  0.855 — der nicht-kausale per-Session-Z-Score inflationiert *nicht*
  (siehe *Per-session z-score* unten).
- `scripts/ml/train_rf_all_live.py` — Deployment-Variante des
  Generic-Modells. Lädt alle 10 LOSO-Probanden, berechnet **pooled** mu/
  sigma (statt per-session — Pooled ist live-deployment-fähig, weil das
  μ/σ ins Joblib eingebacken wird und keine Calibration-Phase pro Session
  braucht). Speichert `models/rf_all_live.joblib`. LOSO-Headline-Artefakt
  `rf_all.joblib` bleibt unangetastet (per-session Z-Score, nicht
  live-tauglich).
- `scripts/ml/replay_live_inference.py` — Diagnose-Tool: füttert eine
  bekannte Watch-CSV Sample-für-Sample durch `LiveInference` und
  vergleicht Predictions mit den gespeicherten Window-Labels. Quelle der
  Sort-Stability-Bug-Diagnose 2026-05-25 (acc 0.573 vs offline 0.876 bei
  bug-affected Modell → identifizierte Feature-Distribution-Mismatch).
- `scripts/ml/diff_live_features.py` — Detail-Diagnose: berechnet Features
  über `build_windows`-Pfad vs. `_window_features`-Live-Pfad, diffed
  per-Feature über alle Windows. Lokalisiert *welche* Features
  divergieren (Sort-Stability-Bug: FFT/Jerk/ZCR/Korrelationen).
- `src/evaluation/evaluate.py` — placeholder that loads
  `{session}_merged.csv` and prints label distribution. Real metrics
  live in `train_loso.py` (cross-subject) and
  `within_session/train_rf.py` (within-session sanity check).
- `src/evaluation/significance.py` — gepaarte Signifikanztests auf
  Per-Fold-Metriken (`paired_fold_test()` = Wilcoxon signed-rank auf den
  paarweisen Fold-Differenzen; beide Configs auf denselben Personen
  ausgewertet). CLI `python -m src.evaluation.significance A.csv B.csv
  [--metric accuracy]` vergleicht zwei `loso_cv.csv` auf gemeinsamen
  `held_out`-Folds. **Pflicht-Gate** vor jeder „+X pp"-Behauptung: bei
  Fold-σ ≈ 3.4 pp sind sub-pp-Gewinne ohne p < 0.05 Rauschen. Greift nur
  für Within-Kohorten-A/Bs (gap, Z-Score, Gravity, center/causal) —
  Cross-Kohorten-Vergleiche (N=7 vs N=14) sind nicht paarbar.
- `src/evaluation/regression.py` — Schreib-Prozent-Regression (Stufe 2).
  Reines Post-Processing über `models/loso_oof.csv`: aggregiert die
  OOF-Vorhersagen auf 60 s / 300 s / ganze-Session-Blöcke und reportet
  MAE/RMSE/Bias gegen geschlossene und rohe Pen-Wahrheit, plus
  Calibration- und Scatter-Plot in `reports/figures/`. `pred_pct` ist
  der **binäre** Schätzer `mean(proba_cal ≥ 0.5)` — das Mitteln roher
  Wahrscheinlichkeiten (`pred_pct_proba`) schrumpft zur Mitte (~53 %)
  und generalisiert nicht auf schiefe Schreibanteile (siehe
  `reports/regression.md`, Abschnitt „Shrinkage"). Headline binär:
  Session-MAE 4,5 pp, 60 s 8,6 pp (N=14 seit 2026-06-10; bei N=10
  waren es 3,5 / 7,6 pp — Verschiebung durch die härtere Kohorte,
  nicht durch Modell-Änderung). Der `evaluate()`-Output trennt
  zwei beschriftete Abschnitte: **HEADLINE** (truth = `closed`
  labels, = Modell-Labels mit Mikropausen ≤2,5 s als writing) und
  **DIAGNOSTIC** (truth = rohe Pen-Down-Samples). `regression_metrics.csv`
  trägt dafür eine `role`-Spalte (`headline`/`diagnostic`). Wichtig:
  der Diagnostic-Bias (~+21 pp) ist der inhärente Label-Closing-Bias
  unserer Politik, **kein Modellfehler** — nur Headline ist die
  vorzeigbare Aussage.
- `src/evaluation/engagement.py` — Engagement-Auswertung (Stufe 2,
  Prio 2). Reines Post-Processing über `models/loso_oof.csv` + den
  Study-Mode-`markers`-CSVs. Ordnet jedes 1-s-Fenster über `t_center_ms`
  einem Task-Block zu (`task_start`/`task_end` aus den Markern) und
  aggregiert pro `(Session, Task)` den Schreibzeit-Anteil: `true_pct`
  (geschlossene Labels) und `pred_pct` (binärer Schätzer, geteilt mit
  `regression.py` via `block_percentages()`). Output:
  `models/engagement_metrics.csv` (1 Zeile pro Task-Block, Schreib-Tasks
  + Pausen als Kontrolle) plus `reports/figures/engagement_heatmap.png`
  (Proband × Task). Der Wert ist ein **Engagement-Proxy**, kein
  Aufmerksamkeits-Detektor — Schreibzeit ≠ Aufmerksamkeit.
- `scripts/plots/plot_merged.py` — visualizes ‖acc‖, ‖gyro‖, and
  `label_writing` over the session; supports `--max-gap-ms` /
  `--max-spike-ms` to preview label smoothing effects.

The merge skips the δ shift when the alignment confidence is weak
(`sigma_minimal_variance > -2`); the quality engine surfaces this as
`low_sync_confidence` (warn) and `sync_failed` (bad). Older pen logs
without `local_ts_ms` cannot be aligned and are flagged as
`legacy_pen_time`.

## Data Schemas

**Watch CSV** (`data/raw/watch/{session}_watch.csv`):
```
local_ts, local_ts_ms, session_id, sequence, sample_rate_hz,
watch_sent_at, phone_received_at, server_received_ms, source,
ts, ax, ay, az, rx, ry, rz,
gx, gy, gz,    # Modern-Pool only (ab 2026-05-26); leer für Legacy-Sessions
qx, qy, qz, qw # Attitude-Quaternion (forward-only); leer für Pre-Quat-Sessions
```

`ax/ay/az` sind weiterhin `motion.userAcceleration` (ohne g). `gx/gy/gz`
sind `motion.gravity` separat, Modern-Pool-Sessions ab 2026-05-26.
Total acceleration = `(ax+gx, ay+gy, az+gz)` jederzeit ableitbar. `qx/qy/qz/qw`
sind `motion.attitude.quaternion` (hardware-fusionierte Handgelenk-Orientierung),
**forward-only Capture** — passive Metadaten, vom ML/Feature-Set (windows.py)
nicht genutzt; reserviert fürs spätere 3D-Replay. Siehe *Pool architecture* unten.

**Pen CSV** (`data/raw/pen/{session}_pen.csv`):
```
local_ts, local_ts_ms, timestamp, x, y, pressure, dot_type,
tilt_x, tilt_y, section, owner, note, page
```
`dot_type` ∈ {`PEN_DOWN`, `PEN_MOVE`, `PEN_UP`, `PEN_HOVER`}. Rows with
`x == -1` and `y == -1` are framing events (no position) — filter
them out before spatial analysis. `label_writing` is derived as 1 for
`PEN_DOWN`/`PEN_MOVE`, else 0. Schema is defined in
`src/pen_schema.py` (shared with `pen_logger.py`).

**AirPods CSV** (`data/raw/airpods/{session}_airpods.csv`):
```
local_ts, local_ts_ms, session_id, sequence, sample_rate_hz,
airpods_sent_at, phone_received_at, server_received_ms, source,
ts, ax, ay, az, rx, ry, rz, qw, qx, qy, qz, gx, gy, gz
```
Head-IMU stream from `CMHeadphoneMotionManager`: accel + gyro +
attitude quaternion + gravity vector. Currently logged only.

**Sessions index** (`data/sessions.csv` — **gitignored**, owned by
the running server, derivable from `data/raw/`):
```
session_id, person_id, description, start_time, end_time,
pen_samples, watch_samples, airpods_samples, status,
study_mode, protocol_id, subject_index
```
- `study_mode` ∈ {`free`, `study`, `test`}. `free` = legacy manual
  recording; `study` = run under a study protocol; `test` = study
  protocol run flagged not-for-analysis (pilot/dry-run).
- `protocol_id` — id of the protocol JSON in `study_protocols/` (e.g.
  `v1`); empty for `free` sessions.
- `subject_index` — 0-indexed counterbalancing index used to pick the
  Latin-Square row for this proband. Auto-assigned via
  `_subject_index_for_person_id(person_id)`, which **counts only prior
  sessions with `study_mode='study'`** for that person — `test` and
  `free` are skipped so pilot runs do not consume a counterbalance
  slot. `balanced_latin_square(n)` in `src/server/study.py` generates a
  Williams-design square sized to the protocol's writing-task count
  (even n → n rows, odd n → 2n); the row is picked by
  `(subject_index - 1) % len(square)`. v1 (3 tasks) and v2 (6 tasks)
  both cycle every 6 subjects.

Session IDs auto-increment (`S001`, `S002`, …). `_next_session_id()`
scans **sessions.csv** and `data/raw/{pen,watch,airpods}/` so an ID
can never be reused while a stale per-session CSV is still on disk.

`sessions.csv` was previously checked in but is **now gitignored**
after a data-loss incident where switching git branches reset it. The
server fully owns the file; any environment can reconstruct it by
scanning `data/raw/`.

**Markers CSV** (`data/raw/markers/{session_id}_markers.csv`): one
row per Study-Mode state transition. Schema:
```
timestamp_ms, event, task_id, task_name, task_index, task_category,
protocol_id
```
Events: `study_start`, `task_start`, `task_end`, `study_end`, `abort`.
There are **no** `pause_start`/`pause_end` events — pauses are ordinary
task blocks (`task_id='pause'`, `task_category='idle'`) delimited by
their own `task_start`/`task_end`. A task block is thus a `task_start`
paired with the matching `task_end` (same `task_index`).
`timestamp_ms` is Unix-ms wall clock — the **same epoch** as the watch
CSV's `local_ts_ms` / `server_received_ms` (the server stamps both).
Seit dem *Capture-Clock-Fix* liegt `t_center_ms` auf der Watch-`ts`-Uhr
(NTP-nah, < 100 ms Skew ggü. der Server-Uhr) statt auf `local_ts_ms` —
für Minuten-lange Task-Blöcke vernachlässigbar, daher bleibt die
Marker→Window-Zuordnung ohne Offset-Korrektur gültig. The marker stream
is the ground-truth timeline
for downstream per-task analyses and lets the training/evaluation
pipeline filter windows by task category.

**Merged CSV** (`data/processed/{session}_merged.csv`): **watch-base**
— every watch sample is preserved, with `label_writing` ∈ {0, 1}
assigned from the nearest pen `dot_type` within ±40 ms of the
δ-corrected pen wall-clock. Watch samples in pen-gaps → label 0 (the
"not writing" negative class). Schema = all watch CSV columns +
`label_writing`. Server/local timestamps are capture metadata, not the
canonical ML timeline.

**Windows CSV** (`data/processed/windows/{profil}/{session}_windows.csv`,
Profil ∈ {`50hz`, `100hz`, `100hz_grav`} — siehe *Profil-sortierte
Windows* oben): 1 row per 1 s sliding window (0.5 s stride),
88/92 features + `label` + `t_center_ms`. Labels are smoothed at
sample level before windowing (see *Label smoothing* below).

**Inference log** (`data/inference_log.csv` — **gitignored**, owned
by the running server): append-only CSV of every 1-Hz Live-Inference
tick aus `_status_loop`. Schema:
```
ts_ms, proba, writing, model_id, fs_hz
```
`ts_ms` = `int(time.time() * 1000)` (server wall clock, same epoch as
watch.local_ts_ms). `rate_mismatch`-Ticks werden **nicht** geschrieben
(sonst stehen 0.0-Probas im Log, die ein "writing time tracked"-Counter
fälschlich als idle-Zeit zählen würde). Wächst ~3 MB/Tag bei
dauerhaftem Streaming. Read-Side: `src/server/routes/focus.py`
aggregiert pro Tag/Woche on-demand (kein Cache).

## Pool architecture (Legacy vs Modern)

Seit 2026-05-26 unterscheidet die Pipeline zwei Watch-Daten-Pools:

| Pool | Hz | Werte/Sample | Features/Window | Inhalt |
|---|---:|---:|---:|---|
| **Legacy** | 50 | 6 (ax/ay/az + rx/ry/rz) | 88 | Die 10 LOSO-Probanden + Vorgeschichte |
| **Transition** | 100 | 6 | 88 | S032, S033 (Noah-Selbsttests vor dem Gravity-Fix) |
| **Modern** | 100 | 9 (6 Sensor-Achsen + gx/gy/gz) | 92 | Alle Sessions ab 2026-05-26 |

**Gravity ist kein eigener Sensor-Kanal.** Die Watch hat 6 unabhängige
Sensor-Achsen: 3-Achsen-`userAcceleration` + 3-Achsen-`rotationRate`.
`gx/gy/gz` ist die von CoreMotion abgespaltene Schwerkraft-Komponente
*desselben* Beschleunigungssensors (`userAcceleration + gravity =
Gesamtbeschleunigung`), keine zusätzliche Messung. Modern speichert diese
Komponente zusätzlich, statt sie wie Legacy zu verwerfen — die „9" sind
also **9 Werte pro Sample, nicht 9 Kanäle**. Der Informationsgewinn ist
allein die rekonstruierbare Wrist-Orientierung relativ zur Schwerkraft
(→ 4 Tilt-Features), nicht ein drittes Sensor-Tripel.

**Warum zwei Pools statt einer:** Review-Feedback aus der
Zwischenpräsentation ergab, dass `userAcceleration` ohne `gravity` einen
Teil der nützlichen Information verschenkt — die Wrist-Orientierung relativ zur Schwerkraft
ist informativ für Schreiben. Modern-Pool capture jetzt
`motion.gravity` separat (`MotionManager.swift`, ab Commit 07577a9).
Alte Sessions haben kein Gravity (kann nicht retro-imputiert werden).

**Pool-Detection ist runtime-derived**, kein neuer sessions.csv-Eintrag:
- `_load_watch_timeline` parsed `gx/gy/gz` wenn Spalten existieren,
  setzt `has_gravity`/`grav_mag` pro Row
- `_session_facts` aggregiert `gravity_rows`, `/sessions/{id}/report`
  exponiert `has_gravity` + `pool` ("legacy" | "modern")
- `build_windows` detektiert die Spalten in `merged.csv` und hängt
  4 zusätzliche gravity-Features an (`tilt_x/y/z_mean`, `tilt_change`
  — siehe `src/features/gravity.py`). `grav_mag_mean/std` wurden
  2026-05-29 gestrichen: `motion.gravity` ist ein Einheitsvektor
  (‖g‖ ≈ 1.000), die Magnitude hat null Varianz und trug im
  S038-Within-Session-RF exakt 0.0 Importance (Rang #93/#94)
- `tilt_change` ist der **Winkel zwischen aufeinanderfolgenden
  Gravity-Vektoren** (`arccos(dot(g_i, g_i+1) / (|g_i|·|g_i+1|))`),
  *nicht* der Per-Achsen-Mittelwert — letzteres unterschätzt Rotationen
  systematisch um Faktor ~0.66

**LOSO Pool-Selection** via `train_loso.py --pool {auto,legacy,modern}`:
- `auto` (default): include all sessions; wenn gemischt → gravity-
  Spalten global gedropt (NaN-Padding vom concat würde sonst RF.fit
  crashen)
- `legacy`: nur Legacy-Sessions, 88 Features. Bestehende Headline.
- `modern`: nur Modern-Sessions mit voller Gravity-Coverage, 92 Features

Bei `--pool != auto` werden `--save-final-model`/`--save-cv-csv`/
`--save-oof` automatisch in `*_modern.*` / `*_legacy.*`-Sibling
gespeichert — damit das generische `rf_all.joblib` (von Live-Inference
+ Regression + Engagement konsumiert) nicht stillschweigend mit einem
pool-spezifischen Modell überschrieben wird.

**Cross-Pool-Mixing — vollständige Bash-Chain:**
```bash
# 1. Modern-Session (100 Hz, 9 Werte/Sample inkl. Gravity) zu Legacy-Format umwandeln
python -m src.features.downsample S034 --target-hz 50
#   → data/raw/watch/S034_watch_legacy.csv  (50 Hz, ohne gx/gy/gz)

# 2. Merge auf die Legacy-Variante laufen lassen
python -m src.merge S034 --watch-suffix legacy
#   → data/processed/S034_merged_legacy.csv

# 3. Features auf die View bauen — landet automatisch im 50hz-Ordner,
#    die native Modern-windows.csv bleibt unangetastet:
python -m src.features S034 --merged-suffix legacy
#   → data/processed/windows/50hz/S034_windows.csv

# 4. LOSO im Legacy-Pool-Modus — lädt windows/50hz/ und nimmt die View
#    damit automatisch in den Legacy-Pool auf
python -m src.training.train_loso --pool legacy
```

**Profil-sortierte Windows (seit 2026-06-10).** Window-CSVs leben unter
`data/processed/windows/{50hz,100hz,100hz_grav}/` statt flach —
eine Modern-Session koexistiert kollisionsfrei nativ (`100hz_grav/`)
und als Legacy-View (`50hz/`). Single Source of Truth ist
`src/profiles.py` (+ `tests/test_profiles.py`): `windows_path()` /
`find_windows()` (native Auflösung = höchste Fidelity zuerst, Flat-
Fallback mit Warnung), `detect_profile()` / `profile_for()` (Form aus
Inhalt — robust gegen Legacy-`ts` in ms und batch-rückwärts sortierte
Samples), `python -m src.profiles` migriert flache Bestandsdateien.
Der Pool wählt das Profil in `train_loso` (`legacy`→`50hz`,
`modern`→`100hz_grav`, `auto`→nativ). sessions.csv trägt die native
Form in der Spalte `watch_profile` (gleiche Vokabel; geschrieben von
`_session_quality_cols` bei Stop/Refresh, migrate-on-read für
Bestand).
Anti-aliased decimate (scipy.signal.decimate, 8th-order Chebyshev I,
`zero_phase=True` für Zeitversatz-Vermeidung beim Pen-Alignment) +
optional gravity-Spalten-Drop. Default-Output:
`{session}_watch_legacy.csv`. Damit kann eine Modern-Session als
Legacy-View behandelt werden — z. B. um sie im 10-Probanden-LOSO-Pool
mittrainieren zu können.

**Live-Inference Gravity-Support (Modern-Pool, seit 2026-05-29).**
`src/server/inference.py::append_sample` nimmt jetzt optional `gx/gy/gz`
(Gravity) als 7.–9. Argument; der Rolling-Buffer führt 10-Tupel
`(ts, ax..rz, gx, gy, gz)` (Gravity in **derselben** Tuple — strukturelle
Alignment-Garantie gegen die Sort-Stability-Bug-Klasse). `predict()`
erkennt ein Modern-Modell über `set(GRAVITY_FEATURE_NAMES).issubset(
feature_cols)` und komponiert dann via `_extract_features()` die vollen
92 Features (`_window_features` + `_gravity_window_features`, identisch
zum `build_windows`-Trainingspfad — Paritäts-Test in
`tests/test_inference.py`). Legacy-Streams ohne Gravity speichern NaN;
ein Modern-Modell auf so einem Stream short-circuited mit Payload
`{missing_channels: true}` (kein Predict auf NaN, analog zum
`rate_mismatch`-Guard), ein Legacy-Modell ignoriert die Extra-Spalten.
**Verbleibender Schritt zum Deployment:** es existiert noch **kein**
Modern-Joblib in `models/` — sobald eins trainiert ist (`train_loso.py
--pool modern --save-final-model` → `rf_all_modern.joblib`), muss sein
Stem zur Picker-Whitelist `_USER_FACING_MODEL_NAMES` in
`src/server/inference.py` hinzugefügt werden, damit es im UI-Switcher
auftaucht. **Gravity-Verdikt (2026-06-10, Modern-LOSO N=4, gepaartes
92-vs-88-A/B via `--drop-gravity`):** cross-subject hilft Gravity
nicht (Δacc −0.005, ΔAUC −0.003; P14 regrediert −3.8 pp durch
Pose-Idiosynkrasie), within-subject bleibt der Befund positiv —
Gravity ist ein Personalisierungs-Signal, kein Generalisierungs-
Signal. Details `reports/feature_ablation.md`. Capture läuft
unverändert weiter (nicht retro-imputierbar, revidierbar ab N≥6).

**Was wo lebt:**
- `src/profiles.py` (+ `tests/test_profiles.py`): watch_profile-
  Taxonomie, Windows-Pfad-Resolver, Profil-Detection, Flat-Migration
- `src/features/gravity.py` (+ `tests/test_gravity.py`): 4 Gravity-
  Features (`tilt_x/y/z_mean`, `tilt_change`), vektor-winkel-basiert
- `src/features/downsample.py` (+ `tests/test_downsample.py`):
  Cross-Pool-Bridge
- `src/training/train_loso.py::_filter_pool` (+ `tests/test_train_loso_pool.py`):
  Pool-Selection (+ `_profile_for_pool`: Pool → Windows-Ordner)
- `src/server/{config,models,routes/watch,timelines,quality}.py`:
  Schema + Detection runtime-side

## Study Mode

End-to-end protocol runner so recordings happen under a consistent,
counterbalanced script rather than free-form. Lives in
`src/server/study.py` (pure logic) + `src/server/routes/study.py`
(HTTP) + `static/js/pages/recording-study.js` (UI).

**Protocol definition.** A protocol JSON defines tasks
(id, label, category ∈ {`writing`, `idle`}, duration, instances,
instruction, content_type ∈ {`text`, `list`, `image`}, content),
plus `pre_task_seconds`, `randomize`, `duration_jitter_pct`, and
`interleave` mode. `load_protocol(path)` validates against the Pydantic
schema. **`v2.json` is the current default** (server default in
`StudyStartBody.protocol_id` + pre-selected in the dashboard dropdown);
`v1.json` stays available for reproduction of the legacy cohort.

**v2 — "Hard Negatives & Edge Cases" (current SOTA).** Targets the two
documented failure modes head-on with dedicated writing variants —
`soft_writing` (→ the P09 soft-writer class) and `think_pause_writing`
(→ P07's long Denkpausen) — plus `drawing`, and a battery of **hard
negatives** in the `idle` class designed to look writing-like on the
wrist IMU: `phone_typing`, `phone_scrolling`, `keyboard_typing`,
`pen_fidgeting` (the documented phone-typing/fidget confound), and
`gesturing`. 6 writing + 6 idle tasks, `duration_jitter_pct=0.15`
(±15 % sum-preserving). Net schedule W-I-W-I… (~26.5 min) — notably
longer than v1's ~15 min. Both the 6 writing tasks **and** the 6 idle
hard-negatives are counterbalanced per subject (see Scheduler), so the
W-I pairings vary — which is where the carryover balance actually bites,
since writing tasks are never adjacent in the interleaved run.

**Scheduler.** Three `interleave` modes are supported. `latin_square`
generates a **balanced Williams Latin square sized to the task count**
(`balanced_latin_square(n)`) and applies it — by `subject_index` — to
**both** the writing tasks and the idle blocks, then interleaves them.
This scales to any protocol: v1's 3 writing tasks and v2's 6 both get a
proper counterbalance (no special-casing, no random fallback when a
`subject_index` is present). v1's writing tasks are `abschreiben`
(text copy), `math`, `free_writing` — each 240 s — separated by pause
blocks (W-P-W-P-W, ~15 min). v2 weaves its 6 writing + 6 idle tasks
into W-I-W-I… (~26.5 min).

**State machine.** `new_runtime(protocol, subject_index)` constructs
the ordered task list; `state.study` tracks `phase`,
`current_task_idx`, `task_started_ms`. `/study/next` advances,
`/study/pause` flips to/from `paused`, `/study/abort` terminates
and writes a `study_end` marker. Markers are written via
`write_marker()` (`csv_io.py`) on every transition.

**Test mode.** `POST /study/start` with `test_mode=true`:
- prefixes the description with `[TEST] `,
- writes `study_mode='test'` to sessions.csv,
- **skips Latin Square** (random shuffle fallback instead).
Existing sessions can be flipped retroactively via
`POST /sessions/{id}/mark-test` (the dashboard exposes this).

## Quality Checks

`/sessions/quality` returns separate `ml_readiness` and
`recording_health` scores. Issues come from `ISSUE_SPECS` in
`src/server/issues.py` (re-exported by `quality.py` for back-compat) —
each issue has `code`, `check`, `threshold`, `observed`, `rationale`,
plus `ml_severity` and `recording_severity`. Sync confidence is a
calibration diagnostic only — it must not downgrade a session by itself.

Notable issues:
- `data_outside_session_window` — fires when watch- or pen-CSV
  timestamps fall more than 60 s before `start_time` or after `end_time`.
  Catches stale CSVs being appended to a recycled session ID.
- `streams_do_not_overlap` — pen and watch wall-clock ranges don't
  overlap.
- `legacy_pen_time` / `legacy_watch_time` — old CSVs missing
  `local_ts_ms` / `server_received_ms`.
- `low_watch_coverage` — fewer rows than `(50 or 100) Hz × duration`.
  Effektiver Target per Session per Nearest-Match aus `_VALID_WATCH_HZ`
  in `src/server/issues.py` (siehe `watch_target_hz()` helper).
- `pen_clock_mismatch` — info-only; pen device clock is typically
  ~922 days behind wall clock.

**Sample-rate target:** the watch streams at 50 oder 100 Hz
(`MotionManager.Config.requestedHz`, per Phone-App konfigurierbar).
Quality-Check ermittelt den Target per Session via Nearest-Match aus
`_VALID_WATCH_HZ = (50.0, 100.0)` und akzeptiert ±20 % darum. Beide
Baender ([40-60] und [80-120] Hz) gelten als valide, der Bereich
[60-80] Hz faellt durch. Erweitern: einen Wert in `_VALID_WATCH_HZ`
ergaenzen. AirPods bleiben hard-coded `_TARGET_AIRPODS_HZ=25`.

**Sample-level merge alignment:** pen and watch device clocks do not
share an epoch (typical Moleskine pen offset: ~922 days plus an
arbitrary time-of-day shift). Session-level overlap uses wall-clock
`local_ts_ms`. For sample-level merging the per-session offset δ is
recovered automatically by the **stroke-variance alignment** in
`src/alignment/pen_match.py` — a port of the ETH Zürich algorithm
(see `data/02_Pen_IMU_Timestamp_Alignment.pdf`). Physical assumption:
while the pen is on paper, the wrist holding the watch is comparatively
still, so the correct δ minimizes the mean watch-acceleration variance
under the shifted stroke mask. The search runs coarse (±20 s @ 0.5 s)
then fine (±5 s @ 10 ms); confidence is reported as
`sigma_minimal_variance` (z-score of the minimum vs the search-grid
distribution — more negative = stronger). `merge_watch_pen()` applies
δ to `pen.local_ts_ms` before the `merge_asof` join and skips the
shift when `sigma > -2`. This replaced the planned tap-sync recording
protocol — no special user action at session start is required.

**Reviewer-Verdacht #3 (2026-06-11) — „Varianz-Minimierung mappt Schreiben
auf Ruhephasen, Labels invertiert" — empirisch widerlegt.** Wichtige
Unterscheidung: die Minimierung nutzt die *grobe Handgelenk-Translations*-
Varianz, um den **Offset δ** zu finden (das Handgelenk transliert beim
Schreiben weniger als beim Greifen/Umblättern/Gestikulieren *zwischen* den
Strokes). „Geringer als grobe Bewegung" ≠ „Ruhe": die so gelabelten
Schreib-Fenster tragen die *höchste* Fein-Motor-Dynamik.
`scripts/ml/label_kinematics_check.py` (pooled über alle Legacy-Windows)
zeigt: **8/8 Jerk-Features sind bei writing höher als bei idle, Median-Ratio
1.35** (z. B. `ay_jerk_mean_abs` 2.49 vs 1.57). Schreiben ist die
*dynamischere* Klasse — die Labels sind nicht auf ruhige Phasen invertiert.
Stützt auch die Pause-FPR ≈ 0.01 (Marker-Analyse): wäre „still = Schreiben"
gelernt, würden die ruhigen Pausen massiv false-positiv. **Caveat:** das ist
die reproduzierbare Falsifikation der *Konsequenz* des Verdachts, **kein**
Ersatz für eine manuelle Video-Ground-Truth (Reviewer-Fix #5, Gold-Standard
— bleibt ein offener manueller Schritt).

## ML pipeline gotchas

**Capture-Clock-Fix (entdeckt + gefixt 2026-06-13).** Merge (`merge.py`)
und Window-Bau (`windows.py`) joinen Pen-Labels / berechnen `t_center_ms`
und Label-Closing-Gaps jetzt auf der per-Sample-Watch-Uhr **`ts`**, nicht
mehr auf der Batch-Ankunftszeit `local_ts_ms`. Zwei Defekte von
`local_ts_ms`: (1) **batch-quantisiert** — alle Samples eines `POST /watch`
teilen einen Wert (Server-Receive-Time), Labels waren in ~200–400-ms-Blöcke
gerastert; (2) **Spill-Drain-Verspätung** — bei WLAN-Hängern liefert der
Watch-Spill Samples Minuten verspätet nach (`watch_sent_at` korrekt,
`local_ts_ms` Minuten zu spät), wodurch Pen-Labels zeitversetzten
Watch-Samples zugeordnet wurden. Messung: S019/P07 33 % der Samples >2,5 s
versetzt (max 42 s), S043/P17 5,3 % (max 13,6 s); Legacy-Sessions ohne
Stalls praktisch 0 %. **Wichtig:** δ wurde schon immer gegen `ts` optimiert
(`reconstruct_watch_wall_clock` in `pen_match.py`) — der Join lief aber auf
`local_ts_ms`, also auf einer *anderen* Achse als die Alignment-Schätzung.
Der Fix vereinheitlicht beide auf `ts` (Fallback `local_ts_ms` nur ohne
ts-Spalte; intern `_wall_ms`-Hilfsspalte, wird vor Return gedroppt). Gepaarter
Vorher/Nachher-Lauf (Wilcoxon, N=15 Legacy): **15/15 Folds besser, mean
+2,4 pp acc, p = 0,0001** (acc/AUC/F1); P07 +8,5 pp acc / +9,3 pp AUC.
Alle vor 2026-06-13 berechneten Zahlen (inkl. Deep/harnet/Fusion/Window-Sweep)
liefen auf `local_ts_ms` und sind regenerations-pflichtig; relative
Within-Kohorten-Vergleiche bleiben grob gültig (Defekt war symmetrisch in
Train/Test), aber die schwachen Folds (P07!) waren überproportional betroffen.
Tests: `test_late_arriving_samples_labelled_by_capture_time` (merge),
`test_t_center_and_closing_follow_capture_clock` (windows).

**Sort-Stability-Bug (entdeckt + gefixt 2026-05-25).** `pandas.sort_values`
ist per Default **nicht stabil** (`kind='quicksort'` historisch). Watch-
Samples in einem Batch teilen sich dieselbe `local_ts_ms` (Server-Receive-
Time pro POST), bei Disk-Spill-Drain sind das bis zu 30 Samples
gleichzeitig. Unstable sort permutierte die Reihenfolge innerhalb dieser
Ties zufällig, was alle order-sensitiven Features (FFT, Jerk, ZCR,
Korrelationen — ~52 % des 88-Feature-Vektors) zwischen Trainings-Pipeline
und Live-Inferenz divergent machte. Tests waren grün (beide Seiten gleich
gescrambled), aber Live-Deployment auf nicht-gescrambled Samples
zeigte AUC bleibend hoch (0.96 — Ranking funktioniert) und Acc kollabiert
(0.57 — Decisions falsch, alle Schreib-Probas unter 0.5 geschoben).
**Fix:** `kind='stable'` in `merge.py` + sortieren nach per-Sample-`ts`
in `windows.py` statt nach `local_ts_ms`. Impact auf Headline: +0.7 pp
Acc / +0.7 pp AUC systematisch über alle Skalen. Alle relativen
Vergleiche (gap-Sweep, N-Verlauf, Sync-Audit, Per-Subject-Threshold)
bleiben gültig — Bug war symmetrisch in Train- und Test-Daten. **Diagnose-
Tools** für ähnliche zukünftige Bugs: `scripts/ml/replay_live_inference.py`
(simuliert Live über bekannte CSV) und `scripts/ml/diff_live_features.py`
(per-Feature-Vergleich Train- vs. Live-Pipeline). Forensik:
[`reports/sort_stability_bug.md`](reports/sort_stability_bug.md).

**Label smoothing (morphological closing).** The pen reports DOWN/MOVE
only while in contact / near the paper. Between letters, across word
boundaries and during short denkpausen there are 50 ms–2 s gaps where
the pen is briefly lifted — the writer is still in *writing mode* but
the raw pen label flips to 0, and the watch IMU during those gaps
looks identical to the surrounding strokes. Without smoothing the
model sees the same wrist motion with contradictory labels and learns
ambivalence. **Chosen closing (headline pipeline):** `max_gap_ms=2500` —
idle runs ≤ 2.5 s between writing runs are flipped to writing.
**Methodisch (Reviewer 2026-06-11):** dieser Wert ist eine *a-priori
Label-Definition* (welche Mikropausen noch „Schreibmodus" sind), **nicht**
ein auf dem Test-Fold getunter Hyperparameter. Der `ablate_gap_loso`-Sweep
unten ist die Sensitivitätsprüfung dieser Wahl (zeigt: robust, Effekte
innerhalb Fold-σ), kein nested-CV-Selektor. Für eine streng leakage-freie
Modell-Hyperparameter-Suche (z. B. RF-Tiefe) gälte das *nicht* — dann wäre
nested CV Pflicht; `max_gap_ms` ist aber ein Label-Politik-Knopf, kein
Modellgewicht.
Code-Default in `build_windows()` + `smooth_labels()` ist seit
2026-05-25-Audit auch `2500` (vorher 300 ms — siehe ML-Gotcha
"Default-Drift" und [`reports/sort_stability_bug.md`](reports/sort_stability_bug.md)
für den Kontext-Audit der diesen Drift aufgedeckt hat). Semantik:
damit detektiert das Modell "Person ist im Schreibmodus" (inkl.
Mikropausen ≤ 2.5 s) und nicht "Pen aktuell auf Papier". Für einen
Schreibzeit-Tracker ist das die User-facing-Wahrheit.

LOSO-Ablation auf N=7 (2026-05-18): Headline gap=2000 → 2500 hob
acc 0.864 → 0.868 (+0.4 pp), AUC 0.940 → 0.943 (+0.3 pp), F1(w)
0.875 → 0.885 (+1.0 pp). 6 von 7 Folds verbesserten sich, P02/P03
marginal regrediert (≤0.7 pp). Wichtig: P05 (neue, schwächste Fold)
profitierte (acc 0.816 → 0.825, FP 307 → 295) — was die Hypothese
aus der Marker-Analyse stützt, dass P05's lange Denkpausen in der
math-Task länger als 2 s sind. Gap=3000 testete noch +0.2 pp F1,
aber P05 regredierte (acc 0.802, FP 340) weil Fidgeting in geplanten
Pausen ≥ 2.5 s fälschlich als writing geschluckt wird — und σ-acc
sprang von 0.026 auf 0.035. `2500` ist die letzte Stelle mit
near-universellem Per-Fold-Gewinn und σ-Tightening. Vorgänger-Switch
auf N=5 von gap=300 → 2000 hatte +4.2 pp acc gebracht; bei N=7 ist
das Plateau erreicht — weitere Smoothing-Gains brauchen entweder
Features (z. B. „still sitting" Detektor) oder Threshold-Tuning.

N=8 (2026-05-18, +P07/S019): Headline-Acc fällt 0.868 → 0.861, AUC
0.943 → 0.932, σ wächst 0.024 → 0.035 — komplett von P07-Fold
getrieben (acc 0.808, AUC 0.848). Per-Block-Diagnose: P07 versagt
*ausschließlich* im Math-Block (acc 0.578, 96 FPs, 61 FNs), während
abschreiben/free_writing/pause sauber sind (acc 0.83–0.96). Sample-
Level am `S019_merged.csv`: P07 hat in 225 s Math-Block nur **22 s
echte Pen-Zeit (10 %)**; 6 Idle-Stretches > 10 s (längste 22 s),
die `max_gap_ms=2500` strukturell nicht schließen kann. **30 s-Burst-
AUC für P07 erholt sich auf 0.932** — Modell trifft Phasen, nur nicht
einzelne Sekunden. Nebenbefund: 3 FP-Bursts in Pause 2 (+8 s, +49 s,
+74 s) korrespondieren mit Noah's in-room Beobachtung dass P07 in der
Pause aufs Handy getippt hat — Phone-Typing als echter Wrist-Confound,
für Protokoll v2 dokumentiert.

N=10 (2026-05-19, +P08/S020, +P09/S022): Headline-Acc 0.861 → 0.856,
AUC 0.932 → 0.928, F1(w) 0.879 → 0.864 — **alle Bewegungen innerhalb
σ-fold, σ tightens sogar 0.035 → 0.032 trotz +2 Folds**, Modell
stabilisiert sich mit N. **P08-Math widerlegt die N=8-These "Math
ist strukturell schwer":** P08 hat in Math 26 % Pen-Zeit (ähnlich
niedrig wie P07's 10 %), erreicht aber acc 0.843 / AUC 0.942 im
Math-Block. Math-Schwierigkeit war **P07-individuell** (lange
Denkpausen + fidgety hands), nicht task-inhärent — die N=8-Diagnose
"strukturelle Limitation" ist insofern zu stark formuliert. **P09 ist
neue Fehlerklasse** (acc 0.812, AUC 0.896): Pausen exzellent
(acc 0.92–0.96), aber beide Writing-Tasks symmetrisch schwach
(Free 0.791 / AUC 0.843, Abschreiben 0.782 / AUC 0.844).
Abschreiben-Pen-Zeit nur **58 % (Norm 75–80 %)** — Soft-Writer-Stil
mit langen Mikropausen *innerhalb* der Schreibphasen. Anders als P07:
**Burst-Aggregation @30 s verschlechtert P09** (acc 0.812 → 0.782,
AUC 0.896 → 0.851) statt zu helfen — die einzige Fold im Datensatz
mit @30 s < @1 s AUC. Erklärung: P09's Fehler sind zeitlich
geclustert, nicht verrauscht — längere Decision-Windows mitteln
korrekte Predictions weg statt Noise zu glätten. → **Zwei distinkte
Failure-Modi** im Datensatz mit unterschiedlichen Lösungswegen:
P07-Klasse (high-frequency Noise) braucht task-aware Labeling oder
profitiert from Burst-Aggregation; P09-Klasse (systematische Soft-
Writer-Confusion) braucht weichere Pen-Truth-Definition.

**Negative result: Per-Subject-Threshold.** Die ursprüngliche Hypothese
„P09-Klasse braucht einen per-Person kalibrierten Entscheidungs-
Schwellwert" wurde getestet (`scripts/ml/per_subject_threshold.py`,
2026-05-22) und **widerlegt**. Leakage-frei: Schwellwert auf dem ersten
Session-Drittel (Eichphase, F1(writing)-optimal) gewählt, ausgewertet auf
den restlichen 2/3, 0.5-Baseline auf denselben Fenstern. Ergebnis:
F1(writing) 0.858 → 0.846 (**schlechter**, 7/10 Folds regrediert) — das
erste Drittel ist nicht klassen-repräsentativ für den Rest. Entscheidend
ist das **Oracle** (Schwellwert direkt auf den Eval-Labels getunt, also
mit Leakage als Obergrenze): es hebt F1(writing) nur um +0.007. Für P09
selbst ist der Oracle-Schwellwert 0.49 — praktisch 0.5. Damit steht fest:
P09's Fehler sitzen in der Klassen-*Trennung* (Modell/Signal), nicht in
der Schwellwert-Wahl — ein Threshold tauscht nur FP gegen FN, die ROC-AUC
bleibt. Damit ist auch der gap-basierte Pfad ausgereizt (`max_gap_ms` hat
bei 2500 plateauiert, 3000 regredierte P05): die ehrlich verbleibenden
P09-Hebel sind mehr Signal (100 Hz) oder eine grundsätzlich andere
Label-Semantik (Intent statt Pen-Kontakt) — nicht weiteres Threshold- oder
gap-Tuning. P09-Klasse ist nach aktuellem Stand ein inhärent schwerer
Teil-Datensatz. Report `reports/per_subject_threshold.md`.

Opening (`max_spike_ms`) ist implementiert aber bleibt off; flipping
short writing spikes hurt S029 — real quick strokes (i-dots,
punctuation) sind kurz und informativ.

**Smoothing lives in the feature step, not the merge.** The merged
CSV is intentionally the "raw pen truth" — smoothing is a feature-
engineering hypothesis and must remain reversible. Anyone wanting the
unsmoothed labels can call `build_windows(..., max_gap_ms=0)` or read
`label_writing` directly from `{session}_merged.csv`.

**Marker-driven per-task error analysis.** Seit Study Mode v1 schreibt
jeder Run einen `data/raw/markers/{session}_markers.csv` mit allen
Task-Übergängen (Schreib-Tasks vs. geplante Pausen). Beim Diagnose
von LOSO-Fehlern ist das die wichtigste Cross-Reference: man kann
jedes Test-Window über `t_center_ms` auf die laufende Task mappen
und FP/FN-Cluster getrennt nach `writing`- vs. `idle`-Kategorie
analysieren. Beispiel-Insight aus dem 2026-05-17-Taji-Fold: die
meisten FPs lagen *nicht* in den geplanten Pausen (Pause-FPR=0.01,
nahezu perfekt), sondern an Pen-Lift-Mikropausen innerhalb der
Schreib-Tasks — was die Hypothese „Pen-Truth ist zu hart" stützte
und letztlich zum `max_gap_ms`-Switch geführt hat. Wenn neue
LOSO-Folds verschlechtert wirken: erst Markers über die Predictions
legen, bevor Modell- oder Feature-Änderungen angefasst werden.

**Session length minimum.** Within-session 80/20 temporal splits need
enough windows that both train and test see both classes. Empirically:
sessions < 5 min (< 100 windows) produce unreliable / nonsense metrics
because bursty writing-periods fall entirely on one side of the split
(seen on S027: train `[51 idle, 3 writing]`, test `[4 idle, 11 writing]`
→ accuracy 0.27, ROC-AUC 0.47). **Aim for ≥ 5 min** with a natural mix
of writing and idle for any session that should contribute to ML
metrics.

**Alignment confidence as ML gate.** The current merge applies δ when
`σ ≤ -2`, but that threshold is too loose for ML — borderline σ values
(-2.0 to -2.5) sometimes find spurious local minima at large δ
(seen on S011/S027: δ = 16–18 s, ROC-AUC 0.36/0.47). For training data
the practical filter is **σ ≤ -3** (S028: -3.30, S029: -5.27). Lower
confidence sessions are still valid for data collection (the pen logs
remain useful raw material), they just shouldn't be fed into the
trainer without manual review of the alignment plot.

**Temporal split, not random** (within-session only). Sliding windows
overlap by 50% (stride 0.5 s, window 1 s). Random splits leak adjacent
windows across train/test → inflated metrics that collapse in
deployment. `within_session.train_rf.temporal_split()` enforces a
4-window gap at the cut. **LOSO via `train_loso.py` is the stronger
guarantee** — the held-out subject/session was never in training, so
window overlap across the cut is impossible by construction. Use
within-session as a fast sanity check during development; LOSO is the
metric that maps to the deployment scenario.

**Feature-Window vs. Decision-Window.** The 1 s sliding window is the
*feature* window (right size for FFT bandwidth + crisp temporal
resolution), but is **not** the right size to report user-facing
accuracy on. `train_loso.py` therefore reports the same fold on four
*decision* scales (1 s / 5 s / 10 s / 30 s) by smoothing the model's
1-s probabilities per-session before re-thresholding. The
per-1-s number stays in the output as the model-quality metric, but
the 10–30 s burst numbers are what matches a typical use-case
(Schreibzeit-tracker, phase detection). Do not silently switch to the
larger scale — always report all four with the decision-window
explicitly named.

**Two training entry points, two purposes.**
- `python -m src.training.within_session.train_rf S029` — fast
  iteration on features/label-smoothing parameters on a single
  session. **Not a generalisation claim.** Use during development.
- `python -m src.training.train_loso [--by person|session]` —
  Leave-One-Out cross-validation. **Headline metric.** Use to validate
  the model and to report results. With `--save-final-model` it
  additionally re-trains on all data and dumps the deployment model
  to `models/rf_all.joblib`; `--save-cv-csv` writes per-fold metrics
  to `models/loso_cv.csv` for tracking across data-collection rounds.

**Per-session z-score, briefly.** The hardest cross-subject problem
isn't "what feature distinguishes writing" — it's that the same
gesture produces different absolute feature values on different
wrists. Per-session standardization removes the absolute-scale
component while preserving the relative structure within a session.
Lives in `_zscore_per_session()` in `train_loso.py` (and a copy in
`compare_models.py`). Caveat for deployment:
production needs a calibration phase (or rolling stats) to estimate
μ, σ from the live stream before the model can be applied.

**Ehrliche Live-Zahl — per-Session-Z-Score leakt nicht (gemessen
2026-06-11, `scripts/ml/honest_live_loso.py`).** Per-Session-Z-Score
ist *nicht-kausal* (der Held-out wird mit seiner eigenen, auch
zukünftigen Session-Statistik normiert) — also kein Train/Test-Leak,
aber live so nicht berechenbar. Die leak-freie, deploybare Variante
(`_zscore_train_pooled()`: μ/σ auf den Trainings-Folds gefittet, auf den
Held-out angewandt — wie `rf_all_live` es einbäckt) gepaart gegen die
per-Session-Headline auf denselben 14 Folds: **pooled acc 0.863 / AUC
0.930 / @5s 0.855 / @30s 0.789 — leicht ÜBER** per-session (0.855/0.929;
Δacc −0.008, Wilcoxon p=0.035 *zugunsten pooled*; ΔAUC −0.002 n.s.). Die
Vermutung „per-Session-Z-Score inflationiert die Headline / das pooled-
Live-Modell wird massiv schlechter" ist damit **empirisch widerlegt**:
der Leak hilft nicht, er unterperformt minimal (Held-out-Single-Session-
μ/σ ist verrauschter als die gepoolte Trainingsverteilung). Die ehrliche
deploybare Zahl ist also 0.863, nicht niedriger.

**Negative result: catch22 + DWT-Energy features.** Tried adding the
22-feature catch22 bank (`pycatch22`) and DWT-Energy coefficients
(`pywt`, db4 wavelet) per axis on top of the 88 engineered features.
At N=3 probands, no systematic gain (Δacc ≈ ±0.003) and fold-σ
roughly doubled — classic overfitting signature when feature count
grows but data doesn't. Recorded in `reports/model_progression.md`.
Worth re-trying at N≥5.

## Testing

`tests/` holds Tier-1 smoke tests (346 cases, ~10 s) — anything that
could silently poison the training data or the proband-facing flow:

- `test_quality.py` — synthetic CSVs feeding into `_session_facts`;
  asserts which issue codes fire. Includes a regression for the
  stale-CSV-window bug.
- `test_session_id.py` — `_next_session_id` skips IDs with stale
  pen/watch/airpods files.
- `test_merge.py` — `merge_watch_pen` watch-base behaviour (every
  watch sample preserved; label 1 only when pen DOWN/MOVE within
  tolerance; pre/post idle stretches labelled 0), plus
  `prepare_pen_data` `label_writing` mapping and x=-1 filtering.
- `test_pen_match.py` — stroke-variance alignment in
  `src/alignment/pen_match.py`: stroke-mask construction, coarse/fine
  search behaviour, sigma confidence.
- `test_pen_parser_framing.py` — STX/ETX/DLE-escape state machine
  in `pen_logger.py`.
- `test_endpoints.py` — FastAPI TestClient smokes for `POST /watch`
  (both payload formats), `POST /session/start` → `/stop` happy path,
  and the `streams_do_not_overlap` validation issue.
- `test_protocol_loader.py` — `load_protocol` schema validation
  (extra fields rejected, durations positive, content_type matches
  content, etc.).
- `test_study_scheduler.py` — Latin-Square ordering, writing/pause
  interleave, `pre_task_seconds`, randomize fallback.
- `test_study_state_machine.py` — runtime transitions
  (idle → running → paused → running → done), pause/abort semantics.
- `test_study_endpoints.py` — HTTP layer for `/study/*`.
- `test_study_e2e.py` — full start → next → next → abort smoke,
  asserts markers CSV contents and sessions.csv columns.
- `test_subject_index.py` — `_subject_index_for_person_id` counts
  only `study_mode='study'` sessions, ignores `test` and `free`.
- `test_markers_csv.py` — `write_marker` schema + append behaviour.
- `test_sessions_schema.py` — sessions.csv carries the new
  `study_mode` / `protocol_id` / `subject_index` columns; the schema
  is migrated forward on read.
- `test_sync.py` / `test_timelines.py` — previously-untested server
  helpers (sync-confidence, per-session timeline reconstruction).
- `test_chart_aggregation.py` — 5 Hz chart aggregator.
- `test_dashboard_static.py` — every JS module / view partial /
  stylesheet path returns 200 (404 trap; ES modules fail opaquely
  when served as `text/html`).
- `test_deep.py` — Deep-Sequenz-Modell-Paket (`src/training/deep/`):
  `build_raw_windows` Shapes/Labels, Per-Kanal-Z-Score, Forward-Pass
  aller drei Modelle (CNN/LSTM/GRU) bei beiden Sequenzlängen,
  Mini-Trainingslauf von `train_one_model`/`predict_proba`/`fold_metrics`,
  plus Pool-/Suffix-Auswahl (`load_session_raw(merged_suffix=…)` lädt die
  Legacy-View bzw. nennt die Downsample-Chain, `_pool_plan` mappt
  watch_profile→merged-Suffix, `POOL_FS`) und den `zscore`-Toggle
  (Default raw, `zscore=True` normalisiert per Kanal).
- `test_harnet_data.py` — harnet-Daten-Bridge (`src/training/deep/
  harnet_data.py`): Fenster-Shapes (harnet5 150 / harnet10 300),
  Resample-Längen-Arithmetik (500@50→300, 600@100→180), Label-
  Mehrheitslogik, **Stable-Sort-Invarianz bei local_ts_ms-Ties**
  (Regression analog `test_merge`), g-Range-Check (kein versehentlicher
  Z-Score), Raten-Detektion aus `ts`. Kein Modell-/Training-Test (der
  frozen-Extractor braucht den torch.hub-Download — manueller Smoke).
- `test_harnet_finetune.py` — Fine-Tuning-Loop (`harnet_finetune.py`):
  `_class_weights` balanciert, `finetune_model`/`predict_proba` als
  modell-agnostischer Smoke mit einem Dummy-`(b,3,L)→(b,2)`-Netz (kein
  harnet-Download nötig).
- `test_inference.py` — `LiveInference` smoke: leerer/stale/zu-kleiner
  Buffer → predict() == None, payload-shape, sparkline-Wachstum, Z-Score-
  Honouring (mu/sigma aus Joblib appliziert), Rate-Mismatch-Guard
  (>20 % fs-Abweichung → `rate_mismatch: true` Payload), Daily-Aggregate-
  Reset bei Datums-Wechsel, model-load-Fallback bei fehlendem joblib,
  Modern-Gravity-Support (`append_sample` mit/ohne Gravity, 92-Feature-
  Predict, Feature-Parität inkl. Gravity gegen `build_windows`,
  `missing_channels`-Guard wenn Modern-Modell auf Legacy-Stream läuft).
- `test_inference_endpoints.py` — `GET /inference/models` Schema +
  Whitelist, `POST /inference/model {id}` Switch + Buffer-Clear,
  unbekannte ID → 404.
- `test_focus.py` — Focus-Tracker-Persistenz: `log_tick` schreibt Header +
  Row, ignoriert rate_mismatch/None-Ticks, `/focus/today` gruppiert Ticks
  in Stretches (max-gap 2.5 s analog zum Label-Closing), `/focus/week`
  liefert 7 chronologische Buckets mit `is_today`-Flag.
- `test_burst_metrics.py` — `_causal_rolling_mean` ist trailing/kausal:
  ein Zukunfts-Fenster ändert keine vergangene Entscheidung (Regression
  gegen das frühere `center=True`-Look-ahead).
- `test_significance.py` — `paired_fold_test` (Wilcoxon): identische Folds
  → n.s. (p=1.0), konsistenter 10-pp-Gewinn → signifikant, sub-pp-Rauschen
  → n.s., Form-Mismatch → ValueError.
- `test_zscore_pooled.py` — `_zscore_train_pooled` ist leak-frei: der
  Held-out wird mit TRAIN-μ/σ normiert (nicht mit eigener Statistik), und
  die Eingabe-DataFrames bleiben unmutiert.
- `test_label_diagnostics.py` — `class_kinematics_summary`: per-Klassen-
  Mittel + Ratio, fehlende Spalten übersprungen, beide Klassen erforderlich
  (ValueError sonst).

Hardware loops (real BLE pen, watchOS app, iPhone bridge) remain
**manual** smoke tests — there is no XCTest target in the Xcode
project and BLE scan/connect cannot be exercised without a device.

## Path Convention

All Python modules resolve data paths relative to the project root:
```python
ROOT = Path(__file__).parents[N]
ROOT / "data"
```
Do not hard-code absolute paths.

## Working with this repo

- Prefer editing existing files; don't add new docs unless asked.
- Default to no comments in code — only add `# Why:` lines for
  non-obvious constraints, hidden invariants, or workarounds.
- When changing the quality engine, add a corresponding test fixture
  in `tests/test_quality.py` with the synthetic CSV that triggers it.
- When changing pen/watch CSV schemas, update `PEN_FIELDNAMES` /
  `WATCH_FIELDNAMES` in `src/server/config.py` (the canonical source)
  and re-run `pytest tests/`.
- Processed data (`data/processed/`) is gitignored and regenerated by
  the training pipeline.

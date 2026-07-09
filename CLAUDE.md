# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

ML4SCS (Machine Learning for Smart and Connected Systems) — semester
project by Noah Samel and Tajuddin Snasni. Goal: a
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
  gyroscope (+ gravity vector) via CoreMotion → iPhone bridge → FastAPI
  server. Rate is configurable — **current capture is 100 Hz + gravity**
  (Modern-Pool). The cross-subject LOSO headline cohort was recorded at
  50 Hz without gravity (Legacy-Pool); see *Pool architecture* below.

Status: data collection + preprocessing + watch-base merge + quality
checks + sliding-window features + Random Forest baseline + LOSO
cross-validation + Study Mode (counterbalanced protocol runner with
fullscreen proband UI and VL admin monitor) + Live-Inference im
Dashboard (Topbar-Pill + Recording-Page-Card mit persistenter
Schreibzeit-Aggregation) + Modell-Switcher
(Personal ↔ Generic) are operational. **Current headline (20-person cross-subject LOSO seit 2026-07-01;
RF + per-session z-score + `max_gap_ms=2500` label closing;
Capture-Clock-Fix): 1s-window accuracy 0.869 ± 0.032, ROC-AUC
0.946 ± 0.021. Burst-aggregiert kausal: @5s 0.856/0.932, @10s 0.825/0.907,
@30s 0.771/0.855.** Praktisch **unverändert** ggü. N=15 (0.872/0.947) trotz
5 härterer v2-Probanden (P26/P27/P29/P31/P32) — die Schwäche ist
task-/subjekt-spezifisch (keyboard/phone-Tippen-Verwechslung, siehe
*Marker-FPR* unten), nicht kohorten-weit. Nachgerechnet aus
`models/loso_oof_legacy.csv`; die kanonischen Artefakte
`loso_cv_legacy.csv` / `rf_all.joblib` sind noch auf N=15 und
regenerations-pflichtig (ebenso `rf_all_live.joblib`, noch N=14 pre-fix).
**Kohorte N=22.** N=22-RF-Refresh gerechnet (2026-07-07, auf dem Pod):
**1s-acc 0.863 ± 0.051, ROC-AUC 0.937 ± 0.053** (leicht unter N=20 0.869/0.946
— der Rückgang kommt zu 100 % aus P33/P34, nicht kohorten-weit; P33 =
Extrem-Soft-Writer, siehe `reports/p33_analysis.md`). Das lokale kanonische
`loso_oof_legacy.csv`/`loso_cv_legacy.csv` sind weiterhin **N=20** (der
Pod-Refresh wurde nicht lokal persistiert; für lokale Reproduktion neu rechnen).
**Reporting-Metrik ist jetzt grouped-5-fold** (mit ETH Zürich vereinbart;
leakage-frei via GroupKFold-by-person — `free_writing`-Kontrolle in p33_analysis) —
die LOSO-20-Stage-2-Bestätigung entfällt.

**Session 2026-07-07 (durable):**
- **Deep N=22 grouped-5-fold @3 Seeds:** tcn_bigru 0.9114 ± 0.005, tcn6
  0.9086 ± 0.003 — effektiv gleichauf, beide ~1–2 pp unter ihren N=20-
  Einzel-Seed-Leaderboard-Maxes (0.9314/0.9196) → Selektions-Inflation bestätigt.
- **HMM-HP-Sweep null** (`scripts/ml/hmm_hyperparameter_sweep.py`, 450 Kombis,
  signifikanz-gegated): smoothing/eps/**gamma** (Acoustic Scale, neu in
  `scaled_likelihoods`, Default 1.0 bit-identisch) alle im Rauschen → Defaults
  optimal. **Der echte Hebel ist der Decode-MODUS:** nicht-kausaler smoother
  (Scrybe-Tagestracker) 0.917 vs kausaler filter (Live-Gimmick) 0.898 = **+1,8 pp,
  p≈0, 20/20 Folds** (N=22: +1,75 pp, 19/22). Live bleibt filter, Tagestracker → smoother.
- **Gravity fürs Deep-Netz** (`build_raw_windows(gravity=True)` → 9 statt 6 Kanäle,
  `GridSpec.gravity`, `n_channels` aus den Daten) — **nie zuvor gefüttert** (auch
  die alte Modern-tcn6-Headline war 6ch). **Ergebnis (Modern-Deep, 3-Seed):
  Gravity hilft nicht** — tcn6 6ch 0.858 → 9ch 0.858 (+0.0005, Rauschen),
  tcn_bigru 6ch 0.889 → 9ch 0.862 (**−0.027, schadet**). Wie beim RF
  (cross-subject −0.005): Personalisierungs-, kein Generalisierungs-Signal.
- **deep×deep-Fusion null** (`inception × tcn_bigru`, r(Residuen)=0.708 → kein
  signifikanter Lift) — bestätigt: nur cross-paradigma (Deep×RF) hebt.
- Neue Tools: `scripts/ml/ensemble_committee.py` (N-Wege-Komitee) +
  `src/evaluation/fusion_utils.py` (geteilte 2-/N-Wege-Fusionslogik);
  `tcn_rf_fusion.py --model`. Neue Modelle: `tcn_bigru_w{32_24,64_16,64_24}`
  (Wide), `tcn6_inception` (Zwei-Branch-Joint-Fusion, kein Ensemble).
- **Daten-Decke bestätigt:** jede Achse außer *mehr Probanden* diese Session
  null/marginal (Fusion, Gravity, HP, Reweighting) — die Decke bewegt sich mit
  Daten, nicht Compute.

**Vorgänger-Headlines (N=3 → N=15, volle Zahlen-Ahnenreihe) +
Deep-Modell-Headlines:
[`documentation/headline_history.md`](documentation/headline_history.md).**

Zwei Zeitachsen-Fixes prägen alle Zahlen (Details im *ML pipeline
gotchas*-Abschnitt): der **Capture-Clock-Fix** (2026-06-13, Labels laufen
auf der Watch-`ts`-Uhr statt der Batch-Ankunftszeit; +2,4 pp acc, 15/15
Folds, p=0,0001) und die **kausale Burst-Glättung** (frühere
`center=True`-Zahlen ~5–6 pp inflationiert; unter kausaler Glättung hebt
Burst-Aggregation die Metrik *nicht* über das 1-s-Level). Deep-/harnet-/
Fusion-Burst-Zahlen im Log liefen teils noch pre-fix + `center=True` und
sind regenerations-pflichtig. Für gepaarte Within-Kohorten-A/Bs:
`src/evaluation/significance.py` (Wilcoxon); sub-pp-Gewinne ohne p<0.05
sind Rauschen.

## Setup

```bash
pip install -r requirements.txt
```

Dependencies: `pandas`, `numpy`, `scikit-learn`, `torch`, `aeon`, `shap`,
`matplotlib`, `bleak`, `fastapi`, `uvicorn`, `websockets`, `pytest`,
`jupyter`, `notebook`. (`aeon` = MiniRocket-Baseline, `shap` = Fold-
Erklärung; beide siehe `scripts/ml/`. `aeon`-Install stuft numpy auf
2.3.5 ab.)

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
python -m src.features S029 --max-gap-ms 2500     # sliding-window features → data/processed/S029_windows.csv
python -m src.training.train_loso                 # LOSO cross-validation (headline metric)
python -m src.training.deep --model cnn --pool legacy  # ein Deep-Modell, LOSO vs RF
python -m src.training.deep.harnet --model harnet5          # Transfer-Learning Stufe 1 (frozen) vs RF
python -m src.training.deep.harnet_finetune --model harnet5 # Stufe 2 (end-to-end fine-tune)
python -m src.training.train_loso --save-oof      # + OOF-CSV für Regression
python -m src.evaluation.regression               # Schreib-Prozent: MAE/RMSE/Bias + Plots
python -m src.evaluation.engagement               # Schreibzeit-Anteil pro Aufgabe + Heatmap
python -m src.training.within_session.train_rf S029   # within-session 80/20 RF (debug/feature-iteration)
python -m src.evaluation.evaluate S029            # placeholder, prints label distribution
python scripts/plots/plot_merged.py S029 --max-gap-ms 2500  # visualize IMU + label overlay
```
Without args, `src.merge` / `src.features` operate on the most recent session.

**Run smoke tests:**
```bash
pytest tests/         # 682 tests
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
  → batches of 10 samples at 50/100 Hz via WatchConnectivity
  → iPhone (PhoneBridge.swift)
  → HTTP POST /watch
  → server.py → data/raw/watch/{session}_watch.csv

Moleskine Smart Pen (BLE)
  → pen_logger.py (subprocess spawned by server.py)
  → data/raw/pen/{session}_pen.csv
                    ↓
       src/alignment/pen_match.py    (recover per-session δ via
                                      stroke-variance minimization;
                                      σ ≤ -3 → auto-`trainable`, -2…-3
                                      `usable` nach Review — siehe Gate-Note)
                    ↓
       src/merge/merge.py            (watch-base: 1 row per watch
                                      sample with label_writing from
                                      pen activity in ±40 ms)
                    ↓
         data/processed/{session}_merged.csv  (50/100 Hz watch + raw label)
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
                                     Recording-Page-Card + hidden #focus page)
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
csv_io.py          read/write watch + pen + sessions CSVs;
                   _next_session_id() (scans raw/{pen,watch}
                   to avoid ID reuse); _pen_recent_dots() for the live
                   whiteboard preview
status.py          connection status + _status_payload() for WS broadcasts
issues.py          ISSUE_SPECS table + _TARGET_WATCH_HZ;
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
                   lazy joblib load (seit 2026-07-08 **rf_all_live** =
                   generisch/100 Hz/pooled Z-Score als Boot-Default VORNE,
                   fallback rf_noah = personalisiert; der generische Detektor
                   ist die ehrliche Story für einen fremden Träger,
                   rf_noah nur über den Picker;
                   rf_all NICHT live-tauglich — per-Session-Z-Score ohne baked
                   mu/sigma, daher aus Fallback + Picker ausgeschlossen),
                   per-window predict() with
                   rate-mismatch guard, sparkline ring, daily-aggregate
                   counter. Reuses _window_features() from
                   src.features.windows so live + training share the
                   exact same feature extractor.
                   **Kausaler HMM-Live-Filter (seit 2026-06-24):** die rohe
                   1-s-Proba bleibt für die instantane Pille + Intensität, der
                   `OnlineForwardFilter` (src/evaluation/hmm.py) glättet sie zur
                   Schreibzeit-ENTSCHEIDUNG (`writing`) — dort sitzt der
                   Genauigkeitsgewinn (offline RF-1s 0.881→0.905, ohne
                   Retraining). Parameter aus `models/hmm_live.json`
                   (2×2-Übergangsmatrix + Prior, modell-agnostisch aus
                   loso_oof.csv via `scripts/ml/export_hmm_live.py`; ~16 s
                   adaptives Gedächtnis). Stateful → `reset()` bei
                   Stream-Gap (stale buffer) / Modell-Swap / rate_mismatch /
                   missing_channels, damit kein abgestandener Prior in eine
                   frische Phase blutet. Payload trägt zusätzlich `proba_hmm`;
                   fehlt das File, fällt `writing` graceful auf proba≥0.5
                   zurück.
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
                   (watch.py, pen.py, sessions.py,
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
  `rf_noah`, `rf_all_live` (rf_all ist als Headline-Artefakt NICHT
  live-deploybar und bewusst nicht im Picker).
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
preload tags, topbar markup (visible tabs **Recording · Sessions ·
Training · Settings**; Focus **and** Admin are intentionally *not*
listed — their page slots, routes, and JS modules stay registered so
`#focus` / `#admin` still resolve, they are just hidden from the tab
strip), the `liveInferencePill` next to the status cluster, the
`<div data-view="..."></div>` page slots, and
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

`focus.js` is the Focus-Tracker page — **hidden from the tab strip**
(reachable only via the `#focus` URL, same pattern as Admin), a
contemplative counterpart to the Recording cockpit. Hero `h:mm` clock
left, 24-hour day-timeline strip right (with writing stretches as
gradient blocks + "now" marker that advances on every WS tick),
seven-bar week frieze below (today highlighted, peak day tagged). Reads
`/focus/today` and `/focus/week` on mount and re-polls every 5 s while
visible; live pill updates from each WS tick. Styles in
`static/css/focus.css` with its own background slash glyph
(mirror-flipped vs Recording's). The page module + `/focus/*` backend +
`focus_log.py` all stay live — the day-to-day writing-time surface is now
the embedded Recording-page inference card. The
Recording-page also exposes an embedded inference card (writing-now
state + 60-s sparkline + "writing time tracked" counter) with an
in-place model picker (Personal `rf_noah` ↔ Generic `rf_all_live`)
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
  into `state.js`. `orientation`-Messages umgehen bewusst `handleStatus`
  und gehen an genau einen `setOrientationHandler(fn)`-Subscriber
  (`(qs, fs)`) — die aktive Seite registriert in `onShow()`, meldet in
  `onHide()` ab.
- `watch3d.js` — seiten-agnostischer Three.js-Helfer fürs *Live 3D watch*
  (siehe eigener Abschnitt unten). `initWatch3D(canvas)` →
  `{updateOrientation, setWriting, recenter, destroy}`.
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

**Live 3D watch (`static/js/core/watch3d.js`, seit 2026-07-08).**
Ein Three.js-Watch-Modell auf der Recording- **und** Admin-Seite, das die
Live-Handgelenk-Orientierung spiegelt (aus dem `qs`-Quaternion-Batch des
`orientation`-WS-Broadcasts) und **grün leuchtet, wenn das Modell „writing"
predictet** (`setWriting()` aus `onStatus`). Präsi-Showpiece — Wow-Effekt.
- Three.js r169 via CDN-Importmap (kein Build-Step), `GLTFLoader` +
  `RoomEnvironment`/PMREM + `ACESFilmicToneMapping`. Modell
  `static/assets/watch/scene-lite.glb` = **7,4k Tris** (von 347k dezimiert
  via `npx @gltf-transform/cli optimize` — die 347k-Version war die ganze
  Lag-Ursache, NICHT Three.js selbst).
- **Basis-Konjugation** CoreMotion(Z-up) → Three.js(Y-up): `q_display =
  C ⊗ (q_ref⁻¹ ⊗ q_dev) ⊗ C⁻¹`, empirisch kalibriert `C_FIX =
  [0, -√½, √½, 0]` + `.conjugate()`. `recenter()` (Button pro Seite) setzt
  die Ruhepose neu — der Arm auf den Tisch legen und nullen.
- **Jitter-Buffer-Playback (der Knackpunkt für Live-Flüssigkeit):** die
  Samples kommen gebündelt (~10 Batches/s à ~10 Stück, Netz-Jitter), werden
  aber mit **konstanter Winkelgeschwindigkeit** abgespielt — fraktionaler
  Lese-Cursor, slerp zwischen zwei Nachbar-Samples, Tempo = **bekannte
  Geräte-`fs`** (aus dem Payload, NICHT aus Ankunftszeiten geschätzt — das
  war ein Ruckel-Bug, Fable-Review). Sanfter P-Regler auf geglätteter
  Puffertiefe (~150 ms Ziel) korrigiert Drift; Prebuffer-Gate gegen
  Dry-Start. Diagnose-Lehre: Live-Ruckeln war das **Signal-Timing**
  (bursty Delivery), nicht das Rendering.
- Server-Cap `_ORIENT_QS_MAX=15` in `routes/watch.py`: kappt einen
  Spill-Drain-Burst auf einen kleinen WS-Frame.

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
  (Phone-App → Settings → Motion; Code-`Config`-Default 50 Hz / Batch 10,
  **aktuell auf 100 Hz gesetzt**) — die Werte
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
  default 2500 ms) before windowing. Then 1 s sliding windows with
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
  [--max-gap-ms 2500] [--max-spike-ms 0]`, writes
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
- `src/training/deep/` — **Deep-Sequenz-Modell-LOSO.** 1D-CNN / LSTM / GRU / TCN
  auf rohen IMU-Sequenzen statt der 88 Features, im identischen LOSO-by-person-
  Protokoll wie `train_loso.py`. `data.py` baut rohe Fenster (6 Kanäle,
  `zscore`-Schalter), `models.py` die `nn.Module`-Klassen (seq-len-agnostisch;
  `TCN` = dilatierte Kausal-Convs nach Bai et al. 2018, `BatchNorm1d` → ohne
  Z-Score deploybar), `train_loso.py` den Trainings-Loop + pool-fähigen Runner.
  **Genau ein Modell pro Aufruf**, `--pool`-Auswahl analog RF (`POOL_FS`,
  `_pool_plan()` mappt Session→merged-Quelle; kein `auto` — rohe Sequenzen
  können keine Raten mischen). **Per-Session-Z-Score hier default AUS**
  (BatchNorm re-normalisiert die Skala; CNN-A/B Δacc −0.002 p≈0.65). CLI:
  `python -m src.training.deep --model {cnn|lstm|gru|tcn|tcn6} [--pool legacy|modern] [--win 1|5|10|both] [--zscore]`
  → `models/deep_loso_{pool}.csv` + Vergleichstabellen gegen die RF-Headline.
  **Kernbefund:** auf **1-s-Input + Burst** ist der TCN-Vorsprung @1s (0.895 vs
  RF 0.872) genau das von der Burst-Aggregation entfernte Rauschen → @5/10/30 s
  ununterscheidbar vom RF. Aber **natives Lang-Fenster-Training** (`--win 5`)
  schlägt den RF signifikant: **TCN-5s 0.911, `tcn6` 0.922** vs RF-nativ-5s
  0.885 (N=15, gepaart p<0.005); plateauiert bei ~5 s. Praktisches Optimum:
  5-s-Fenster mit TCN/tcn6 — **nicht deployed** (live läuft 1s-RF+HMM). Volle
  Zahlen (CNN/TCN/tcn6 @1/5/10 s, modern-Pool-Seed-Floor ±1.7 pp):
  [`documentation/experiment_log.md`](documentation/experiment_log.md) §3.
- `scripts/ml/deep_hp_study.py` + `src/training/deep/hp_search.py` —
  **faire Per-Architektur-HP-Studie** (Sobol über lr/dropout/batch/wd), weil die
  Deep-Vergleiche oben mit Default-HP für alle Architekturen liefen. `--mode
  {full,trial,collect}`; `.github/workflows/deep_hp.yml` = 3-Job-CI, dispatch-only,
  `SWEEP_DATA_URL`-gated. **PR #57 auf main (2026-07-01).** Suchlauf N=20 legacy
  @5s: Sieger @1 Seed **tcn6 0.9194/0.9755** (robustest), **GRU-Überraschung
  0.9185 gleichauf** aber HP-fragil, LSTM extrem fragil, tcn 0.905, cnn 0.897.
  tcn6-vs-gru (0.1 pp) weit unter dem Seed-Floor ±1.7 pp. Details +
  Transformer-OOM-Fix: `reports/deep_hp_study.md`,
  [`documentation/experiment_log.md`](documentation/experiment_log.md) §3.
- `src/training/deep/grid.py` + `configs/hp/*.json` — **config-getriebene
  HP-Grid-Search** (2026-07-05): editierbare per-Modell-Grids (identische
  Default-Grids = Fairness-Invariante), Runner `--mode grid --config …` (Freeze
  via Git-SHA, Resume über Trial-CSV-Skip) + `--mode grid-collect` (Winner
  a-priori: Seed-Mittel-Acc). **Zwei-Stufen-Protokoll:** Suche auf grouped-5-fold
  (`train_deep_loso(folds=5)`, `random_state=42` gepaart; `folds=None` = LOSO) →
  Bestätigung NUR des Siegers @3 Seeds auf LOSO-20 (`significance.py`).
  5-Fold-Signifikanz strukturell unterpowert (min p 0.0625) → nie für gepaarte
  Claims. **RunPod ist die primäre Trainings-Umgebung** (1× RTX A4000, hat Colab
  abgelöst — Session-Timeouts). Dispatch auf dem Pod:
  `python scripts/ml/run_grid_wandb.py configs/hp/<name>.json` → loggt nach wandb
  (`ML4SCS_HP_Grid`) + R2-Backup. Ergebnisse ziehen:
  `scripts/ml/pull_wandb_runs.py [--out models/hp_grid/wandb_runs.csv]`.
  **Bei GPU-Compute-Fragen RunPod vorschlagen; für HP-Grid-Ergebnisse zuerst
  `pull_wandb_runs.py` laufen lassen.**
  **RunPod-Gotchas (2026-07-07):** `/workspace` überlebt einen Pod-Restart, aber
  **pip-Deps, Creds (`rclone.conf`, wandb-`~/.netrc`) und Env sind weg** →
  re-provisionieren (`pip install --break-system-packages …`, wandb-Login,
  `RCLONE_CONFIG_R2_*`-Env). `run_grid_wandb` **crasht mit EXIT:1 am ENDE am
  rclone-R2-Backup**, wenn R2-Creds fehlen — Training + wandb sind dann längst
  durch (Ergebnisse sicher in wandb), rein kosmetisch. **Resume-Skip:** ein
  Leftover-Outdir (`run_meta.json` ohne `trial_*.csv`, Rest eines gekillten Laufs)
  lässt eine Config **still ausfallen** → Outdir löschen erzwingt Re-Run.
  R2-Bucket `ml4scs-sweep`, Creds lokal in `.env` (gitignored), `sweep_data.zip`
  (N=22) hochgeladen. Pod pullt Daten aus R2 + Code aus `origin` (= noahsa16-Fork,
  NICHT `org` = divergentes Team-Repo). wandb-Run-Namen kollidieren für gleiches
  (model, seed) über pool/gravity — per Config-Feldern unterscheiden.
- `src/training/deep/harnet*.py` — **Transfer-Learning mit dem Oxford
  `ssl-wearables`-Foundation-Model (harnet).** `harnet_data.py` (Bridge
  merged→harnet-Fenster: resample 50/100→30 Hz, `(N,3,150)` harnet5 /
  `(N,3,300)` harnet10), `harnet_frozen.py` (Stufe 1: frozen Conv-Trunk →
  Embedding als `.npz` gecached, LOSO mit LogReg + RF-Kopf), `harnet_finetune.py`
  (Stufe 2: end-to-end). **Input = userAcceleration ohne Gravity, kein
  Z-Score.** CLIs `python -m src.training.deep.harnet [--model harnet5|harnet10]`
  + `.harnet_finetune`. **Befund (N=14):** harnet5-frozen gleichauf mit RF@5s;
  harnet10-frozen schlägt RF@10s (+bes. @30s +4.3 pp); Fine-Tuning kein Gewinn
  vs frozen (überfittet bei N=14). Gleiche schwache Folds wie RF (per-Fold-AUC
  r≈0.92) → modellunabhängige Decken-Bestätigung. `reports/harnet_transfer.md`,
  [`documentation/experiment_log.md`](documentation/experiment_log.md) §3.
  Setup-Hürde: macOS-Framework-Python braucht CA-Bundle für `torch.hub`
  (`_ensure_ca_bundle()`); Modell-Download lazy beim ersten Lauf (~40 s).
- `scripts/ml/harnet_rf_fusion.py` — **harnet5↔RF-Fusion, Null-Befund** (N=14):
  nativ-5s hebt weder Ensemble noch Stack die Headline (alles in der
  Fold-Streuung); der per-window-Gewinn ist reines De-Noising, redundant zur
  Burst-Aggregation. Residuen-Korrelation r=+0.574 (beide irren an denselben
  Fenstern). `reports/harnet_rf_fusion.md`.
- `scripts/ml/tcn_rf_fusion.py` — **TCN6↔RF-Ensemble** (2026-07-01/02, N=20
  legacy, nativ-5s). **Anders als die harnet-Fusion hebt das Proba-Mittel hier
  BEIDE Solo-Modelle signifikant:** RF-solo 0.879, TCN6-solo 0.898, **Ensemble
  0.909 / AUC 0.978** (Ensemble > RF Δacc +0.0327 p=0.0032; > TCN6 +0.0076
  p=0.036). Residuen r=0.599 — plausibel echter ~1-pp-Effekt via N=20-Power (vs
  N=14 harnet). **Forschungsbefund, NICHT deployed** (live 1s-RF+HMM).
  `reports/tcn_rf_fusion.md`, [`documentation/experiment_log.md`](documentation/experiment_log.md)
  §4. Siehe `tcn6_rf_fusion_result`-Memory.
- **Hybrid-TCN-Modelle + Modell-Zoo-Erweiterung** (`src/training/deep/models.py`,
  2026-07-05/06, aus Nutzer-Vorschlägen; die 2026-07-05-Hybride via Subagent-
  Driven-Development, Commits `027d07c..2a16172` auf `development`). **In git
  committet sind 15 Einträge** (`cnn, lstm, gru, tcn, tcn6, tcn6w32, tcn6k5,
  tcn6wn, tcn6ap, tcn6se, tcn8, transformer, transformer_p5, tcn_gru,
  tcn_transformer`); (`gru2, bigru, inception, tcn_bigru, tcn_gru_attn` sind seit 252cbf1/2aac3a7
  **committet**; ebenso die 2026-07-07-Neuzugänge tcn_bigru-Wide + tcn6_inception
  — ein frischer Clone hat sie also). Deren **Accuracies** liegen aber in wandb,
  nicht lokal: vor jedem Zitat `models/hp_grid/wandb_runs.csv` bzw. den Pod prüfen. Gemeinsame Grundlage aller TCN-Varianten:
  `_build_tcn_trunk(n_channels, hidden, levels, kernel_size=3, dropout=0.2,
  norm="batch")`, bit-identisch aus `TCN.__init__` extrahiert (volle Test-Suite
  vorher/nachher grün), damit Hybride denselben dilatierten Causal-Conv-Stack
  wie `TCN`/`tcn6` bauen statt ihn zu duplizieren.
  - **`TCNGRUHybrid` (`tcn_gru`, ~14.257 Params) — der aktuelle FRONT-RUNNER.**
    `tcn6`'s 6-Ebenen-Trunk (`hidden=16`, kein `AdaptiveAvgPool1d`) speist einen
    1-Layer-GRU (`hidden=32`) statt zu poolen — der GRU übernimmt die zeitliche
    Aggregation, die `tcn6` sonst wegmittelt (`O(seq_len)` wie ein reiner GRU,
    kein Downsampling nötig). **HP-Grid-Befund (2026-07-06, grouped-5-fold,
    legacy, nativ-5s): g00 (lr 3e-4/dropout 0.05/wd 1e-5) über 3 Seeds acc
    0.9271/0.9211/0.9185 → Mittel 0.9222 ± 0.0036 / AUC 0.9786** — über `tcn6`
    g00 (0.9196) auf demselben Protokoll, mit σ *tighter* als der Seed-Floor.
    **Caveat:** auf einem *einzelnen* Seed nicht belastbar über tcn6 (GPU-Non-
    Determinismus unten); der Vorsprung braucht das gepaarte 3-Seed-Mittel.
  - **`TCNBiGRUHybrid` (`tcn_bigru`, ~19.089 Params, UNCOMMITTED):** Einzel-
    Variablen-Delta zu `tcn_gru` — GRU-Head **bidirektional**, Repräsentation =
    `cat(h_n[0], h_n[1])` (beide finalen Hidden-States) statt `out[:, -1, :]`
    (dessen Rückwärts-Anteil sähe nur das letzte Sample). Bei Batch-Fenster-
    Klassifikation zulässig (kein Online-Streaming *im* Fenster); der Rückwärts-
    Pass trägt das Fensterende (Stift-Absetzen) in frühe Zeitschritte. Hypothese:
    hebt den tcn_gru-Vorsprung über das Rauschband.
  - **`TCNGRUAttnHybrid` (`tcn_gru_attn`, ~14.290 Params, UNCOMMITTED):** Einzel-
    Variablen-Delta zu `tcn_gru` — `AttnPool1d` (Softmax über die Zeit) über
    ALLE GRU-Outputs statt nur `out[:, -1, :]`. Fast gratis (+33 Params). Nicht
    kausal streambar (nutzt die Zukunft), für die Batch-Fenster-Entscheidung ok.
    Beide Deltas sind bewusst **isoliert** (je eine Variable), damit die Präsi-
    Aussage eindeutig bleibt (bidirektional *vs.* Attention-Pooling, nicht beides).
  - **`TCNTransformerHybrid` (`tcn_transformer`, ~22.193 Params) — DROPPED.**
    3-Ebenen-TCN-Trunk als reicherer Patch-Embedder (mehr Kontext/Token als
    `transformer_p5`'s einzelner Conv), `MaxPool1d(5)` → 50 Tokens (gleiches
    Attention-Budget wie `transformer_p5`), dann 2-Layer-`TransformerEncoder`
    (`d_model=32, nhead=4`); rezeptives Feld 29 Samples/Token. **2026-07-06
    mid-run gekillt** (zu langsam für die GPU-Share vor Donnerstag) — nie ein
    echtes Ergebnis.
  - **`gru2`/`bigru`/`inception` (UNCOMMITTED, Standalone-Roh-Sequenz, kein
    TCN-Trunk):** Pre-Thursday-Modell-Zoo — 2-Layer-GRU (~11k), bidirektionaler
    1-Layer-GRU (`cat(h_n[0],h_n[1])`, ~8k), `InceptionTime` (Fawaz et al. 2020:
    parallele Kernel 9/19/39 + Bottleneck + MaxPool-Zweig + Residual alle 3
    Blocks, ~119k — das bewusst stärkere CNN-Pendant gegen das 0.897-gedeckelte
    `cnn`). GRU-getunte Grids (`lr` bis 0.005, das der Sobol-GRU-Sieger mochte).
    Zwischenstand HP-Grid: `gru2` best 0.9125, `tcn_gru` 0.9222, `tcn6` 0.9196 —
    die GRU-Familie ist konkurrenzfähig, aber im ±1.7-pp-Rauschband.
  - **Configs:** je `configs/hp/<model>.json`. `tcn_gru`/`tcn_transformer` volles
    Grid (Fairness-Invariante); die Pre-Thursday-Probes (`gru2`/`bigru`/
    `inception`/`tcn_bigru`/`tcn_gru_attn`) **fokussierte 4–6-Trial-Grids, 1 Seed,
    grouped-5-fold** um den jeweiligen Sieger-HP — bewusst NICHT das volle Grid,
    damit sie vor Donnerstag durchlaufen (die tcn_gru-108→36-Kürzung war derselbe
    Zwang). tcn_gru selbst wurde auf dem Pod via `tcn_gru_1seed.json`-Kopie
    (seeds `[42]`) von 108 auf 36 Trials gekürzt.
  - **GPU-Non-Determinismus (2026-07-06, wichtiger Methodik-Befund):** dieselbe
    Config + derselbe **Seed 42** gaben **0.9271** (`tcn_gru/`) vs. **0.9106**
    (`tcn_gru_1seed/`) — **1.6 pp Spread bei FIXEM Seed.** Ursache: cuDNN-
    Autotuning + nicht-deterministische Conv-Backward-Kernel → divergente Early-
    Stop-Epochen (9.8 vs 8.0). Heißt: der dokumentierte „Seed-Rauschen-Floor
    ±1.7 pp" ist teils gar kein Seed-Effekt, sondern **Hardware-Nichtdeterminiert-
    heit bei fixem Seed**. Konsequenz: Einzelzahlen-Rankings zwischen Modellen
    sind Rauschen; nur **gepaartes Multi-Seed auf identischen Folds** (Sieger-@3-
    Seed-Bestätigung, `significance.py`) ist belastbar.
  - **Ensemble (Konzept 3):** `scripts/ml/tcn_transformer_fusion.py`
    (+ `tests/test_tcn_transformer_fusion.py`) — Proba-Mittel `tcn6` ×
    `transformer_p5`, noch nie für ein echtes Ergebnis gelaufen. Reaktiver Hebel:
    nur wenn ein Run überrascht (Muster `tcn_rf_fusion.py` → 0.909).
  - **Pod-Dispatch-Stand (2026-07-06, pre-Donnerstag-Abschlusspräsi):** drei
    tmux-Queues auf dem RunPod-Pod (siehe *RunPod hat Colab abgelöst*), alle nach
    wandb `ML4SCS_HP_Grid`: `hp_tcn_gru` (= `tcn_gru_1seed`, 36 Trials),
    `hp_queue` (`gru2`→`bigru`→`inception`), `hp_queue2` (`tcn_bigru`→
    `tcn_gru_attn`→Deep-Reweighting-Experiment; wartet comm-basiert bis die GPU
    frei ist). Ein RF-Sweep + `tcn_transformer` wurden gekillt (irrelevant / zu
    langsam vor der Präsi).
- `scripts/ml/deep_hard_negative_weight.py` — **Deep-Reweighting am tcn6**
  (2026-07-06, UNCOMMITTED): gepaart pro Fold tcn6 baseline vs. **3×-Loss-
  Gewicht auf keyboard/phone-Trainingsfenstern**, einzige Variable =
  `sample_weight`. Deep-Pendant zum RF-Test (`reports/hard_negative_feature.md`:
  phone-FPR 0.243→0.286 *schlechter*) — der einzige nach der RF-Falsifikation
  noch untestete Riss (ein Netz könnte seine Repräsentation umformen). Dafür
  bekam `train_one_model` ein optionales `sample_weight` (Default `None` →
  bit-identisch, `reduction='none'`+gewichtetes Mittel nur wenn gesetzt; 105/105
  `test_deep` grün). Nutzt die Deployment-Trainingsmaschinerie (kein divergenter
  Loop). Tagging via Marker (`t_center_ms`→Task, wie `marker_fpr.py`). Output
  `reports/deep_hard_negative_weight.md` + `models/deep_hard_neg_weight_{oof,cv}.csv`.
  Erwartung: bestätigt den RF-Null → stärkt die Signal-Decken-Story.
- `scripts/ml/compare_models.py` — runs LOSO on the same splits with
  RF / ExtraTrees / HistGradBoost / LogReg / MLP / SVM-RBF to verify
  RF is still competitive. Same `--no-zscore` flag. Liest
  vor-generierte `{session}_windows.csv` aus `data/processed/`.
- `scripts/ml/minirocket_loso.py` — **MiniRocket-LOSO (viertes Modell-Bein,
  `aeon`)**, `--window-sec` / `--n-kernels`. **Befund (N=15 legacy):
  MiniRocket-nativ-5s 0.886/0.956 ≡ RF-nativ-5s 0.885/0.953 (p=0.93).** Eine
  RF-unverwandte Familie trifft dieselbe Decke + schwächste Fold (P17) →
  paradigmen-unabhängige Decken-Bestätigung. Negativ: 1-s+Burst @10s/@30s
  signifikant schlechter als RF → nativ-5s nutzen. `models/minirocket_win{1,5}_cv.csv`.
- `scripts/ml/shap_explain_fold.py` — **SHAP-Erklärung einer LOSO-Fold**
  (`TreeExplainer`, leakage-ehrlich). Auf **P17**: Top-Features Jerk + 3–8-Hz-
  Spektral, aber die *kleinen* signierten Werte (~±0.005) SIND der Befund — kein
  Feature trennt P17 → Mehrdeutigkeit im Signal, nicht im Feature-Set.
  → `reports/figures/shap_P17.png`.
- `scripts/ml/marker_fpr.py` — **Marker-Per-Task-FPR: Hard-Negative-Lücke**
  (2026-07-01, N=20 legacy 1s-OOF; `parse_task_blocks`/`assign_task`,
  `tests/test_marker_fpr.py`). **Die LOSO-FPR clustert task-spezifisch auf
  Tippen, nicht flach:** pooled `keyboard_typing` 0.360, `phone_typing` 0.251
  vs. `pause` 0.036 (4.7×). **P17: keyboard 0.63, phone 0.68** (verwechselt ~2/3
  der Tipp-Fenster mit Schreiben), subjekt-spezifisch (P26/P27 lehnen ab).
  **Revidiert die „Decke = reine Signal-Ambiguität"-Erzählung teilweise:** ein
  substanzieller Teil von P17s Schwäche ist eine adressierbare Trainingslücke.
  `reports/marker_fpr.md`; siehe `marker_fpr_hard_negative_gap`-Memory.
- `src/features/rhythm.py` + `scripts/ml/rhythm_feature_test.py` —
  **Rhythmus-Feature-Negativbefund** (opt-in `build_windows(rhythm=True)`,
  Autokorr-Peak + spektrale Flatness): keyboard-FPR 0.343→0.336, phone leicht
  schlechter, LOSO n.s. — Handschrift ist am Wrist-IMU selbst rhythmisch genug.
  `reports/rhythm_feature.md`, Log §2.
- `scripts/ml/tsfresh_loso.py` + `src/features/tsfresh_winners.py` — **ERSTER
  übertragbarer Feature-Gewinn** (2026-07-02, nach drei Falsifikationen).
  Dreistufig: volle tsfresh-Bank schlägt die 88 gematcht (+0.85 pp acc p=0.0015)
  → 42 lean numpy-„Winner" destilliert (Kurzlag-Autokorrelation, Quantile,
  change_quantiles, CID; opt-in `build_windows(tsfresh_winners=True)`,
  bit-identisch im Default) → **Transfer auf allen ~45.5k Fenstern hält**
  (window-acc 0.869→0.874 p=0.0073, AUC p=0.0002; **1s+HMM-Stack 0.8954→0.8993
  p=0.0027** — komponiert mit dem HMM). P17 unberührt (Tipp-Confound bleibt
  Datenproblem). **Adoptions-Kandidat, noch NICHT adoptiert** (Übernahme = Flag
  in kanonischer Window-Gen + Live-Inference + Retraining). `reports/tsfresh_transfer.md`,
  Log §4; siehe `tsfresh_feature_gain`-Memory.
- **SHAP-Diff + Hard-Negative-Feature-Test P17-Schreiben vs. P17-Tippen**
  (`scripts/ml/hard_negative_feature_test.py`, 2026-07-01/02): Rohdaten zeigen
  P17s Tippen als scharfe Gyro-Bursts *derselben Größenordnung* wie sein
  Schreiben (aggressiver Hunt-and-Peck-Stil); SHAP-Vergleich P17-Schreib-TP vs.
  Tipp-FP r=0.633 — die Trenn-Info existiert als **Minderheitsstimme**
  (`rx_band_3_8`, `gyro_mag_jerk`), wird aber überstimmt. 10 verschärfte Features
  senken die Tipp-FPR nicht (keyboard 0.343→0.358); 3×-Weighting schadet
  (phone 0.243→0.286). **Feature-Achse dreifach falsifiziert** (Rhythmus,
  Features, Weighting) → Hebel = mehr Probanden mit aggressivem Tippstil, oder
  intrinsisch @50 Hz. `reports/shap_hard_negative_diff.md` +
  `reports/hard_negative_feature.md`, Log §2/§5; siehe
  `p17_keyboard_confusion_mechanism`-Memory.
- `scripts/ml/compare_models_at_gap.py` — gleiches Modell-Panel, aber
  baut die Features on-the-fly bei beliebigem `--gap` neu, ohne die
  Cache-Dateien anzufassen. Nützlich, um Modell-Rangfolge bei
  alternativen Label-Closing-Werten zu prüfen ohne Re-Generation.
- `scripts/ml/sweep_window_size.py` — **Feature-Window-Größen-Sweep** (das
  *Feature*-Fenster): rechnet die 88 Features über längere Roh-IMU-Fenster (3–5 s
  statt 1 s) statt 1-s-Predictions zu mitteln. Schreibt in den separaten Ordner
  `data/processed/windows_sweep/` (kanonischer Cache unangetastet), nutzt den
  **kausalen** `_burst_metrics`. CLI `--pool`, `--models`, `--config W,S`.
  **Befund (N=14 legacy):** ein 5-s-natives Feature-Fenster schlägt 1-s+Burst@5s
  bei fixer 5-s-Latenz um **+2.8 pp acc / +2.3 pp AUC** (p≈0.011, 12/14 Folds),
  modell-robust über 4 Familien. Beste Parameter 5s/2.5s oder 3s/1.5s. Per-Fold:
  P09 +0.057 größter Gewinner, P07 −0.038 einzige Regression (P07/P09-Dichotomie).
  **Noch NICHT adoptiert** (live rechnet weiter auf 1 s). Log §5.
- `scripts/ml/ablate_gap_loso.py` — Label-Closing-**Sensitivitätsanalyse** über
  mehrere `max_gap_ms`. **Methodik:** `max_gap_ms` ist a-priori durch die
  Label-Semantik fixiert (nicht test-fold-getunt); dieser Sweep prüft Robustheit,
  ist kein Selektor. Nachtest (N=14): gap 2500 vs 3000 — 2500 marginal besser +
  stabiler, Δ n.s. → **2500 bleibt**. Grouped-5-fold (GroupKFold) 0.867 ≈ LOSO
  0.871 → korroboriert die Headline (kein Fold-Struktur-Artefakt). Log §1.
- `src/training/deep/augment.py` + `scripts/ml/augment_matrix.py` —
  **Daten-Augmentation-Negativbefund** (`reports/augment_ab.md`). On-the-fly-IMU-
  Augmentation (basic scale/rotate; rich +time-warp/jitter/magnitude), GitHub-A/B
  tcn6 @5s 3 Seeds. **Kein Gewinn auf keinem Pool** (alle p>0.07), AUC durchweg
  flach → Input-Raum-Erweiterung erfindet kein fehlendes Signal. `AUGMENT`
  default OFF. Log §2; siehe `feature_engineering_ceiling`-Memory.
- `scripts/ml/label_kinematics_check.py` — falsifiziert den Varianz-
  Alignment-Bias-Verdacht: pooled writing-vs-idle Jerk/Varianz (Kern
  `src/evaluation/label_diagnostics.py::class_kinematics_summary`). Befund:
  8/8 Jerk-Features bei writing höher (Median-Ratio 1.35) → Schreiben ist
  die dynamischere Klasse, Labels nicht auf Ruhephasen invertiert (siehe
  *Sample-level merge alignment* oben). Kein Ersatz für Video-Ground-Truth.
- `scripts/ml/sync_audit.py` — prüft, ob residualer Pen↔Watch-Alignment-Fehler
  die LOSO-Decke erklärt. **Nein:** r(σ,acc)=−0.22, r(Drift,acc)=−0.18 (beide
  null/falsch-vorzeichig) → Signal-Mehrdeutigkeit bleibt die Diagnose.
  `reports/sync_audit.md`, Log §2.
- `scripts/ml/per_subject_threshold.py` — per-Person kalibrierter Schwellwert
  hilft P09 nicht (F1w 0.858→0.846, Oracle +0.007) — siehe *Per-Subject-Threshold*
  in den Gotchas + Log §2.
- `scripts/ml/train_noah_personal.py` — Personal-Modell für die Focus-Tracker-App.
  RF auf Noahs 100-Hz-Sessions (S032+S033), A/B datengetrieben ohne Z-Score
  (ΔAUC=0.000). Speichert `models/rf_noah.joblib` (mit `person_id`,
  `sample_rate_hz`, optional `zscore_mu/sigma`). Within-Noah-LOSO acc 0.878.
- `scripts/ml/honest_live_loso.py` — misst die ehrliche, deploybare Live-Zahl
  (per-Session-Z-Score vs. leak-frei pooled). **pooled 0.863 ≥ per-session 0.855**
  → der nicht-kausale Z-Score inflationiert *nicht*. Log §2.
- `scripts/ml/train_rf_all_live.py` — Deployment-Variante des
  Generic-Modells. Lädt alle 10 LOSO-Probanden, berechnet **pooled** mu/
  sigma (statt per-session — Pooled ist live-deployment-fähig, weil das
  μ/σ ins Joblib eingebacken wird und keine Calibration-Phase pro Session
  braucht). Speichert `models/rf_all_live.joblib`. LOSO-Headline-Artefakt
  `rf_all.joblib` bleibt unangetastet (per-session Z-Score, nicht
  live-tauglich). **`--profile` (Default `100hz_grav`)** wählt den
  Windows-Pool; bei einem Gravity-Profil werden die 4 Gravity-Features
  gedroppt → 88-Feature-Modell (cross-subject hilft Gravity nicht, siehe
  Gravity-Verdikt). Der 2026-07-08-Refresh trainierte so ein generisches
  **100 Hz / ohne Gravity**-RF, das seither der **Live-Boot-Default** ist
  (`_DEFAULT_MODEL_PATHS` in `inference.py`, rf_all_live vorne).
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
- `src/evaluation/hmm.py` — **kausaler HMM-Post-Processor** der
  Per-Fenster-Probas (2 Zustände idle/writing), reine Numerik. Scaled-
  Likelihood-Hybrid: die kalibrierte RF-Proba *ist* die Emission (`proba_cal`
  / Klassen-Prior), das HMM lernt nur die 2×2-Übergangsmatrix
  (`estimate_transition_matrix`, per-Session-Counts + Laplace; `class_priors`;
  `scaled_likelihoods`). `forward_filter` ist der **kausale** Headline-Decoder
  (nur Vergangenheit+Gegenwart), `forward_backward` + `viterbi` die
  nicht-kausale Obergrenze. Seq-len-/raten-agnostisch → läuft auf RF- wie
  Deep-OOF. `OnlineForwardFilter` ist die **stateful Ein-Schritt-Variante**
  des `forward_filter` fürs Live-Deployment (`step()`/`reset()`, bit-identisch
  zur Batch-Version — Test in `tests/test_hmm.py`); konsumiert von
  `src/server/inference.py`.
- `scripts/ml/export_hmm_live.py` — schreibt die deploybaren Live-HMM-Parameter
  (`models/hmm_live.json`: 2×2-Matrix + Prior, modell-agnostisch aus
  `loso_oof.csv`) für den `OnlineForwardFilter` in der Inferenz.
- `scripts/ml/hmm_postprocess_loso.py` — HMM-Treiber auf `models/loso_oof.csv`,
  leakage-frei per-Person-Holdout. **Hebt den 1-s-RF acc 0.881 → 0.905 (+2,4 pp,
  ohne Retraining)**, schlägt die kausale Burst-Glättung auf jeder Skala (15/15
  Folds, p=0.0001), ~16 s adaptive Latenz. Negativkontrolle (geshuffelte Emission
  → acc 0.50) schließt ein Artefakt aus. Verfeinert den Decken-Befund: der
  *Rolling-Mean* hebt nichts, ein *HMM* schon. **Seit 2026-06-24 LIVE deployed**
  (`OnlineForwardFilter`; Parameter via `scripts/ml/export_hmm_live.py` →
  `models/hmm_live.json`). `reports/hmm_postprocess.md`, Log §5.
- `scripts/ml/hmm_cross_model.py` — **Cross-Model-Kontext-Leiter** (2×2 RF/Deep ×
  1s/5s): **der HMM-Gewinn hängt am Zeitkontext, NICHT an der Modellfamilie** —
  RF-1s +2,4 / TCN-1s +1,0 (hilft) vs. RF-5s/TCN-5s/harnet-5s (schadet,
  Überglättung). RF-1s+HMM 0.905 ≈ TCN-1s+HMM 0.905 ≈ nativer TCN-5s 0.911 — eine
  Decke, mehrere Straßen. **Deployment: HMM auf den 1-s-RF, nicht 5-s.**
  `reports/hmm_context_ladder.md`, Log §5.
- `src/evaluation/calibration.py` + `scripts/ml/calibration_decision_scale.py` —
  ECE/Brier/Reliability auf den Decision-Scale-Probas (N=15): **die 1-s-RF-Proba
  ist schon ehrlich** (ECE 0.020, Isotone verbessert nichts); Burst verschlechtert
  die Kalibrierung; der HMM-Filter hat den besten Brier (0.080), ist leicht
  über-konfident (ECE 0.057). `reports/calibration_decision_scale.md`, Log §5.
- `src/evaluation/regression.py` — **Schreib-Prozent-Regression** (Post-Processing
  über `loso_oof.csv`, 60 s / 300 s / Session-Blöcke, MAE/RMSE/Bias). `pred_pct` =
  **binärer** Schätzer `mean(proba_cal ≥ 0.5)` — Proba-Mitteln schrumpft zur Mitte
  (~53 %), generalisiert nicht auf schiefe Anteile. Headline binär: Session-MAE
  4,5 pp, 60 s 8,6 pp (N=14). `evaluate()` trennt **HEADLINE** (truth = closed
  labels) von **DIAGNOSTIC** (truth = rohe Pen-Down; Bias ~+21 pp ist der
  Label-Closing-Bias, kein Modellfehler). `reports/regression.md`, siehe
  `regression_shrinkage`-Memory.
- `src/evaluation/engagement.py` — **Engagement-Auswertung** (Post-Processing über
  `loso_oof.csv` + Marker-CSVs): pro `(Session, Task)` der Schreibzeit-Anteil
  `true_pct` / `pred_pct` (`block_percentages()` geteilt mit `regression.py`).
  Output `models/engagement_metrics.csv` + `reports/figures/engagement_heatmap.png`.
  **Engagement-Proxy, kein Aufmerksamkeits-Detektor** (Schreibzeit ≠ Aufmerksamkeit).
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
**forward-only Capture** — vom ML/Feature-Set (windows.py) nicht genutzt, aber
seit 2026-07-08 vom **Live-3D-Watch-Rendering** konsumiert (siehe *Live 3D
watch* unten): `POST /watch` broadcastet den Quaternion-Batch als
`{type: "orientation", qs: [...], fs}` über den WS. Siehe *Pool architecture* unten.

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

**Sessions index** (`data/sessions.csv` — **gitignored**, owned by
the running server, derivable from `data/raw/`):
```
session_id, person_id, description, start_time, end_time,
pen_samples, watch_samples, airpods_samples, status,
study_mode, protocol_id, subject_index
```
- `airpods_samples` — **vestigial**; the AirPods head-IMU stream is no
  longer captured. The column stays in the header for CSV-schema stability
  (kept in `config.py` SESSION_FIELDNAMES) but is always empty for new
  sessions.
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
scans **sessions.csv** and `data/raw/{pen,watch}/` so an ID
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

**Modern-TCN6-Seed-Floor (2026-06-25, Modern-Pool N=7).** Ehrliche 3-Seed-
`tcn6`-Headline (100 Hz + Gravity, nativ-5s): **acc 0.889 ± 0.017 / AUC 0.968.**
Kernbefund: **Seed-Rauschen-Floor ±1.7 pp** (per-Fold bis ±5 pp) — bei N=7 sind
Architektur-Tweaks gegen dieses Rauschen unmessbar; nur mehr Daten bewegen die
Zahl. Frühere „+4.9 pp z-score" / „+2.8 pp val-early-stop" waren Rausch-Artefakte.
AUC seed-stabil (Ranking robust), nur die acc-Schwelle wackelt. **Deploy:
no-zscore.** Nebenbei die Deep-Pipeline gehärtet: `drawing`-Task aus allen Pools
ausgeschlossen (war ein Bug, der P17 drückte — 0.728 → 0.843 durch Fix + N=7),
Per-Fold-Seeding, v2-Coverage-Erkennung. Details Log §3; siehe
`modern_zscore_threshold_fix`-Memory.

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
(→ P07's long Denkpausen) — plus a battery of **hard
negatives** in the `idle` class designed to look writing-like on the
wrist IMU: `phone_typing`, `phone_scrolling`, `keyboard_typing`,
`pen_fidgeting` (the documented phone-typing/fidget confound), and
`gesturing`. 5 writing + 6 idle tasks, `duration_jitter_pct=0.15`
(±15 % sum-preserving). Net schedule W-I-W-I… (~25 min) — notably
longer than v1's ~15 min. (A `drawing` task was dropped 2026-06-18:
non-handwriting pen motion is out of scope for the writing detector.
Because writing now has an odd count, `_interleave_writing_with_pauses`
appends the leftover idle block at the end → the run closes on …W-I-I.)
Both the 5 writing tasks **and** the 6 idle
hard-negatives are counterbalanced per subject (see Scheduler), so the
W-I pairings vary — which is where the carryover balance actually bites,
since writing tasks are never adjacent in the interleaved run.

**Scheduler.** Three `interleave` modes are supported. `latin_square`
generates a **balanced Williams Latin square sized to the task count**
(`balanced_latin_square(n)`) and applies it — by `subject_index` — to
**both** the writing tasks and the idle blocks, then interleaves them.
This scales to any protocol: v1's 3 writing tasks and v2's 5 both get a
proper counterbalance (no special-casing, no random fallback when a
`subject_index` is present). v1's writing tasks are `abschreiben`
(text copy), `math`, `free_writing` — each 240 s — separated by pause
blocks (W-P-W-P-W, ~15 min). v2 weaves its 5 writing + 6 idle tasks
into W-I-W-I… (~25 min). Note v2's odd writing count: `balanced_latin_square(5)`
yields 2·5 = 10 rows (idle stays at 6), so the full counterbalance cycle
spans lcm(10, 6) = 30 subjects rather than 6 — Williams balance still holds
within each group.

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
ergaenzen.

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

**Capture-Clock-Fix (2026-06-13).** Merge + Window-Bau joinen Pen-Labels /
berechnen `t_center_ms` + Label-Closing-Gaps jetzt auf der per-Sample-Watch-Uhr
**`ts`**, nicht mehr auf der Batch-Ankunftszeit `local_ts_ms` (Fallback nur ohne
ts-Spalte). `local_ts_ms` ist batch-quantisiert + bei Spill-Drain Minuten
verspätet → Labels wurden zeitversetzten Samples zugeordnet (S019/P07 bis 42 s
versetzt). δ wurde schon immer gegen `ts` optimiert — der Join lief aber auf
`local_ts_ms`, also einer *anderen* Achse. **Ergebnis (N=15): 15/15 Folds besser,
+2,4 pp acc, p=0,0001; P07 +8,5 pp.** Alle vor 2026-06-13 gerechneten Zahlen
liefen auf `local_ts_ms` (regenerations-pflichtig; Defekt symmetrisch in
Train/Test, schwache Folds überproportional). Tests
`test_late_arriving_samples_labelled_by_capture_time` +
`test_t_center_and_closing_follow_capture_clock`.

**Sort-Stability-Bug (2026-05-25).** `pandas.sort_values` ist per Default **nicht
stabil**; Batch-Samples teilen dieselbe `local_ts_ms` → unstable sort scrambelte
die Reihenfolge und machte alle order-sensitiven Features (~52 % des Vektors)
zwischen Trainings- und Live-Pipeline divergent (Live-Acc kollabierte auf 0.57 bei
AUC 0.96). **Fix:** `kind='stable'` in `merge.py` + sort nach per-Sample-`ts` in
`windows.py`. Impact +0.7 pp acc/AUC. Diagnose-Tools:
`scripts/ml/replay_live_inference.py` + `scripts/ml/diff_live_features.py`.
Forensik: [`reports/sort_stability_bug.md`](reports/sort_stability_bug.md).

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

Die gap-Ablations-Historie (N=5 gap 300→2000 +4.2 pp; N=7 plateau bei 2500;
N=8/N=10 die P07-Math- und P09-Soft-Writer-Failure-Modi) steht in
[`documentation/experiment_log.md`](documentation/experiment_log.md) §1.
Kernlehre daraus, die weiter gilt: **zwei distinkte Failure-Modi** — P07-Klasse
(high-frequency Noise, profitiert von Burst-Aggregation) vs. P09-Klasse
(systematische Soft-Writer-Confusion, @30 s-Burst verschlechtert sie sogar).

**Negative result: Per-Subject-Threshold** (`scripts/ml/per_subject_threshold.py`)
— ein per-Person kalibrierter Schwellwert hilft P09 nicht (F1(writing) 0.858 →
0.846; Oracle nur +0.007, P09-Oracle-Threshold 0.49 ≈ 0.5). P09's Fehler sitzt in
der Klassen-*Trennung*, nicht in der Schwelle. `reports/per_subject_threshold.md`,
Log §2.

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

**Alignment confidence as ML gate — σ ist konservativ, kein Hard-Gate.**
The merge applies δ when `σ ≤ -2`, but that threshold is too loose to
*auto-trust* — borderline σ values (-2.0 to -2.5) *can* find spurious
local minima at large δ (seen on S011/S027: δ = 16–18 s, ROC-AUC
0.36/0.47). σ ≤ -3 is therefore the bar for the **auto-`trainable`**
verdict tier (S028: -3.30, S029: -5.27). **Wichtig: σ ≤ -3 ist KEIN
erzwungener Trainings-Filter.** `train_loso` includes
`verdict ∈ {trainable, usable}`, and `usable` carries no σ floor — so a
sub-threshold session enters training once it passes the **manual
alignment-plot review** (the actual gate for -2…-3). This is by design,
not an oversight: **σ is a conservative well-depth proxy, not an δ-error
measure.** Worked example — **S039/P13 has σ = -2.73 (below -3) yet is
the strongest LOSO fold of the cohort (acc 0.926, AUC 0.980).** A spurious
δ would *collapse* the fold (cf. the 0.36/0.47 cases above); P13's
excellence shows its δ is correct and the weak σ only reflects a shallow
variance well (very steady writer → flat minimization curve). A hard
σ ≤ -3 cutoff would have wrongly dropped the best session. Lower-σ
sessions remain valid raw data either way; they just require the manual
plot check before training, never an automatic include.

*Data-hygiene caveat:* `sessions.csv` is server-owned and not always
refreshed — `duration_seconds` can sit stale at empty even when
`start_time`/`end_time` are present, which collapses every stored
`verdict` to `usable` (the `trainable` tier needs `duration ≥ 300`).
The live quality engine (`quality.py`) recomputes both correctly; the
CSV staleness does not change the training cohort because `train_loso`
admits `usable` regardless.

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

**Negative result: catch22 + DWT-Energy features.** catch22 (`pycatch22`) +
DWT-Energy (`pywt`, db4) on top of the 88 features: at N=3 no systematic gain
(Δacc ≈ ±0.003), fold-σ ~doubled (overfitting). `reports/model_progression.md`,
Log §2. Worth re-trying at N≥5.

Weitere Negativbefunde (Rhythmus, hard-negative-Features, Augmentation, Sync-
Audit, Label-Kinematik) sind bei den jeweiligen Skripten oben +
[`documentation/experiment_log.md`](documentation/experiment_log.md) §2 gesammelt.

## Testing

`tests/` holds Tier-1 smoke tests (682 cases) — anything that
could silently poison the training data or the proband-facing flow:

**Daten-/Pipeline-Integrität:** `test_quality.py` (Issue-Codes + stale-CSV-Window-
Regression), `test_session_id.py` (kein ID-Reuse), `test_merge.py` (watch-base
Merge-Verhalten), `test_pen_match.py` (Stroke-Varianz-Alignment),
`test_pen_parser_framing.py` (STX/ETX/DLE-State-Machine), `test_sessions_schema.py`
(sessions.csv-Migration), `test_markers_csv.py` (`write_marker`).

**Server/Endpoints:** `test_endpoints.py` (`POST /watch` + session start/stop),
`test_inference_endpoints.py` (`/inference/*` + 404), `test_focus.py`
(Focus-Persistenz + Stretch-Gruppierung), `test_sync.py` / `test_timelines.py`,
`test_chart_aggregation.py`, `test_dashboard_static.py` (404-Trap auf jeden
static-Pfad).

**Study Mode:** `test_protocol_loader.py`, `test_study_scheduler.py`
(Latin-Square + Interleave), `test_study_state_machine.py`,
`test_study_endpoints.py`, `test_study_e2e.py`, `test_subject_index.py`.

**ML-Kern:** `test_deep.py` (alle Modelle Forward + TCN-Kausalität + Mini-Train +
Pool/zscore-Toggle), `test_harnet_data.py` / `test_harnet_finetune.py`,
`test_inference.py` (`LiveInference` inkl. Rate-Mismatch + Modern-Gravity-Parität),
`test_burst_metrics.py` (kausaler Rolling-Mean, Look-ahead-Regression),
`test_significance.py`, `test_zscore_pooled.py` (leak-frei),
`test_label_diagnostics.py`, `test_hmm.py` (forward_filter-Kausalitäts-Invariante),
`test_calibration.py` (ECE).

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

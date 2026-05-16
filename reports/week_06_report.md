# Week 06 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Move the ML evaluation from the within-session sanity check to a real cross-session LOSO number that we can actually quote, and build a counterbalanced **Study Mode** so that the next data collection rounds happen under a controlled, reproducible protocol instead of free-form recordings.

---

## Work Done This Week

### ML Pipeline

- Added LOSO cross-validation as the metric we actually report. The new `src/training/train_loso.py` runs Leave-One-Out (`--by session` while we still only have one subject, `--by person` once that changes). By default it only includes sessions with `verdict ∈ {trainable, usable}` from `sessions.csv`; `--include-all` overrides. It prints per-fold accuracy and ROC-AUC plus a mean ± std summary, and can optionally write a CV CSV (`--save-cv-csv`) and a final all-data model (`--save-final-model`).
- The within-session baseline is still in the repo but it's now clearly marked as a debug tool — same Random Forest with the temporal 80/20 split + 4-window gap, but only useful for fast iteration on features or label smoothing. We don't report those numbers as project results anymore.
- LOSO doesn't need the `temporal_split` trick because the held-out session was never in training to begin with, so the 50 % overlap between adjacent windows can't leak across the cut. That's a stronger guarantee than what the within-session split was giving us.

### Study Mode (end-to-end)

- Server-side state machine in `src/server/study.py`: a Pydantic-validated protocol loader for `study_protocols/v1.json`, a scheduler with three interleave modes (`writing_with_pauses`, `shuffled`, `latin_square`), and a small runtime state machine over `idle → running → paused → done`. We deliberately kept this as pure Python with no FastAPI imports, which made it easy to unit-test in isolation.
- Latin-Square counterbalancing: `LATIN_SQUARE_3` covers all 6 permutations of the 3 writing tasks, so by the time we hit 6 probands every task has appeared in every position twice. The `subject_index` is assigned automatically by `_subject_index_for_person_id`, which only counts prior `study_mode='study'` sessions — pilot/test runs don't shift the counterbalance.
- HTTP layer in `src/server/routes/study.py`: `GET /study/protocols`, `POST /study/start | /next | /pause | /abort`. Every state transition writes a row to `data/raw/markers/{session}_markers.csv`, which gives us a clean timeline for any later per-task analysis.
- v1 protocol: three writing tasks (*Text abschreiben*, *Mathe-Aufgaben*, *Freies Schreiben*), each 240 s, with two pause blocks in between. Total schedule: W-P-W-P-W, about 15 minutes including the pre-task countdowns.
- Test mode: `POST /study/start` with `test_mode=true` prefixes `[TEST] ` to the description, sets `study_mode='test'`, and skips the Latin Square (random shuffle instead). We also added `POST /sessions/{id}/mark-test` so we can retroactively flag earlier sessions without polluting the counterbalance counter.
- Sessions schema migration: `data/sessions.csv` now has `study_mode`, `protocol_id`, and `subject_index` columns. We added forward-migration on read so older rows still load fine.

### Frontend

- Fullscreen takeover for the proband side (`static/js/pages/recording-study.js` + `static/css/study-mode.css`). We build the DOM via the API rather than re-`innerHTML`-ing on every tick — that came in after we noticed the FLIP-style transition between tasks was breaking because the nodes kept being recreated. The `body.study-active` class hides the topbar and gives the proband only the instruction, the countdown, and the urgent last-5-second pulse.
- VL controls (Pause / Next / Abort) with keyboard shortcuts. Audio cues: a 880 Hz tick during the last 5 seconds and an E5/B5 two-note chime at every task transition. Both are gated on actual state changes rather than every WS tick — we tried it the lazy way first and it was very loud.
- Hidden admin monitor page at `#admin`. It's not in the tab strip on purpose — the proband shouldn't see it. The VL reaches it by triple-clicking the brand logo in the topbar (a small easter egg, mostly so it stays out of the way during normal use). It mirrors the live status / charts / connections summary on a second device, typically an iPad, so the experimenter never has to share the proband's screen.

### Quality / Data Hygiene

- `sessions.csv` is now gitignored. We learned this the hard way: the file used to be checked in, and switching branches once reset it inside the working tree, taking a chunk of session metadata with it. The server owns the file end-to-end now, and any environment can rebuild it by scanning `data/raw/`.
- Wiped the pre-Study-Mode recordings. They were collected before the v1 protocol existed and would have diluted LOSO with sessions that don't actually match the new content distribution. Cleaner to start fresh under the validated protocol than to try to make the old data fit.
- Test count went from 76 to 138. New tests cover the Study Mode modules (`test_protocol_loader.py`, `test_study_scheduler.py`, `test_study_state_machine.py`, `test_study_endpoints.py`, `test_study_e2e.py`, `test_subject_index.py`, `test_markers_csv.py`, `test_sessions_schema.py`) plus some server helpers that were previously untested (`test_sync.py`, `test_timelines.py`). The full suite still runs in about 1.5 s.

---

## Experiments

**S029 within-session baseline (debug only):** Random Forest with 1 s sliding windows at 0.5 s stride, 42 statistical features, label smoothing `max_gap_ms=300`, temporal 80/20 split with a 4-window gap → accuracy 0.83, ROC-AUC 0.85. We use this as a sanity floor when iterating on features or smoothing parameters, but it doesn't say anything about generalisation.

**Cross-session LOSO (single subject, 5 sessions):** `python -m src.training.train_loso --by session` over `S029, S031, S037, S039, S043`:

| Metric | Value |
|--------|-------|
| Accuracy | 0.854 ± 0.018 |
| ROC-AUC | 0.917 ± 0.015 |
| F1 (writing class) | 0.852 |

Per-fold accuracies all sit in a tight `[0.83, 0.88]` band, which we found pretty encouraging — the model is consistent across recording days, watch positions on the wrist, and different writing contexts (as long as it's the same subject).

**Feature importances** are clearly dominated by gyroscope-derived statistics: `ry_rms`, `rz_rms`, and the gyro-magnitude mean / std / energy values lead, with the accelerometer features trailing. That actually makes physical sense — handwriting at the wrist is mostly rotational (forearm pronation/supination plus wrist flexion), so the angular-rate channels should be where the signal lives. It probably also explains why a single-subject LOSO is already at AUC ~0.92 with just 200 trees and no feature selection — we're not really fighting the data here.

**First cross-subject pilot (Noah + P01, 3 sessions):** The week ended with the first session from a second proband — Noah's flatmate sat through the full v1 protocol as `P01` (subject_index=2, σ=-4.55, 15.5 min, one harmless 2-batch / ~400 ms sequence gap). Combined with `S003`+`S007` (Noah), this gave us the first real `train_loso --by person` run. We also rolled out the extended feature set (commit `e417a93`) just before this session, so the feature count has grown from 42 to 88 — added 24 spectral descriptors (dominant frequency, spectral centroid, spectral entropy, 3–8 Hz band ratio per axis), 6 zero-crossing rates, 8 jerk features, and 6 cross-axis Pearson correlations.

| Holdout | Trained on | Accuracy | ROC-AUC | F1 |
|---------|------------|----------|---------|-----|
| **P01** (1843 windows) | Noah only (2730 windows) | **0.855** | **0.927** | 0.853 |
| Noah (2730 windows) | P01 only (1843 windows) | 0.808 | 0.908 | 0.803 |
| **Mean** | — | **0.831 ± 0.024** | **0.917 ± 0.010** | 0.828 |

The number that actually matters: cross-person AUC came in at **0.917**, essentially indistinguishable from the same-person LOSO (0.913) we ran earlier the same day on `S003`+`S007` alone. We had been bracing for a measurable drop — that drop was the thing this whole milestone was meant to surface — and so far it hasn't shown up. With only 2 subjects we don't want to over-claim: the std is wide (±0.024 acc, ±0.010 AUC) and one proband can't disprove the existence of person-specific failure modes. But it's a strong directional signal that the central thesis of the project holds.

Feature-group importance on this 3-session set lines up with that reading: the new spectral / cross-correlation / ZCR features account for ~60 % of total importance with 52 % of the features. The single most-important feature is now `ry_dom_freq` (dominant frequency of gyro-Y, i.e. wrist rotation around the vertical axis) at ~5 % importance, followed by spectral centroids on `ry`/`rz` and `corr_ay_az`. The 2–6 Hz band where handwriting strokes live is invisible in pure time-domain statistics, which is presumably why these features generalize across subjects — they encode the *rhythm* of writing rather than per-person amplitudes.

We also ran a model comparison (ExtraTrees, GBM, HistGBM, SVM-RBF, MLP, LogisticRegression) on the same LOSO splits. All seven landed in `[0.83, 0.85]` accuracy and `[0.90, 0.91]` AUC — well within the per-fold std. With this much data, the model is not the bottleneck.

---

## Key Insights

- The within-session number was overstating things. An 80/20 cut on the same hand, same day, same task is just not the same thing as "can we predict writing on a new session". Once we made LOSO the number we report, deciding whether a new feature is worth adding got a lot less arbitrary — we now have one number that actually moves up or down for the right reasons.
- Counterbalancing the task order was much cheaper to set up now than it would be to retro-fit later. With three writing tasks the 6-permutation Latin Square fully balances every (task, position, predecessor) triple by the time we get to 6 probands. Doing it inside the protocol runner means we don't have to model order effects as a covariate when we analyse the data later.
- The subject index has to be derived, not typed in by hand. `_subject_index_for_person_id` only counts prior `study_mode='study'` sessions for that person, so pilots and free-form recordings don't shift the counterbalance. We almost shipped it without that distinction and realised it would have been a real footgun: a few test runs with proband A would have pushed her into row 3 of the Latin Square for no good reason.
- The fullscreen takeover turned out to be more important than we thought. In early dry-runs the proband was just sitting in front of the dashboard while the experimenter clicked around looking at logs and charts — distracting for both sides. Splitting it into a clean proband view and a hidden `#admin` monitor (reached by triple-clicking the brand logo, kept out of the tab strip on purpose) fixed that without adding any visible UI for the proband.
- Data hygiene ended up being part of the experiment. Keeping the pre-protocol sessions in the LOSO pool would have contaminated it: different durations, different content distribution, no counterbalance. We hesitated about wiping them — it felt wasteful — but the v1 protocol is the only source of training material that's apples-to-apples going forward.
- Cross-subject generalization, on the first try, held up. We did not expect AUC to stay flat at 0.92 when moving from same-person LOSO to person-held-out LOSO — that was the metric the project was structured to honestly measure, with the expectation that it would drop a bit. The fact that it didn't (yet, on N=2 subjects) is the strongest piece of evidence so far that the wrist-IMU writing signature is person-invariant in the band we're extracting it from. The 88-feature set ships *before* the cohort grows, so when more subjects come in we won't be confounding "more data" with "richer features".

---

## Plan for Next Week

- Extend the cross-subject cohort: Ben and Taji each record a full v1 session, plus 2–3 external probands so the first complete row of the 6-permutation Latin Square gets filled. With 4–5 subjects the LOSO std should tighten enough that the 0.92 AUC starts to be a real claim rather than a directional reading.
- A second session from P01 to even out the asymmetry we saw this week — Noah currently has 2 sessions of training data, P01 has 1, and the Noah-as-holdout fold suffered for it (acc 0.808 vs 0.855).
- Once a third subject is in, run `--by person` LOSO with the new burst-aggregated metrics in the report (5 s / 10 s / 30 s) so we have a single number for the typical user-facing use case ("did this person write in the last 30 s?") alongside the model-quality 1 s number.
- Optional, if time allows: slice windows by `task_id` from the marker CSV and check whether copy / math / free-writing have systematically different feature distributions. That would tell us whether the deployment model needs per-content-type calibration or not.

---

## Contributions

### Noah

- Built Study Mode end to end: the server-side state machine and Latin-Square scheduler (`src/server/study.py`), the `/study/*` routes, the marker CSV pipeline, the sessions schema migration, and the retroactive `mark-test` endpoint.
- Built the fullscreen proband UI (`recording-study.js`, `study-mode.css`) with the FLIP transitions, audio cues, and the urgent last-5-second pulse, plus the hidden admin monitor page (`#admin`) with the brand-logo triple-click easter egg.
- Switched the reported metric to LOSO (`src/training/train_loso.py`), moved the within-session baseline into debug territory, ran the first 5-session LOSO (acc 0.854 ± 0.018, ROC-AUC 0.917 ± 0.015), and at the end of the week the first cross-subject LOSO with P01 (acc 0.831 ± 0.024, ROC-AUC 0.917 ± 0.010 — the cross-subject number landing on top of the same-subject one was the headline result of the week).
- Extended the feature set from 42 to 88 (spectral, jerk, ZCR, cross-correlation) and added burst-aggregated decision-window metrics (1 s / 5 s / 10 s / 30 s) to the LOSO output so we can report at the scale that matches each use case.
- Grew the test suite from 76 to 138 cases — Study Mode end to end, plus some server helpers that hadn't been covered before (`sync`, `timelines`).
- Diagnosed the `sessions.csv` data-loss incident (branch switch wiped the file) and gitignored it; wrote down the ownership semantics so it doesn't happen again.

### Ben

- _to be filled in_

### Taji

- _to be filled in_

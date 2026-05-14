# Week 06 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Promote the ML evaluation from a within-session sanity check to a real cross-session LOSO metric, and stand up a counterbalanced **Study Mode** so that all further data collection happens under a controlled, reproducible protocol — ready to scale to multiple probands next week.

---

## Work Done This Week

### ML Pipeline

- **LOSO cross-validation introduced as the headline metric.** New `src/training/train_loso.py` runs Leave-One-Out (`--by session` for the current single-subject regime, `--by person` for multi-subject going forward). Filters sessions via `verdict ∈ {trainable, usable}` from `sessions.csv` by default; `--include-all` overrides. Reports per-fold accuracy / ROC-AUC + mean ± std and optionally writes a CV CSV (`--save-cv-csv`) and a final all-data model (`--save-final-model`).
- **Within-session baseline demoted to debug.** `src/training/within_session/train_rf.py` is the same RF with the temporal 80/20 split + 4-window gap, but it is now explicitly documented as "fast feature/label-smoothing iteration, not a generalisation claim". Project results are quoted from `train_loso` only.
- **No leakage by construction.** LOSO drops `temporal_split` — the held-out session was never in training, so 50%-overlap between adjacent windows cannot leak across the cut. Stronger guarantee than the within-session split it replaces.

### Study Mode (end-to-end)

- **Server-side state machine** (`src/server/study.py`): protocol loader (Pydantic-validated `study_protocols/v1.json`), scheduler with three interleave modes (`writing_with_pauses`, `shuffled`, `latin_square`), and a runtime state machine over phases `idle → running → paused → done`. Pure Python, no FastAPI imports — fully unit-tested in isolation.
- **Latin-Square counterbalancing.** `LATIN_SQUARE_3` is all 6 permutations of the 3 writing tasks (full counterbalance: each task appears in each position twice across 6 subjects, every ordered pair equally often). `subject_index` is auto-assigned by `_subject_index_for_person_id`, which **counts only prior sessions with `study_mode='study'`** — pilot/test runs don't consume a counterbalance slot.
- **HTTP layer** (`src/server/routes/study.py`): `GET /study/protocols`, `POST /study/start | /next | /pause | /abort`. Every state transition writes a row to `data/raw/markers/{session}_markers.csv` (canonical timeline for downstream per-task analyses).
- **v1 protocol.** Three writing tasks — *Text abschreiben*, *Mathe-Aufgaben*, *Freies Schreiben* — each 240 s, separated by 2× pause blocks. Net schedule: W-P-W-P-W (~15 min including pre-task countdowns).
- **Test mode.** `POST /study/start` with `test_mode=true` prefixes `[TEST] ` to the description, sets `study_mode='test'`, and skips Latin Square (random shuffle fallback). Retroactive flag `POST /sessions/{id}/mark-test` retired previously-recorded sessions cleanly without polluting the counterbalance counter.
- **Sessions schema migration.** `data/sessions.csv` gained `study_mode`, `protocol_id`, `subject_index` columns. Schema is migrated forward on read so legacy rows still load.

### Frontend

- **Fullscreen takeover for the proband side** (`static/js/pages/recording-study.js` + `static/css/study-mode.css`). DOM-API-built (no `innerHTML` re-mounts on every tick), with a FLIP-style transition between tasks. `body.study-active` class hides the topbar and takes over the viewport so the proband sees only the instruction, the countdown, and the urgent last-5-second pulse.
- **VL controls** — Pause / Next / Abort buttons with keyboard shortcuts. Audio cues: 880 Hz tick during the urgent last-5-seconds, E5/B5 two-note chime at every task transition. Both are gated on actual transitions, not every WS tick, to avoid spam.
- **Admin monitor page** at `#admin` — hidden from the tab strip; the VL reaches it by **triple-clicking the brand logo** in the topbar. Mirrors the live status / charts / connections summary on a second device (iPad) so the experimenter never has to share the proband's screen. Files: `static/js/pages/admin.js`, `static/views/admin.html`, `static/css/admin.css`.

### Quality / Data Hygiene

- **`sessions.csv` is now gitignored** after a data-loss incident on a branch switch: the file used to be checked in, and switching branches reset it under the working tree. The server owns the file end-to-end now; any environment can rebuild it by scanning `data/raw/`.
- **Pre-Study-Mode recordings wiped.** Old free-mode data was collected before the v1 protocol existed and would dilute LOSO with non-comparable session content. Fresh data collection starts under the validated protocol going forward.
- **Tests: 76 → 138.** Coverage extended to the new modules (`test_protocol_loader.py`, `test_study_scheduler.py`, `test_study_state_machine.py`, `test_study_endpoints.py`, `test_study_e2e.py`, `test_subject_index.py`, `test_markers_csv.py`, `test_sessions_schema.py`) and to previously-untested server helpers (`test_sync.py`, `test_timelines.py`). Full suite still runs in ~1.5 s.

---

## Experiments

**S029 within-session baseline (debug only):** RF with 1 s sliding windows @ 0.5 s stride, 42 stat features, label smoothing `max_gap_ms=300`, temporal 80/20 split with a 4-window gap → accuracy 0.83, ROC-AUC 0.85. Useful as a feature/smoothing sanity floor; not quotable as a generalisation result.

**Cross-session LOSO (single subject, 5 sessions):** `python -m src.training.train_loso --by session` over `S029, S031, S037, S039, S043`:

| Metric | Value |
|--------|-------|
| Accuracy | 0.854 ± 0.018 |
| ROC-AUC | 0.917 ± 0.015 |
| F1 (writing class) | 0.852 |

Per-fold accuracies are tight in the `[0.83, 0.88]` band — encouraging consistency across recording days, watch positions, and writing contexts within the same subject.

**Top feature importances** are dominated by gyroscope-derived statistics: `ry_rms`, `rz_rms`, and the gyro-magnitude mean / std / energy bands lead, with accelerometer features trailing. Physically plausible — handwriting at the wrist is fundamentally rotational (forearm pronation/supination + wrist flexion), so the angular-rate channels carry most of the signal. The strength of the gyro features is also the cleanest explanation for why a single-subject LOSO is already at AUC ~0.92 with only 200 trees and no feature selection.

---

## Key Insights

- **Headline metric matters.** Reporting within-session accuracy as the project result silently overstates generalisation: the 80/20 cut is on the same hand, on the same day, on the same task. Switching the headline to LOSO disciplines every downstream design choice and makes "is the next feature actually worth adding" a tractable question.
- **Counterbalancing is cheaper to do up front than to retro-fit.** With three writing tasks and three positions, the 6-permutation Latin Square fully counterbalances — by the time we hit 6 probands, every (task, position, predecessor) triple is balanced. Doing this in the protocol runner means analysis later doesn't have to model order effects as a covariate.
- **Subject indexing must be derived, not assigned by hand.** `_subject_index_for_person_id` counts only `study_mode='study'` sessions for that `person_id` — pilots (`test`) and free-form recordings (`free`) don't shift the counterbalance. This avoids the very real footgun of "we did three test runs with proband A and now her Latin-Square row is row 3".
- **The fullscreen takeover is a usability win, not a cosmetic one.** Pilot dry-runs of the proband UI showed the experimenter wandering around looking at logs / charts while the proband sat with an idle screen. The hidden `#admin` page gives the VL their own monitor without the proband ever seeing it — and the triple-click easter egg keeps it out of the way during normal use.
- **Data hygiene is part of the experiment.** Keeping pre-protocol sessions in the LOSO pool would contaminate it (different durations, different content distribution, no counterbalance). Wiping was the cleaner move; the v1 protocol is now the single source of training material going forward.

---

## Plan for Next Week

- Recruit and record the first multi-proband cohort: Ben + Taji + 2–3 external probands. Each runs the full v1 protocol; their `subject_index` is auto-assigned in `[0, 5]` to cover the first row of the Latin Square.
- Once ≥ 2 subjects are in, flip the headline to `train_loso --by person` (true cross-subject LOSO). Expect a drop from the current 0.92 AUC — that drop is the actual quantity the project is measuring.
- Pilot run of the v1 protocol end-to-end to verify timings (240 s × 3 + pauses lands at ~15 min as designed) and that the audio cues are audible in the typical recording room.
- Optional: per-task analysis pass — slice windows by `task_id` from the marker CSV and see whether copy vs math vs free-writing have systematically different feature distributions (informs whether the deployment model needs per-content-type calibration).

---

## Contributions

### Noah

- Built Study Mode end-to-end: server-side state machine + Latin-Square scheduler (`src/server/study.py`), `/study/*` routes, marker CSV pipeline, sessions schema migration, retroactive `mark-test` endpoint.
- Built the fullscreen proband UI (`recording-study.js`, `study-mode.css`) — FLIP transitions, audio cues, urgent last-5s pulse — and the hidden admin monitor page (`#admin`) with the brand-logo triple-click easter egg.
- Promoted LOSO to headline metric (`src/training/train_loso.py`); demoted within-session baseline to debug; first 5-session LOSO run (acc 0.854 ± 0.018, ROC-AUC 0.917 ± 0.015).
- Extended the test suite from 76 → 138 cases, covering Study Mode end-to-end plus previously-untested server helpers (`sync`, `timelines`).
- Diagnosed the `sessions.csv`-on-branch-switch data-loss incident and gitignored the file; documented ownership semantics.

### Ben

- _to be filled in_

### Taji

- _to be filled in_

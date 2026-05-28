# Week 08 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Deliver the intermediate presentation, then build the *evaluation
layers above the LOSO classifier* — write-percent regression and
per-task engagement — and close out the open hypotheses about where
the AUC ceiling comes from (sample rate, sync, per-subject threshold).
The pivot toward a Focus-Tracker deployment story came mid-week and
shaped the second half.

---

## Work Done This Week

### Intermediate presentation and Thursday demo

Two events back-to-back. **Thursday 2026-05-21:** live ML4SCS
demo — watch + iPhone + server end-to-end with the
cloudflare → ngrok → LAN tunnel fallback chain as the safety net
(the reason the tunnel work happened in the first place).
**Friday 2026-05-22:** intermediate presentation with Prof. Funk,
built around the N = 10 LOSO result, the working Study Mode
protocol, and the two failure modes from last week. Funk's verbatim
feedback: *"das Beste, was er jemals in diesem Seminar gesehen hat."*
That sets the bar — the final presentation has to be defensible at
the same level, not just incremental. It was the trigger for the
deployment-story pivot described below.

### Evaluation layers above the classifier

The headline LOSO classifies one second at a time. Two new layers
sit on top of it as pure post-processing — no re-training, no
changes to the model — and turn the per-second predictions into
metrics that match real use cases.

- **Regression — "what percentage of this time window was writing?"**
  (`src/evaluation/regression.py`). Aggregates the out-of-fold
  predictions to 60 s / 300 s / whole-session blocks and reports
  MAE / RMSE / Bias against the closed pen truth. To make the
  probabilities trustworthy on those longer scales,
  `train_loso --save-oof` now runs an isotonic calibration per fold
  (`CalibratedClassifierCV`, `cv=3` on the training folds). The
  Expected Calibration Error dropped from **0.052 → 0.006** (factor
  ~9). Documented in `reports/regression.md` + figures
  `regression_calibration.png` / `regression_scatter.png`.

- **Engagement — "how much of each task did the subject actually
  spend writing?"** (`src/evaluation/engagement.py`). Same
  architecture (post-processing over the OOF CSV) but joined against
  the Study Mode `markers.csv` so every window gets attributed to
  the task it falls into. Reports per-(subject × task) writing
  share. Documented in `reports/engagement.md` + heatmap
  `engagement_heatmap.png`. The two layers share a
  `block_percentages()` helper so the math is identical on both
  sides.

### Deep sequence models (CNN / LSTM / GRU) on raw IMU

New training package `src/training/deep/`. Runs the identical
LOSO-by-person protocol as `train_loso.py` (same fold definitions,
same burst aggregation), but trains 1D-CNN / LSTM / GRU on raw
50 Hz IMU windows instead of the 88 hand-engineered features. The
goal was to honour Prof. Funk's "do you have a deep model" question
and to give an honest answer to "do learned features beat engineered
ones at this dataset size?". CLI: `python -m src.training.deep
[--model cnn|lstm|gru|all] [--win 1|5|both]`. New test file
`tests/test_deep.py` covers raw-window shapes, per-channel z-score,
forward passes for all three models at both sequence lengths, and a
mini end-to-end run.

### Two ceiling hypotheses refuted

These are negative results. They are the most important work of the
week because they close research paths cleanly instead of leaving
them open as "should try later."

- **Sync audit.** Tested whether residual pen ↔ watch alignment
  error explains the LOSO ceiling. Three sub-tests in
  `scripts/ml/sync_audit.py`: (A) σ ↔ accuracy correlation across
  folds, (B) δ-drift first vs. second session half plus its
  correlation with accuracy, (C) label flips under a ±50 ms δ
  perturbation. Result: r(σ, acc) = **−0.22**, r(drift, acc) =
  **−0.18** — both near zero / wrong-signed. Weak folds (P07, P09)
  have *strong* σ and *minimal* drift. Sync does not explain the
  ceiling. Report: `reports/sync_audit.md`.

- **Per-subject decision threshold.** P09's failure mode looked like
  it might be a threshold problem (probas exist but are pushed below
  0.5 on this subject). Tested leakage-free in
  `scripts/ml/per_subject_threshold.py`: threshold tuned on the
  first third of each session, evaluated on the remaining two
  thirds, baseline = global 0.5. Result: F1(writing) **0.858 →
  0.846** (worse, 7/10 folds regressed). The oracle (threshold
  tuned directly on the eval labels, leakage-as-upper-bound) only
  improved F1 by **+0.007**. For P09 specifically the oracle
  threshold is 0.49 — practically 0.5. The errors live in
  class *separation*, not threshold choice; a threshold only trades
  FP for FN and the ROC-AUC stays put. Report:
  `reports/per_subject_threshold.md`.

### 100 Hz Watch streaming infrastructure

The watch and iPhone code got a full streaming-reliability upgrade
that landed as commits H1 / H3 / H4 over 2026-05-22:

- **H1 — Disk spill instead of drop** (`MotionManager.swift`). What
  used to be lost on buffer overflow or a full `transferUserInfo`
  queue now lands in `watch_spill.jsonl` on watch disk and gets
  drained back through the live path by a timer. Loss-free, survives
  app-kill.
- **H3 — Sample rate and batch size configurable from the phone app**
  (Settings → Motion). Default 50 Hz / batch 10. Watch reports back
  the effective values per command/poll, so the dashboard reflects
  what's actually being captured.
- **H4 — Motion callbacks on a background queue**. Callbacks no
  longer run on the main thread; a staging buffer plus
  `drainStaging()` feeds the main pipeline. Necessary headroom for
  the 100 Hz path.

Server-side: the quality check now accepts both 50 Hz and 100 Hz
(`_VALID_WATCH_HZ = (50.0, 100.0)`); the target Hz per session is
chosen via nearest match. Extending to other rates is one entry in
that tuple.

A `100 Hz vs 50 Hz` ablation ran two Noah self-test sessions
(S032, S033) and compared all four cross-trainings + a CNN baseline
(`reports/100hz_ablation.md`). Result: 50 Hz cross-subject
(AUC 0.928–0.945) ≈ 100 Hz within-subject (AUC 0.924–0.941) —
practically identical, *even though* within-subject should have the
obvious advantage. The CNN converges on the same ceiling.
**Sample rate is not the bottleneck.** Decision: keep 100 Hz as
engineering headroom (more diagnostic room, more sensors later),
but the model argument stays at 50 Hz Nyquist covers wrist writing
(0–15 Hz band).

### Focus-Tracker pivot — deployment story

Started 2026-05-25 as the *wow* hebel for the final presentation.
With the AUC ceiling honestly reached (sync / threshold / sample-rate
all refuted, deep ≈ RF) more decimals on the headline aren't where
the marginal value sits — a live, personalised deployment is.

- **`rf_noah.joblib` — personal model.** Trained on Noah's two
  100 Hz sessions (S032 + S033, 3692 windows), A/B-tested with and
  without z-score (Δ AUC = 0.000, so without). Within-Noah-LOSO:
  acc 0.878 / AUC 0.939 / @5 s AUC 0.973 / @30 s AUC 0.949.
- **`rf_all_live.joblib` — deployment variant of the generic model.**
  Same 10 probands as the headline, but with *pooled* z-score mu/sigma
  baked into the joblib instead of per-session. Live-deployable
  without a calibration phase — the trade-off vs the per-session
  headline is a slightly weaker subject-baseline removal, framed in
  the demo as "generic with deployment-friendly normalisation."
- **Backend** (`src/server/inference.py`, `routes/inference.py`):
  `LiveInference` singleton with a rolling sample buffer, lazy
  joblib load (rf_noah preferred, fallback rf_all_live → rf_all),
  rate-mismatch guard (>20 % fs deviation surfaces as
  `rate_mismatch: true` in the WS payload instead of a junk
  prediction), daily writing-time aggregate. Endpoints:
  `GET /inference/models` (whitelisted), `POST /inference/model`,
  `GET /inference/current`. Reuses `_window_features()` directly so
  live and training share the exact same feature extractor.
- **Persistence** (`src/server/focus_log.py`): append-only CSV at
  `data/inference_log.csv` (gitignored), one row per 1-Hz tick out
  of `_status_loop`. Rate-mismatch ticks skipped so they don't
  pollute the aggregate. Survives server restarts.
- **Frontend.** Live-inference card on the Recording page (state +
  60 s sparkline + in-place model switcher Personal ↔ Generic),
  topbar mini-pill on every page, and a dedicated `#focus` tab as
  the contemplative counterpart to the Recording cockpit: hero mono
  clock `h:mm` left, 24-hour day timeline with writing stretches as
  gradient blocks plus a "now" marker right, seven-bar week frieze
  below.
- 16 new smoke tests across `test_inference.py`,
  `test_inference_endpoints.py`, `test_focus.py` cover feature
  parity, buffer hygiene, z-score honouring, rate-mismatch, model
  whitelist, log persistence, and aggregation gap-closing.

### Sort-Stability bug — discovered and fixed

The most consequential single fix of the project. Found 2026-05-25
during the first live-inference test on the recording page: the
deployed `rf_noah` model predicted writing almost never (acc ~0.57)
even though it benchmarked at 0.876 / 0.938 offline.

Diagnostic signature: ROC-AUC stayed high (0.962 — *ranking* still
works) while accuracy collapsed (0.57 — *decisions* are wrong).
Classic distribution-shift picture: the model knows which windows
are writing, but every writing proba is systematically below 0.5.
Replay through a known session (`scripts/ml/replay_live_inference.py`)
plus a per-feature train-vs-live diff
(`scripts/ml/diff_live_features.py`) localised the divergence to
order-sensitive features only (FFT, jerk, ZCR, correlations —
~52 % of the 88-feature vector).

Root cause: `pandas.sort_values` defaults to `kind='quicksort'`,
which is **not stable**. Watch streams in batches; the server stamps
each batch with `local_ts_ms = int(time.time() * 1000)` so every
sample in a batch shares the same key. Quicksort scrambled
within-batch order — especially bad at 100 Hz with disk-spill drain
(up to 30 samples sharing a timestamp). Live inference's `deque` is
in append order, so it always saw a clean world; the training
pipeline saw a scrambled one. The model was calibrated on the
scrambled world.

Fix: `kind='stable'` plus sort by the per-sample watch clock `ts`
(no ties) instead of `local_ts_ms` in both `src/merge/merge.py` and
`src/features/windows.py`. Re-trained both `rf_noah` and
`rf_all_live`, rebuilt all `{session}_windows.csv`. Full forensic
write-up: `reports/sort_stability_bug.md`.

Important context for the relative comparisons in this report and
last week's: **train and test were symmetrically affected** before
the fix, so all relative comparisons (gap-sweep, N-progression,
sync audit, per-subject threshold, deep models) remain valid. Only
the absolute headline shifts.

### Multi-Rate Watch + default-drift audit

While auditing the quality-check for the 50/100 Hz multi-rate
support, found a default drift in the documentation: the headline
LOSO had moved from `max_gap_ms=2000` to `2500` over the
N = 7 → N = 8 transition, but the code default and CLAUDE.md still
showed `300`. Reconciled — code default now `2500` (matching the
headline pipeline). Documented in CLAUDE.md under "Default-Drift."

---

## Experiments

### New LOSO headline (post Sort-Stability fix)

`train_loso --by person`, RF 200 trees, per-session z-score,
`max_gap_ms=2500`, N = 10:

| Decision-Window | Acc | AUC | F1(writing) |
|:---|---:|---:|---:|
| 1 s (model) | **0.863 ± 0.032** | **0.935 ± 0.032** | **0.875** |
| 5 s burst   | 0.902 ± 0.035 | 0.968 ± 0.030 | — |
| 10 s burst  | 0.885 ± 0.037 | 0.957 ± 0.025 | — |
| 30 s burst  | 0.844 ± 0.034 | 0.922 ± 0.029 | — |

Pre-fix headline (Week 7) was acc 0.856 / AUC 0.928 / F1 0.864.
The lift is **systematic across all four scales** (+0.7 to +1.5 pp)
— the scramble had genuinely burned information that a stable sort
recovers.

### Regression — write-percent across scales

Binary estimator `mean(proba_cal ≥ 0.5)` against the closed pen
truth. 18,544 windows over 10 subjects (OOF regenerated 2026-05-26
on the post Sort-Stability features):

| Decision-Window | n blocks | MAE | RMSE | Bias |
|---:|---:|---:|---:|---:|
| 60 s           | 161 | 7.7 pp | 10.7 pp | +0.57 |
| 300 s          |  40 | 6.9 pp |  9.6 pp | +1.92 |
| whole session  |  10 | **3.6 pp** | 4.3 pp | +0.39 |

The bias stays ~0 on every scale; only the variance shrinks. The
per-second error of the model is overwhelmingly **noise, not
systematic bias** — averaged over a session the writing-share
estimate lands within 3.6 pp of truth.

**Shrinkage caveat.** The first estimator we tried was
`mean(proba_cal)`. Empirically the error correlates with truth at
**r = −0.85** (`err ≈ −0.68·truth% + 36`, zero at ~53 %): few-writers
get over-estimated, heavy-writers under-estimated. The
session-level number looked good (MAE 4.1 pp) only because the
counterbalanced protocol keeps every session in the 46–66 % writing
band — near the 53 % neutral point. The binary estimator doesn't
shrink and was strictly better at every scale (session 4.1 → 3.5,
60 s 10.6 → 7.6, 300 s 8.5 → 6.8). Generalisation to skewed
deployment writing shares remains an open question.

### Engagement — writing share per task

Mean `true_pct` across subjects, from the closed pen truth:

| Task           | Mean true_pct | n |
|----------------|--------------:|--:|
| abschreiben    | 87.1 %        | 10 |
| free_writing   | 82.7 %        | 10 |
| **math**       | **44.0 %**    | 10 |

(S022 / P09 originally fell out of math because the server's marker
writer dropped a single `task_start` write — one-off hiccup, the
~240 s of watch + pen data was intact, only the marker was missing.
Fixed mid-week: the missing marker row was reconstructed from
`study_start + pre_task_seconds`, and `engagement.py::task_timeline`
now does that reconstruction automatically for any future orphan
`task_end` instead of silently dropping the block. With P09 included
and the OOF regenerated on the post Sort-Stability features, math
sits at 44.0 % — still about half the writing share of
abschreiben/free_writing, so the structural-writing-sparse finding
stands. P09 is at 55.1 % true_pct, the highest math share in the
cohort. That isn't a contradiction with last week's soft-writer
label for P09's abschreiben (58 %, well below the cohort norm of
~75–80 %): the `max_gap_ms=2500` closing absorbs P09's many short
micro-pauses while it does *not* absorb the long think-pauses other
subjects show during math, so P09's *post-closing* writing share
comes out high on math even though raw pen-time would land lower.) Pauses
(20 blocks) sit at exactly 0.0 % — the labelling pipeline invents no
writing where there is none. Predicted false-positive rate in pauses
is Ø 6.4 %, with 4/20 pauses above 10 % (P05 ×2 at 20.8 / 15.0, P07
Pause 4 at 18.3, P08 Pause 4 at 11.8) — visible signature of the
phone-typing confound documented last week.

The math finding **structurally validates the N = 10 failure-mode
diagnosis from last week**: P07's 0.58 accuracy in math was never a
model error, math is just writing-sparse for *everyone* (~40 % vs
~83 % for the other writing tasks). The model's per-second writing
share estimate on P07-math is 47.6 % vs truth 39.2 % — well within
the noise floor.

### Deep models — small but consistent advantage at N = 10

LOSO-by-person, matched decision windows, 1-s input
(`reports/model_progression.md` table 1):

| Decision-Window | RF | CNN | LSTM | GRU |
|:---|---:|---:|---:|---:|
| @1 s  | 0.856 / 0.928 | 0.866 / 0.933 | 0.869 / 0.933 | 0.870 / 0.938 |
| @5 s  | 0.887 / 0.960 | 0.892 / 0.963 | **0.909 / 0.966** | **0.907 / 0.967** |
| @10 s | 0.870 / 0.944 | 0.877 / 0.952 | 0.888 / 0.954 | 0.886 / 0.956 |
| @30 s | 0.831 / 0.909 | 0.842 / 0.922 | 0.843 / 0.922 | 0.843 / 0.923 |

5-s input (per-window output is already a 5-s decision; compare to
RF-burst @5 s = 0.887 / 0.960):

| Model | per-window (acc / AUC) | σ(acc) | @30 s (acc / AUC) |
|:---|---:|---:|---:|
| CNN 5 s  | 0.885 / 0.954 | 0.030 | 0.837 / 0.925 |
| GRU 5 s  | 0.876 / 0.946 | 0.041 | 0.833 / 0.921 |
| LSTM 5 s | 0.820 / 0.876 | 0.053 | 0.813 / 0.904 |

(These pre-date the Sort-Stability fix and will get a small uniform
lift on the re-run, but the relative picture holds — both training
and test were scrambled symmetrically.)

Three readings.

- **1-s input: small but consistent advantage for deep.** All three
  deep models sit above RF at *every* one of the four decision
  windows — 12 of 12 cells in favour, ~1–2 pp acc / ~0.5–2.3 pp
  AUC. Each individual cell is inside fold-σ (~0.04), but the
  *direction* is identical across 12 cells and 3 architectures —
  pure noise would give roughly 6/12. Best setup in the panel:
  **LSTM @1 s / GRU @1 s aggregated to 5-s decision ≈ 0.908 /
  0.966** (RF @5 s: 0.887 / 0.960).
- **5-s input is a negative result.** Longer raw context doesn't
  help: CNN @5 s ties RF-burst @5 s, GRU @5 s slightly worse, and
  **LSTM @5 s collapses** (0.820, σ 0.053) — textbook RNN failure
  at long sequences (250 steps) with small N. Longer context is
  better gained by burst-aggregating the 1-s predictions than by a
  larger input window.
- **The gap to perfect is in the labels, not the model.** A
  train/val/test gap diagnostic on the deep runs shows train
  saturates around ~0.89 (not 1.0) and the cross-subject cost
  (train → test) is only ~2–3 pp. Of the ~13 pp gap to a perfect
  classifier, roughly **~11 pp is the label/signal ceiling** and
  only ~2–3 pp is generalisation. This is the formal sister of the
  100-Hz-ablation diagnosis and the sync-audit refutation: model
  tuning is wirkungslos at this dataset size because we're hitting
  the irreducible label noise, not the capacity ceiling.

Critical methodology note: **input window ≠ decision window**.
CNN @5 s input vs RF @1 s output is not a fair comparison; the
correct comparison is CNN @5 s against RF-burst @5 s. Always match
decision windows when comparing model classes.

### Sub-table — 100 Hz vs 50 Hz (selection)

| Train → Test | Model | Acc | @30 s AUC |
|:---|:---:|---:|---:|
| rf_all (50 Hz × 10) → S032 | RF | 0.880 | 0.937 |
| rf_all (50 Hz × 10) → S033 | RF | 0.881 | 0.969 |
| S032 (100 Hz, 1 sess) → S033 | RF | 0.891 | 0.970 |
| S033 (100 Hz, 1 sess) → S032 | RF | 0.875 | 0.926 |

Within-subject 100 Hz vs cross-subject 50 Hz are interchangeable in
both directions despite the obvious within-subject advantage.

---

## Key Insights

- **The intermediate presentation set the bar.** Funk's "best he's
  ever seen" framing means the final presentation has to live up to
  that, not just incrementally extend it. That alone justified the
  mid-week pivot toward the Focus-Tracker deployment story — more
  decimals on the headline aren't where the marginal value sits.
- **Three ceiling hypotheses refuted in one week.** Sync
  (r ≈ −0.2), sample rate (100 Hz ≈ 50 Hz, CNN converges on the
  same ceiling), per-subject threshold (oracle +0.007 only). The
  remaining diagnosis — *real signal ambiguity in 6-channel wrist
  IMU* — now rests on positive eliminations, not absence of
  progress. The honest project-level statement is no longer "we
  could maybe do better" but "we've explored the obvious levers and
  none move it."
- **Negative results are project results.** `reports/sync_audit.md`,
  `reports/per_subject_threshold.md`, `reports/100hz_ablation.md`,
  and the deep-models section of `reports/model_progression.md`
  each close a research path cleanly. That's exactly the kind of
  work the milestone was meant to produce.
- **The Sort-Stability bug was a near-miss for the final
  presentation.** A live deployment demo would have shown 0.57
  accuracy — the worst-case demo failure mode for this project.
  Lesson: end-to-end self-comparison tests are tautological if both
  sides scramble the same way. Real parity needs an *external*
  reference (the same session driven through a different code path,
  bit-comparing the feature vectors). `replay_live_inference.py` is
  now standard for any model that goes to live inference.
- **Shrinkage is a labelling-layer artefact, not a model bug.**
  Averaging probabilities of an uncertain classifier pulls every
  estimate toward 50 %. The session-level MAE of the proba-mean
  estimator looked excellent only because the protocol confined
  every session near the 53 % neutral point. The binary estimator
  is the right deployment default; the proba-mean stays in the
  artefacts as a comparison column.

---

## Plan for Next Week

- **Per-task analysis re-run on the binary estimator.** The diagnoses
  in `reports/regression.md` (Noah −12 pp on every writing task,
  P01 −21 pp on abschreiben, P05 +27 pp on pauses) were done on the
  proba-mean before the shrinkage diagnosis. Re-do on the binary
  estimator and reconcile.
- **Ceiling-artefact decomposition.** The calibrated proba saturates
  near 0.94 (the model never says "100 % sure"). Quantify how much
  of P01's −21 pp on abschreiben is this baked-in saturation effect
  vs. a real P01-specific weakness.
- **Pause-FP rate as a per-subject diagnostic** — surfaces the
  phone-typing confound systematically rather than anecdotally and
  feeds directly into the protocol-v2 conversation.
- **Final presentation structure.** Story arc:
  classification-per-second → regression-per-time-window →
  engagement-per-task → live deployment as punchline. The demo runs
  on the Focus-Tracker pivot — watch streaming, recording page,
  Personal ↔ Generic toggle.
- **Final report writing.** Code work is converging; remaining time
  should weight toward narrative and figure quality, not new
  features.

---

## Contributions

### Noah

- Built the regression and engagement evaluation layers end-to-end
  (`src/evaluation/regression.py`, `src/evaluation/engagement.py`),
  including the isotonic calibration in `train_loso --save-oof`,
  the shrinkage diagnosis, and the switch to the binary estimator.
- Built and ran the deep sequence models (CNN / LSTM / GRU) — full
  pipeline in `src/training/deep/` with matched-decision-window
  comparisons and the train/val/test gap diagnostic.
- Designed, ran, and documented the two ceiling-hypothesis
  refutations: sync audit and per-subject threshold.
- 100 Hz Watch streaming infrastructure (H1 / H3 / H4 commits) and
  the post-implementation ablation that ruled out sample rate as
  the bottleneck.
- Focus-Tracker pivot: Personal `rf_noah` and generic
  `rf_all_live` models, live-inference backend
  (`src/server/inference.py`, `src/server/focus_log.py`),
  Recording-page card, topbar pill, standalone `#focus` tab with
  day timeline and week frieze.
- Sort-Stability bug discovery, diagnosis tooling
  (`replay_live_inference.py`, `diff_live_features.py`), fix, and
  re-run of all headline numbers.
- Multi-rate quality check and default-drift audit.
- Fixed a one-off marker-writer hiccup that had left S022 / P09
  out of the math engagement aggregation: reconstructed the missing
  `task_start` row and added defensive orphan-end reconstruction to
  `engagement.py::task_timeline` (plus regression tests) so a future
  drop can't silently swallow a block.
- Co-prepared the intermediate presentation with Taji.

### Taji

- Co-delivered the intermediate presentation with Noah, built around
  the N = 10 LOSO result, the Study Mode protocol, and the two
  failure modes identified the week before.

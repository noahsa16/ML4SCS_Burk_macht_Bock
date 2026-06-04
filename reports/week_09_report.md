# Week 09 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Act on Prof. Funk's / Prof. Wehrli intermediate-presentation feedback that
`userAcceleration` without gravity throws away useful information —
the wrist's orientation relative to gravity is informative for
writing. Concretely: capture `motion.gravity` on the watch, build the
two-pool (Legacy / Modern) data architecture end to end so old and new
sessions can coexist, record the first Modern-pool proband, and test
*honestly* whether gravity actually lifts the score. Plus a few
deployment-polish items carried over from the Focus-Tracker pivot
(VL-monitor live card, 9-channel live inference).

---

## Work Done This Week

### Two-pool architecture (Legacy 6ch / Modern 9ch)

The dataset's 10 LOSO probands were all recorded before gravity
capture existed, and `motion.gravity` cannot be reconstructed from
`userAcceleration` after the fact. Rather than discard 10 subjects or
block everything on re-recording, the pipeline now distinguishes two
pools and lets them coexist:

| Pool | Hz | Watch channels | Features/window | Content |
|---|---:|---:|---:|---|
| **Legacy** | 50 | 6 (ax/ay/az + rx/ry/rz) | 88 | The 10 LOSO probands + history |
| **Transition** | 100 | 6 | 88 | S032, S033 (100 Hz self-tests pre-gravity) |
| **Modern** | 100 | 9 (+ gx/gy/gz) | 92 | All sessions from 2026-05-26 |

- **Watch capture** (`MotionManager.swift`): now streams 9 channels
  per sample — `userAcceleration` (ax/ay/az), `rotationRate`
  (rx/ry/rz), and `motion.gravity` (gx/gy/gz) as a separate vector.
  `ax/ay/az` stay gravity-free; total acceleration is always
  recoverable as `(ax+gx, …)`. Schema migration through the whole
  capture chain: `WATCH_FIELDNAMES` + Pydantic envelope + CSV writer
  extended with `gx/gy/gz`.
- **Pool detection is runtime-derived**, not a new `sessions.csv`
  column. `_load_watch_timeline` parses `gx/gy/gz` when the columns
  exist; `_session_facts` aggregates `gravity_rows`;
  `/sessions/{id}/report` exposes `has_gravity` + `pool`
  (`legacy` | `modern`). A session is classified by what's actually in
  its CSV, so legacy data needs no migration.
- **Gravity feature module** (`src/features/gravity.py`), integrated
  into `build_windows`. The 4 gravity features are appended only when
  the merged CSV carries `gx/gy/gz`; otherwise they come back NaN so
  legacy sessions never crash the pipeline. Key correctness fix:
  `tilt_change` is the **angle between consecutive gravity vectors**
  (`arccos(dot(g_i, g_{i+1}) / (|g_i|·|g_{i+1}|))`), *not* a per-axis
  mean — the per-axis version systematically underestimates rotations
  by a factor of ~0.66.
- **Pool-aware LOSO**: `train_loso --pool {auto,legacy,modern}` with
  strict `has_gravity` detection. `auto` drops the gravity columns
  globally when the set is mixed (NaN-padding from the concat would
  otherwise crash `RF.fit`). Critical guard: with `--pool != auto`,
  `--save-final-model` / `--save-cv-csv` / `--save-oof` write to
  `*_modern.*` / `*_legacy.*` siblings, so the generic `rf_all.joblib`
  consumed by live inference + regression + engagement is never
  silently overwritten with a pool-specific model.
- **Cross-pool bridge** (`src/features/downsample.py`): anti-aliased
  decimation 100 → 50 Hz (`scipy.signal.decimate`, 8th-order
  Chebyshev I, `zero_phase=True` to avoid the time shift that would
  break pen alignment) + optional gravity-column drop. Combined with a
  new `--watch-suffix` flag on `merge`, a Modern session can be viewed
  as Legacy and folded into the 10-proband Legacy LOSO pool.
- Backward-compat HTTP tests for `POST /watch` covering both legacy
  (6-channel) and modern (9-channel) payloads.

### First Modern-pool session — S038 / P12

**S038 (P12, study v1, ~16 min, 100 Hz + gravity, σ ok / quality
ok)** — the first full-protocol proband recorded on the gravity
setup, and the data the gravity question is decided on. Three shorter
recordings did not make the bar: S035 (P10) and S036 (P11) were too
short (< 1 min, `bad`), and S037 was a ~2.5 min Noah gravity smoke
test (`[TEST] 100HZ + G`).

### Gravity feature ablation — does gravity help?

The core analytical question of the week. The gravity block was first
built with 6 features and then trimmed to **4**:

- `grav_mag_mean` / `grav_mag_std` **dropped**: `motion.gravity` is a
  unit vector by CoreMotion definition (`|g| ≈ 1.000` always), so its
  magnitude has zero variance. Both scored exactly 0.0 importance in
  the S038 within-session RF (ranks #93 / #94 of 94). This is a
  unit-vector trap — they *look* like reasonable features but carry no
  information; caught by importance, not intuition.
- `tilt_*_std` **rejected** in a separate experiment (within-S038, did
  not help — see Experiments). The orientation signal sits in the
  *means* (wrist pose relative to gravity), not in its variability.
- Final block: `tilt_x/y/z_mean` + `tilt_change` (4 features,
  88 → 92).

**Result (within-S038, temporal 80/20, on-the-fly):**

| Feature set | Acc | AUC | F1(writing) |
|:---|---:|---:|---:|
| 88 (no gravity) | 0.760 | 0.813 | 0.560 |
| 92 (with gravity) | **0.770** | **0.836** | 0.567 |
| Δ | +0.011 | **+0.023** | +0.007 |

Seed robustness (10 seeds, same split): **ΔAUC +0.021 ± 0.006,
positive in 10/10 seeds**; Δacc +0.007 ± 0.007, positive in only 7/10
(noise around 0). Reading: gravity consistently lifts the *ranking*
(AUC) but barely moves the 0.5 *decision*. The signal sits in the
orientation means — physically plausible, since the hand pose while
writing differs systematically from the resting pose, while its jitter
does not.

**Caveat — N = 1, not a finding yet.** This is one proband,
within-session. 10/10 seed consistency rules out *seed* noise only —
**not** subject idiosyncrasy: the gain could be P12's specific wrist
pose in this one session. A real cross-subject Modern LOSO needs ≥ 2
Modern-pool probands, and only S038 exists today (S037 too short /
low-sync; S032/S033 are 100 Hz *without* gravity). Until a second
Modern proband, **"gravity helps" is a hypothesis, not a finding.**
100 Hz itself is already refuted as a model gain
(`reports/100hz_ablation.md`); gravity is the single open lever.
Documented in `reports/feature_ablation.md`.

### 9-channel live inference

`src/server/inference.py::append_sample` now optionally takes
`gx/gy/gz`; the rolling buffer carries 10-tuples
`(ts, ax…rz, gx, gy, gz)` — gravity in the **same** tuple, a
structural alignment guarantee against the Sort-Stability bug class
(no separate re-join that could drift). `predict()` detects a Modern
model via `set(GRAVITY_FEATURE_NAMES).issubset(feature_cols)` and
composes the full 92 features through the same `build_windows`
extractor used in training (feature-parity test in
`test_inference.py`). Legacy streams store NaN; a Modern model on a
Legacy stream short-circuits with `{missing_channels: true}` (no
predict on NaN, analogous to the `rate_mismatch` guard), and a Legacy
model simply ignores the extra columns. **Open deployment step:** no
Modern joblib exists in `models/` yet — once one is trained
(`--pool modern --save-final-model` → `rf_all_modern.joblib`), its
stem must be added to the picker whitelist `_USER_FACING_MODEL_NAMES`
to appear in the UI switcher.

### VL-monitor live writing-prediction card + misc

- **Admin (VL-monitor) page** got a compact live writing-prediction
  strip between the controls and the live counters: large writing/idle
  label left, 60 s SVG sparkline right, proba-% and model-ID badge top
  right, three data-states (writing green / idle neutral /
  rate_mismatch yellow) matching the Recording-page card. Reads the
  existing `live_inference` / `live_sparkline` WS broadcast — no new
  API, no extra server calls. Lets the experimenter watch the live
  prediction from the second screen without touching the proband's
  display.
- **Focus-Tracker startup-strategy spec**
  (`docs/specs/2026-05-28-focus-tracker-startup-design.md`) — design
  sketch for how the live tracker should behave at session start.
- Housekeeping: CI fix (synthetic inference-model fixture, since
  `models/` is gitignored), Xcode `xcuserdata/` untracked, README
  updated for the N = 10 headline, live inference, and the pool
  architecture.

---

## Experiments

### Gravity block (88 vs 92) — within-S038

Reproduced from the section above for the experiment record:

| Feature set | Acc | AUC | F1(writing) | ΔAUC (10 seeds) |
|:---|---:|---:|---:|---:|
| 88 (no gravity) | 0.760 | 0.813 | 0.560 | — |
| 92 (with gravity) | 0.770 | 0.836 | 0.567 | **+0.021 ± 0.006 (10/10)** |

Conclusion: encouraging but **not yet a finding** — within-session,
N = 1. Needs a second Modern proband for a cross-subject verdict.

### `gyro_acc_energy_ratio` (#3) — N = 10 Legacy LOSO

Candidate "rotation-dominance" feature, tested on the full headline
pool (the one place we *can* run a real LOSO today):

| | Acc | AUC | F1(writing) |
|:---|---:|---:|---:|
| 88 features (without #3) | 0.863 ± 0.032 | 0.935 ± 0.032 | 0.875 |
| 89 features (with #3) | 0.863 ± 0.031 | 0.935 ± 0.032 | 0.875 |

Δacc −0.0006, ΔAUC 0.0000 — no movement. **Dropped.** Consistent with
the feature-engineering ceiling: engineered features don't move the RF
on the Legacy pool; the ceiling is signal ambiguity (P07/P09), not
feature count.

---

## Key Insights

- **Acting on  gravity feedback was right, but the payoff is
  still unproven.** Gravity is the only model lever not yet refuted
  (sync, sample rate, per-subject threshold, deep ≈ RF, engineered
  features all eliminated), and the first signal is encouraging — AUC
  up in 10/10 seeds. But it's one proband. The discipline that carried
  the project so far applies here too: do **not** promote a hypothesis
  to a finding before a second Modern proband. The honest line for the
  final presentation is "gravity looks promising on our first
  9-channel subject; the cross-subject test is the immediate next
  step," not "gravity helps."
- **The two-pool design is the honest way to add a feature mid-dataset.**
  Old sessions can't get gravity retro-fit. Rather than throw away 10
  probands or block on re-recording, the pool split lets both coexist,
  and the anti-aliased downsample bridge lets a Modern session be
  treated as a Legacy view so it can still join the 10-proband LOSO.
- **The unit-vector trap.** `grav_mag_mean/std` looked like sensible
  features but carry zero information, because `motion.gravity` is a
  unit vector. Importance ranking (0.0, #93/#94) caught it; intuition
  didn't. Worth remembering for any future normalised sensor channel.
- **Same-tuple buffering is a deliberate defense against the
  Sort-Stability bug class.** Carrying gravity in the same buffer
  tuple as accel/gyro means there is no second stream to re-align —
  the alignment is structural, not a join that could drift. That
  design choice is a direct lesson from last week's
  near-miss.

---

## Plan for Next Week

- **Record a second (ideally third) Modern-pool proband.** This is the
  single highest-value next step — it's what turns the gravity
  *hypothesis* into a *finding* either way, via a real cross-subject
  Modern LOSO. Everything else gravity-related is blocked on it.
- **Train `rf_all_modern`** (`--pool modern --save-final-model`) once
  there are enough Modern subjects, and add its stem to the live
  picker whitelist so the Personal ↔ Generic ↔ Modern switch is real
  in the demo.
- **Final presentation + report.** Code work is converging; remaining
  time should weight toward narrative and figure quality. Story arc
  unchanged: classification-per-second → regression-per-time-window →
  engagement-per-task → live deployment as punchline, now with the
  gravity strand as the "what's next" honest open question.

---

## Contributions

### Noah

- Two-pool architecture end to end: watch gravity capture, schema
  migration through the capture chain, runtime pool detection in the
  quality engine, `src/features/gravity.py`, pool-aware
  `train_loso --pool`, the `downsample` cross-pool bridge, and the
  `--watch-suffix` merge flag.
- Recorded the first Modern-pool proband (S038 / P12) and ran the
  gravity feature ablation, including the 6 → 4 feature trim, the
  unit-vector diagnosis, the `tilt_*_std` rejection, the 10-seed
  robustness check, and the N = 1 caveat write-up
  (`reports/feature_ablation.md`).
- 9-channel live inference support (`src/server/inference.py`) with
  the same-tuple buffer, Modern-model detection, `missing_channels`
  guard, and feature-parity test.
- VL-monitor live writing-prediction card, Focus-Tracker startup
  spec, and the CI / housekeeping fixes.
- `gyro_acc_energy_ratio` ablation on the N = 10 Legacy LOSO
  (dropped).

### Ben

- _to be filled in_

### Taji

- _to be filled in_

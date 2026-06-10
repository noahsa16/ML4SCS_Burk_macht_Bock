# Week 10 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Close the two open threads from week 09: record more Modern-pool
probands and decide the gravity question cross-subject. Then fold the
Modern probands into the headline pool (N=10 → 14) and clean up the
pipeline so multiple data shapes (50 Hz / 100 Hz / 100 Hz + gravity)
coexist without overwriting each other.

## Work Done This Week

### Three new Modern-pool probands

**P13/S039, P14/S040 (2026-06-05) and P15/S041 (2026-06-08)** — all
study v1, ~16 min, 100 Hz + gravity, verdict `usable`. The Modern pool
now has 4 full-protocol probands (P12–P15). Alignment note: S039's
σ = −2.73 is below the σ ≤ −3 training gate (manual review of the
alignment plot pending) — ironically it is the *strongest* Modern fold,
which argues against a label-shift problem.

### Gravity verdict — cross-subject ✗, within-subject ✓

The core result of the week. New `--drop-gravity` flag enables a
**paired 92-vs-88 ablation on identical folds, sessions and seed**
(Modern LOSO, N=4):

| Fold | Δacc (gravity effect) | ΔAUC |
|---|---:|---:|
| P12 | +0.014 | +0.002 |
| P13 | +0.003 | +0.001 |
| P14 | **−0.038** | **−0.013** |
| P15 | +0.004 | +0.002 |
| **Mean** | **−0.005** | **−0.003** |

The within-S038 gain (ΔAUC +0.021, 10/10 seeds) does **not** transfer:
`tilt_*_mean` encodes subject-specific wrist pose; with 3 training
subjects per fold the RF learns pose boundaries that transfer
negatively to a subject with a different writing posture (P14).
**Gravity is a personalization signal, not a generalization signal** —
still a candidate for the personal Focus-Tracker model line, dropped
from the cross-subject feature set, capture continues (not
retro-imputable; revisit at N ≥ 6). This closes the last open model
lever: sync ✗, 100 Hz ✗, per-subject threshold ✗, deep ≈ RF,
engineered features ✗, gravity cross-subject ✗.
Details: `reports/feature_ablation.md`.

### New headline: N=14 cross-subject LOSO

P12–P15 folded into the legacy pool as anti-aliased 50 Hz views
(downsample bridge → `merge --watch-suffix legacy` →
`features --merged-suffix legacy`):

| Decision window | Accuracy | ROC-AUC |
|---|---:|---:|
| 1 s | **0.855 ± 0.034** | **0.929 ± 0.034** — F1(w) 0.862 |
| 5 s | 0.899 ± 0.036 | 0.962 ± 0.030 |
| 10 s | 0.882 ± 0.033 | 0.952 ± 0.027 |
| 30 s | 0.838 ± 0.037 | 0.917 ± 0.030 |

Three readings: (1) the 7 long-standing folds **gained** +0.8 pp acc /
+0.8 pp AUC vs. the N=7 state (6/7 improved); (2) the drop vs. the
N=10 headline (0.863/0.935) is **cohort hardness, not model
regression** — the 7 newer folds average 0.833 vs. 0.877 for the older
7, σ stable; (3) **N beats Hz+gravity again**: P14 as a 50 Hz view
with 13 training subjects scores 0.851/0.928 vs. 0.802/0.906 in its
own Modern LOSO (3 training subjects, 100 Hz, 92 features).

Promoted to canonical via new `--no-pool-suffix` override:
`rf_all.joblib` + `rf_all_live.joblib` retrained on N=14 (25 936
windows), regression refreshed (**session MAE 4.5 pp, 60 s 8.6 pp** —
shift is the harder cohort, not methodology), engagement heatmap now
14 probands. N=10 archived as predecessor headline.

### Profile-sorted windows + `watch_profile`

Windows now live in `data/processed/windows/{50hz,100hz,100hz_grav}/`
instead of flat — a Modern session coexists natively and as a legacy
view without collisions (previously the view would silently overwrite
the native windows; the documented manual-rename gap in the cross-pool
chain is closed). `src/profiles.py` is the single source of truth
(path resolver, content-derived profile detection, flat-file
migration); `sessions.csv` carries the native shape in a new
`watch_profile` column (same vocabulary, server-written, migrate-on-
read + backfill). Pool selects the folder in `train_loso`
(`legacy`→`50hz`, `modern`→`100hz_grav`, `auto`→native). Two real bugs
surfaced and fixed along the way: legacy watch CSVs carry `ts` in ms
with **reverse-sorted batches** (detection hardened), and the
downsample bridge failed on real data because the watch reports the
*effective* rate (99.5 Hz, not 100) — decimation factor now snaps to
the nominal grid. Suite: 289 tests; Modern LOSO reproduced its numbers
exactly after the migration.

## Key Insights

- **The honest N=1 caveat from week 09 paid out.** The announced risk
  ("the gain could be P12's specific wrist pose") is exactly what the
  cross-subject test found. Not promoting a hypothesis to a finding
  before the data existed was the right call.
- **Cohort hardness ≠ model regression.** Reporting 0.855 @ N=14 over
  0.863 @ N=10 is the stronger scientific claim — the per-fold paired
  comparison (old folds improved) is what makes the drop explainable
  instead of alarming.
- **Layout follows content.** The windows folder is derived from what
  is actually in the file (measured rate + gravity features present),
  never from a manually set flag — the same structural-integrity idea
  as the same-tuple buffer from the sort-stability lesson.

## Plan for Next Week

- **Final presentation + report** — the code work is done; story arc:
  classification/s → regression/time-window → engagement/task → live
  deployment, with the gravity verdict as the closing scientific act.
- Review S039 alignment plot (σ −2.73 below the training gate).
- Optional demo polish: `rf_all_modern` stem into the live-picker
  whitelist (one-liner, only if the Modern switch should be shown).

## Contributions

### Noah

- Recorded P13/S039, P14/S040, P15/S041; processed S041 through the
  pipeline (σ −3.51).
- `--drop-gravity` paired ablation + gravity verdict write-up; Modern
  LOSO N=4.
- Profile-sorted windows architecture (`src/profiles.py`,
  `--merged-suffix`, `watch_profile` column, migration, both bug
  fixes).
- N=14 headline run + promotion (`--no-pool-suffix`, canonical
  artifact retrain, regression/engagement refresh, CLAUDE.md/README).

### Ben

- _to be filled in_

### Taji

- _to be filled in_

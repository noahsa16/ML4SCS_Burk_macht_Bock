# Week 07 Report — Machine Learning for Smart and Connected Systems

## Weekly Goal

Grow the dataset from the 2-person pilot to a real group of subjects,
turn the cross-subject LOSO score into a number we can actually quote,
and prepare the figures and the intermediate presentation for the
milestone.

---

## Work Done This Week

### Data Collection — eight new subjects

The main job this week was recording. The dataset went from **2
subjects to 10**. We ran the full v1 study protocol (W-P-W-P-W,
~15 min: text copying, math tasks, free writing, with pauses in
between) with eight more subjects, P02 through P09. Pilot and dry-run
recordings were flagged as `study_mode='test'` so they stay out of
the training data.

- Every session was checked before being used for training: alignment
  confidence (σ ≤ -3), at least 5 min long, and a sensible mix of
  writing and idle time. Sessions that didn't pass stayed as raw data
  but were not used by the trainer.
- One real-world problem showed up during recording: in P07's pause
  block the subject typed on a phone, and the error analysis later
  found false positives in exactly that window. Phone-typing looks
  similar enough to writing to fool the model. We noted it as a known
  problem for protocol v2.

### Capture-chain reliability

Recording eight sessions back-to-back showed reliability gaps that a
few pilot runs never did:

- **Dropped-batches fix**: closed four spots along the
  watch → iPhone → server path where IMU batches could be lost. This
  matters for label quality — a lost batch is a hole in the data that
  the merge can't tell apart from real idle time.
- **Tunnel fallback chain**: the server connection now falls back
  cloudflare → ngrok → LAN-IP automatically. This is the safety net
  for on-site recordings and for the demo, so a bad venue network
  can't stop a session.

### ML Pipeline — label smoothing and error analysis

- **Label-closing sweep.** `scripts/ml/ablate_gap_loso.py` runs the
  full LOSO at several `max_gap_ms` values. This drove our main
  decision: the label smoothing moved from `300 ms` → `2000 ms` →
  `2500 ms` as the dataset grew. The 300 → 2000 step was the biggest
  single improvement of the whole project.
- **Per-task error analysis.** New scripts in `scripts/analysis/`
  match each test window to the task timeline in `markers.csv`, so we
  can say *which task* a false positive happened in (writing vs.
  pause) instead of just looking at one big confusion matrix.
- **Sanity-check scripts** in `scripts/checks/` for merge quality and
  data gaps — the tooling we needed to check eight new sessions fast.
- The `scripts/` folder was reorganised into `analysis/`, `checks/`,
  `ml/`, `ops/`, `plots/` to keep it tidy.

### Figures generated

A full set of figures was produced for the report and presentation
(scripts in `scripts/plots/`, outputs in `reports/figures/`):

- `confusion_matrix_loso.png`, `loso_bars.png` — overall LOSO result
  and per-subject scores.
- `burst_sweep.png`, `per_block_heatmap_*.png` — how the score
  changes with the decision-window size, and per-subject × per-task
  accuracy heatmaps (this is the figure that shows P07's math-block
  problem).
- `reliability_diagram_*.png` — calibration curves for RF and MLP.
- `svm_pca.png` / `svm_pca_3d.*` — PCA view of the feature space, a
  teaching figure for the presentation.
- `signal_demo*.png` — raw accel/gyro signal with the writing label
  on top.

### Intermediate presentation

The intermediate presentation was prepared together by Noah and Taji.
It is built around the three results of the week: the N = 10 LOSO
score, the working Study Mode protocol, and the two failure modes the
larger dataset revealed.

---

## Experiments

### Dataset growth — LOSO progression

The reported metric is `train_loso --by person` (Random Forest, 200
trees, per-session z-score, label smoothing `max_gap_ms=2500`):

| n_subjects | Change                          | Acc   | AUC   | F1(w) | σ-fold |
|-----------:|---------------------------------|------:|------:|------:|-------:|
| 5          | label smoothing → `2000`         | 0.872 | 0.940 | 0.887 | 0.020  |
| 7          | + P04, P05; smoothing → `2500`    | 0.868 | 0.943 | 0.885 | 0.024  |
| 8          | + P07                            | 0.861 | 0.932 | 0.879 | 0.035  |
| **10**     | **+ P08, P09**                   | **0.856** | **0.928** | **0.864** | **0.032** |

**Headline (N = 10):** accuracy **0.856 ± 0.032**, ROC-AUC
**0.928 ± 0.033**, F1(writing) **0.864**. Burst-aggregated: @10 s
acc 0.870 / AUC 0.944; @30 s acc 0.831 / AUC 0.909.

The score dropped about 0.5 pp from N = 8 to N = 10, but the important
part is that all changes are within fold-σ, and σ even got smaller
(0.035 → 0.032) while adding two subjects. The model is becoming more
stable as the dataset grows — so the project's main idea (a
person-independent writing signal) now rests on 10 subjects, not 2.

### Two failure modes

The bigger dataset broke in two different ways:

- **P07 — noisy errors.** Fails mostly in the math block, because that
  subject wrote very little there (long think-pauses the label
  smoothing can't close). But the errors are noise, not systematic —
  at the 30 s decision window P07's AUC recovers to 0.93. The model
  gets the phase right, just not every single second.
- **P09 — systematic errors.** Pauses are detected well, but both
  writing tasks are weak. This subject writes "softly" with many small
  pauses inside the writing phases. Here burst aggregation makes it
  *worse*, because the errors are clustered in time, not spread out
  as noise.

The two modes need different fixes: P07-type errors are helped by
burst aggregation; P09-type errors need a per-subject threshold or a
softer definition of the writing label.

---

## Key Insights

- **The pilot held up.** Last week's N = 2 reading was AUC ≈ 0.92; at
  N = 10 it is 0.928 ± 0.033. We expected the score to drop once the
  dataset got bigger and small-sample luck washed out. It didn't —
  that is the result this milestone was meant to test honestly.
- **A bigger dataset is worth the effort because it breaks in useful
  ways.** At N = 2 the model looked uniformly good. At N = 10 it showed
  two clear, different failure modes — which tells us exactly what
  protocol v2 has to fix.
- **Label smoothing is a labelling decision, not just tuning.** Moving
  `max_gap_ms` to 2500 ms changes the target from "pen on paper right
  now" to "person is in writing mode (incl. short pauses ≤ 2.5 s)".
  For a writing-time tracker that is the more useful definition.
- **Check the errors before changing the model.** Every time a new
  subject's fold looked weak, the first step was to lay the task
  timeline over the predictions — not to change features or the
  model. That is what found the P07/P09 difference and the
  phone-typing problem.

---

## Plan for Next Week

- Demo on Thursday — run the live capture + inference path end to end,
  with the tunnel fallback chain as the safety net.
- Protocol v2 (after the demo): handle the phone-typing confound in
  the pauses and the math-task think-pause problem. v1 with its
  natural think-pauses is still ecologically valid and will be framed
  in the report as a use-case discussion.
- Try a per-subject decision threshold for the P09-type failure mode,
  since burst aggregation does not help there.
- Keep recording more subjects so the 0.928 AUC keeps tightening.

---

## Contributions

### Noah

- Ran most of the proband recordings (P02–P09) under the v1 protocol,
  including the quality check of each session before using it for
  training.
- Drove the label-smoothing sweep and the `max_gap_ms` 300 → 2500
  decision.
- Built the per-task error-analysis and sanity-check scripts and
  diagnosed the two failure modes (P07, P09) and the phone-typing
  confound.
- Generated the full figure set for the report and presentation.
- Fixed the dropped-batches bug and built the tunnel fallback chain.
- Co-prepared the intermediate presentation with Taji.

### Ben

- _to be filled in_

### Taji

- Co-prepared and delivered the intermediate presentation with Noah,
  built around the N = 10 LOSO result, the Study Mode protocol, and
  the two failure modes.

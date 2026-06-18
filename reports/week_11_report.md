# Week 11 Report — Machine Learning for Smart and Connected Systems

![Web Training Cockpit — launching and live-visualising a LOSO run from the
dashboard (legacy pool, fold 14/15): per-person held-out leaderboard, AUC
over folds, and a live confusion matrix updating as each fold completes.](figures/week_11_training_cockpit.png)

## Weekly Goal

Two threads after the N=14 headline: (1) act on the intermediate-
presentation review and make every reported metric defensible — causal
smoothing, paired significance, leak-free live numbers; (2) find out why
the per-subject "signal-ambiguity ceiling" (P07 in particular) held, and
harden the capture path against the data-integrity issues that surfaced
while recording the newest probands.

## Work Done This Week

### Methodological audit — making the metrics honest

Five corrections from the intermediate-presentation review, each landed
as a self-contained change:

- **Burst aggregation is now causal (trailing, `center=False`).** The
  previous burst numbers smoothed the 1-s probabilities with a
  *centered* rolling mean, which averages in *future* windows —
  inadmissible for a metric sold as live. Under honest trailing
  smoothing the apparent burst gain disappears; the centered numbers
  were ~5–6 pp inflated. A regression test now guards against the
  look-ahead returning.
- **Paired significance gate (Wilcoxon signed-rank).**
  `src/evaluation/significance.py` compares two `loso_cv.csv` on shared
  folds. At fold-σ ≈ 3.4 pp, sub-pp "gains" without p < 0.05 are now
  reported as noise. Mandatory before any "+X pp" claim.
- **Per-session z-score does not leak.** Measured the deployable
  pooled-μ/σ variant against the per-session headline on identical
  folds: pooled 0.863 ≥ per-session 0.855 (Δacc −0.008, p = 0.035
  *favouring pooled*). The honest deployable number is therefore not
  lower than the headline.
- **`max_gap_ms = 2500` reframed as an a-priori label definition**, not
  a test-set-tuned hyperparameter; the gap sweep is a sensitivity check,
  not a selection criterion.
- **Variance-alignment-bias suspicion falsified.** The reviewer worried
  the variance minimisation maps writing onto *quiet* IMU stretches,
  inverting the labels. Pooled kinematics show the opposite: 8/8 jerk
  features are higher for writing (median ratio 1.35) — writing is the
  most dynamic class, not the quietest.

Study protocol **v2 ("Hard Negatives & Edge Cases") is now the
default**, with `soft_writing` / `think_pause_writing` variants aimed at
the two documented failure modes and six wrist-confounding idle tasks
(phone typing, fidgeting, gesturing), counterbalanced via a Williams
Latin square that scales to any task count.

### Capture-clock fix — new N=15 headline 0.872

The week's main result. The merge and windowing ran their label join and
window-centre timeline on the **batch-arrival** clock `local_ts_ms`, not
the **per-sample capture** clock `ts`. `local_ts_ms` is batch-quantised
(all samples of one POST share the server-receive time) and, on
spill-drain stretches, minutes late — so pen labels were assigned to
time-shifted watch samples. Measured: S019/P07 had 33 % of samples
> 2.5 s off (max 42 s); S043/P17 5.3 % (max 13.6 s); stall-free legacy
sessions ≈ 0 %.

Moving both the join and the window timeline onto `ts` (the axis δ was
always optimised against), on the N=15 pool (10 legacy + P12–P15 + P17 as
50 Hz views):

| Decision window | Accuracy | ROC-AUC |
|---|---:|---:|
| 1 s (per window, headline) | **0.872 ± 0.037** | **0.947 ± 0.026** — F1(w) 0.873 |
| 5 s (causal burst) | 0.860 ± 0.044 | 0.933 ± 0.032 |
| 10 s (causal burst) | 0.825 ± 0.049 | 0.906 ± 0.040 |
| 30 s (causal burst) | 0.771 ± 0.051 | 0.856 ± 0.049 |

Note the burst scales now sit *below* the 1-s number — under causal
smoothing, aggregation does not lift the metric, which is the honest
correction to the earlier centered story. Paired before/after (Wilcoxon,
N=15): **15/15 folds better, mean +2.4 pp acc, p = 0.0001** on
acc/AUC/F1. Biggest winner **P07: +8.5 pp acc / +9.3 pp AUC** — the
long-standing per-subject ceiling on that fold was largely time-shifted
labelling, not an irreducible signal problem. Canonical artefacts
(`rf_all.joblib`, `loso_cv.csv`, `loso_oof.csv`) retrained on N=15 + the
fix.

Consequence to flag: the deep / harnet / fusion / window-sweep numbers
all predate the fix (and ran under centered smoothing), so they need
regeneration before they can be compared to this headline.

### Stream-integrity hardening

Recording the newest probands surfaced two reconnect / spill failure
modes; both are now caught:

- **Spill-flush controls + foreign-spill discard.** A force-quit leaves
  orphan samples of a finished session in the watch spill, and the drain
  timer would deliver them into the next session. Added `drain_spill` /
  `clear_spill` commands and an automatic discard of foreign-session
  spill at session start. Orphan samples that reach the server without an
  active session are quarantined to `unsessioned_watch.csv` instead of
  being appended to the last-streamed session.
- **Batch-sequence checks hardened.** `sequence_gaps` was run-length
  based and miscounted out-of-order arrival (batch #1 landing after
  #2–5) as phantom gaps — set-based now. Two new checks:
  `duplicate_samples` (a sample delivered twice with identical ts +
  axes, e.g. spill re-delivery) and `sequence_counter_reset` (the
  run-scoped counter restarting mid-session on reconnect; out-of-order
  arrival is distinguished from genuine reuse). The merge deduplicates
  verbatim re-deliveries on (ts + axes), keep-first.
- **Phone-bridge dedup key fixed.** The iPhone deduplicated batches on
  (sessionId, sequence). Because the watch sequence counter resets to 0
  on every run and a session can span multiple runs, reused low sequence
  numbers collided on that key and would silently drop legitimate
  post-reset batches. Re-keyed on the first sample's capture ts —
  monotonic across resets, identical on a true re-delivery.

Suite at 346 tests; the new data-integrity checks verified against real
sessions (S036 = 21 true duplicates, S022 / S044 = 1 / 38 counter
resets, S046 out-of-order correctly not flagged).

## Key Insights

- **A "ceiling" is a hypothesis until the labels are clean.** P07's
  per-subject ceiling survived sync audits, threshold tuning and a
  foundation-model cross-check — yet 8.5 pp of it was a batch-clock
  artefact. The sort-stability lesson repeated: verify the timeline
  before concluding the signal is the limit.
- **Honest reporting costs headline points and is worth it.** Causal
  smoothing removed a 5–6 pp burst "gain" that was future leakage. The
  defensible 1-s number (0.872) is the one to report; the burst scales
  are for use-case framing, not for inflating the metric.
- **Structural fixes beat per-incident patches.** Quarantining
  unsessioned samples and keying dedup on capture ts remove whole
  failure classes (orphan-spill contamination, counter-reset data loss)
  rather than the one session that exposed them.

## Plan for Next Week

- **Regenerate the deep / harnet / fusion / window-sweep numbers** on
  N=15 + capture-clock fix + causal smoothing so they are comparable to
  the 0.872 headline.
- Retrain `rf_all_live.joblib` (still N=14, pre-fix) on the N=15
  pooled-μ/σ pool.
- Final presentation + report: classification → regression → engagement
  → live deployment, with the capture-clock fix as the headline
  correction.

## Contributions

### Noah

- Diagnosed and fixed the capture-clock bug (label timeline on
  per-sample `ts`); N=15 retrain + paired before/after validation.
- Methodological audit: causal burst aggregation, Wilcoxon significance
  gate, leak-free live measurement, alignment-bias falsification.
- Stream-integrity hardening: spill-flush controls, unsessioned-sample
  quarantine, sequence / duplicate / counter-reset checks + merge dedup,
  phone-bridge dedup-key fix.
- Study protocol v2 as default; documentation language cleanup.

### Ben

- _to be filled in_

### Taji

- Conducted additional recording sessions with participants for the experiment in order to further expand the dataset.
- Supported the ongoing data collection process by helping gather more subject-specific recordings for later analysis and model training.
- Searched for relevant scientific papers related to IMU-based writing or activity recognition in order to compare approaches, methods, and reported results.

# Headline Lineage — Cross-Subject LOSO (RF)

The **current** headline lives in `CLAUDE.md` (Project Overview). This file
preserves the full predecessor lineage — every cohort-size step of the RF
LOSO-by-person headline as data collection grew.

## Current (canonical copy in CLAUDE.md)

**N=20 (seit 2026-07-01)** — die 15-Probanden-Kohorte + P26/P27/P29/P31/P32 als
v2-Hard-Negative-Kohorte; RF + per-session z-score + `max_gap_ms=2500` label
closing; Capture-Clock-Fix. 1s-window acc **0.869 ± 0.032**, ROC-AUC
**0.946 ± 0.021**. Burst-aggregiert **kausal**: @5s acc 0.856 ± 0.039 / AUC
0.932 ± 0.026; @10s 0.825 ± 0.046 / 0.907 ± 0.032; @30s 0.771 ± 0.046 /
0.855 ± 0.041. Praktisch **unverändert** ggü. N=15 (0.872/0.947) trotz 5
zusätzlicher, im Schnitt härterer v2-Probanden — die neuen Folds sind eine
Mischung aus sehr schwach (P31 acc 0.784, P17 0.802) und sehr stark (P13 0.908,
P26 0.907), kein systematischer Abfall. Nachgerechnet direkt aus
`models/loso_oof_legacy.csv`; die kanonischen Artefakte `loso_cv_legacy.csv` /
`rf_all.joblib` sind noch auf N=15 (2026-06-20) und regenerations-pflichtig.

**Kohorte inzwischen N=22** (P33/S062 + P34/S063 seit 2026-07-06 collected &
`usable`, Legacy-Views lokal gebaut, noch nicht in der computed Headline). Der
N=22-Refresh (Headline neu rechnen + Winner-Modelle/Seeds/Params auf N=22
nachtrainieren) läuft **ein andermal auf dem Pod**, nicht lokal — der Config-Rang
der HP-Suche ist robust gegen ±2 Probanden, die N=20-Suche bleibt also als
Stufe-1-Selektion gültig, nur die finale Bestätigungszahl wandert auf N=22.

## Vorgänger-Headlines

- **N=15** (post Capture-Clock-Fix, vor N=20-Erweiterung, seit 2026-06-13):
  acc 0.872 ± 0.037 / AUC 0.947 ± 0.026 / F1(w) 0.873; @5s 0.860/0.933,
  @10s 0.825/0.906, @30s 0.771/0.856.
- **N=14** (pre Capture-Clock-Fix): acc 0.855 ± 0.034 / AUC 0.929 ± 0.034 /
  F1(w) 0.862.
- **N=10** (post Sort-Stability-Fix): acc 0.863 ± 0.032 / AUC 0.935 ± 0.032 /
  F1(w) 0.875; @5s 0.902/0.968, @30s 0.844/0.922.
- **N=10** (pre Sort-Stability-Fix, siehe `reports/sort_stability_bug.md`):
  0.856 / 0.928.
- **N=8** gap=2500: acc 0.861 ± 0.035 / AUC 0.932 ± 0.035.
- **N=7** gap=2500: acc 0.868 ± 0.024 / AUC 0.943 ± 0.014; gap=2000:
  acc 0.864 ± 0.026 / AUC 0.940.
- **N=5** gap=2000: acc 0.872 ± 0.020 / AUC 0.940.
- **N=3** gap=300: acc 0.842 ± 0.007 / AUC 0.909 (ExtraTrees).

All pre-Sort-Stability-Fix numbers were computed on systematically noisy
features (train + test symmetrically affected → relative comparisons stay
valid). All pre-Capture-Clock-Fix + `center=True` burst numbers (CNN-Deep,
harnet frozen/finetune, harnet↔RF fusion) are regeneration-pending — see
[experiment_log.md](experiment_log.md).

## Deep-Modell-Headlines (nativ-5s, legacy, post-fix, no-zscore)

- **tcn6-nativ-5s (N=15):** acc 0.922 / AUC 0.978 (σ 0.033) — höchster
  Punktschätzer, schlägt RF-nativ-5s (0.885/0.953) signifikant.
- **TCN-5s (4-Ebenen, N=15):** 0.911 / 0.976; **CNN-5s:** 0.905 / 0.970.
- **tcn6 modern-Pool (N=7, 3-Seed ehrlich):** acc 0.889 ± 0.017 / AUC
  0.968 ± 0.001 — Seed-Rauschen-Floor ±1.7 pp.
- **Deep-HP-Grid (2026-07-06, grouped-5-fold):** `tcn_gru` (TCN6-Trunk +
  GRU) ist Front-Runner — g00 3-Seed 0.9222 ± 0.0036 / AUC 0.9786, über
  tcn6 g00 (0.9196). GPU-Non-Determinismus: dieselbe Config+Seed 0.9271 vs
  0.9106 (±1.6 pp) → nur gepaartes Multi-Seed belastbar.

Detaillierte Deep-/Fusion-/Transfer-Zahlen: [experiment_log.md](experiment_log.md).

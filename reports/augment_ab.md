# Data-Augmentation A/B — konsolidiertes Ergebnis (Negativbefund)

**Frage:** Verbessert On-the-fly-Augmentation der rohen IMU-Fenster die
Deep-Netze (cross-subject)?

**Setup:** paralleles GitHub-Actions-A/B (`.github/workflows/augment.yml` →
`scripts/ml/augment_matrix.py` → `scripts/ml/augment_ab_collect.py`), tcn6 @5 s,
3 Seeds × {aug, no-aug} = 6 Jobs, seed-gemittelt, **gepaarter Wilcoxon**.
Claim-Gate: Gewinn nur, wenn Δ außerhalb des Seed-σ-Bands **und** p < 0.05 auf
acc **und** AUC. Augmentation ist **train-only** (Val/Test nie augmentiert),
label-safe, mit eigenem RNG pro Fold (sauber gepaart). `AUGMENT`-Default = OFF.

## Ergebnisse

| Satz | Pool | N | Δacc (aug − no-aug) | p (acc) | ΔAUC | p (AUC) |
|---|---|---:|---:|---:|---:|---:|
| basic: scale(0.8–1.2) + rotate(±10°) | modern | 8 | +1.55 pp | 0.078 | +0.2 pp | 0.38 |
| basic | legacy | 14 | +0.52 pp | 0.27 | +0.05 pp | 0.25 |
| **rich**: + time-warp/jitter/magnitude, scale(0.7–1.3), rotate(±20°) | modern | 8 | **+1.28 pp** | **0.31** | +0.5 pp | 0.38 |
| rich (unvollständig¹) | legacy | 14 | +0.93 pp | 0.058 | +0.02 pp | 0.39 |

¹ Der legacy-rich-Lauf wurde von GitHub-Actions-Concurrency teils gecancelt
(1 aug-Seed statt 3) → nicht belastbar. Der vollständige legacy-**basic**-Lauf
war bereits klar null.

## Verdikt: **kein Gewinn — auf keinem Pool, mit keinem Satz**

- Beide Sätze verfehlen das Claim-Gate (kein p < 0.05).
- Der **richere** Satz half auf modern sogar *weniger* als das simple
  scale+rotate (+1.28 vs +1.55 pp, schlechteres p).
- **AUC durchweg flach** (alle Δ ≤ +0.5 pp) — der entscheidende Tell:
  Augmentation bewegt die **Accuracy/Kalibrierung** auf einzelnen schwachen
  Folds (größte Bewegung P14/P17/P26 — die hypothetisierten Soft-Writer-/
  Orientierungs-Fälle), aber **keine Trennbarkeit**.

**Interpretation:** Input-Raum-Augmentation erweitert die Abdeckung, kann aber
kein Signal erfinden, das nicht im Signal ist. Das reiht sich in die
dokumentierten Feature-Engineering-Nullbefunde ein (siehe
`reports/feature_ablation.md`, `reports/harnet_transfer.md`): dieselbe Decke,
anderer Hebel. Der ehrliche verbleibende Hebel bleibt **bessere Labels**
(Video/Intent), nicht mehr Augmentation.

Das Tooling bleibt trotz Nullbefund nutzbar: richerer Augment-Satz
(`src/training/deep/augment.py`), tqdm-Fold-Fortschritt, das parallele
A/B-Harness, `AUGMENT`-on/off-Schalter im Sweep.

## Nebenbefunde derselben Session (2026-07-01)

- **gap 2500 vs 3000** (legacy N=14): 2500 acc 0.871 ± 0.030 vs 3000
  0.867 ± 0.039 — 2500 marginal besser *und* stabiler, Δ n.s. (acc p=0.24).
  `max_gap_ms` ist eine Label-Definition, kein Modell-Knopf → **2500 behalten**.
- **grouped-5-fold** (`train_loso --folds 5`, GroupKFold nach Subject,
  leakage-frei): acc 0.867 ± 0.026 vs LOSO 0.871 ± 0.030 — praktisch identisch,
  sogar engere σ. Der 5-fold-Check **korroboriert** die LOSO-Headline (kein
  Fold-Struktur-Artefakt); random-5-fold hätte sie via Leakage aufgebläht.

# Deep×Deep-Ensemble: inception × tcn_bigru

Legacy-Pool, nativ-5s, grouped-5-fold, 45271 Fenster. Beide Netze frisch trainiert, gepaart auf identischen Folds (gleicher Fold-Seed, einzige Variable = Architektur).

## Per-Fold acc±σ / AUC (nativ-5s)

| Arm | acc±σ / AUC |
|---|---|
| inception solo | 0.922±0.014 / 0.976 |
| tcn_bigru solo | 0.908±0.039 / 0.971 |
| **Ensemble (mean)** | 0.924±0.027 / 0.979 |

## Der entscheidende Test: Residuen-Korrelation

- **r(a−y, b−y) = +0.708**  → Fehler stark korreliert, kaum Fusions-Spielraum.

## Gepaarter Wilcoxon (Ensemble vs. solo)

- Ensemble vs **inception** (acc): median Δ +0.0104, p=0.6250 → n.s.
- Ensemble vs **inception** (AUC): median Δ +0.0032, p=0.1250 → n.s.
- Ensemble vs **tcn_bigru** (acc): median Δ +0.0102, p=0.0625 → n.s.
- Ensemble vs **tcn_bigru** (AUC): median Δ +0.0023, p=0.0625 → n.s.

**Verdikt:** Fusion **hebt inception nicht** (Δ n.s. / ≤ 0) (Δacc vs inception +0.0017, vs tcn_bigru +0.0160).

Rohdaten: `models/deep_deep_fusion_inception_tcn_bigru_cv.csv`.

# TCN6↔RF-Ensemble: hebt Fusion das stärkste Modell?

Legacy-Pool, nativ-5s, LOSO-by-person, 20 Folds, 9093 aligned Fenster.

## Per-Fold acc±σ / AUC (nativ-5s)

| Arm | acc±σ / AUC |
|---|---|
| RF-nativ-5s solo | 0.879±0.027 / 0.953 |
| TCN6-nativ-5s solo | 0.898±0.045 / 0.969 |
| **Ensemble (mean)** | 0.909±0.036 / 0.978 |

## Der entscheidende Test: Residuen-Korrelation

- **r(rf−y, tcn6−y) = +0.599**  → Fehler stark korreliert, kaum Fusions-Spielraum.

## Gepaarter Wilcoxon (Ensemble vs. solo)

- Ensemble vs **TCN6** (acc): median Δ +0.0076, p=0.0364 → SIGNIFIKANT
- Ensemble vs **TCN6** (AUC): median Δ +0.0009, p=0.4304 → n.s.
- Ensemble vs RF (acc): median Δ +0.0327, p=0.0032 → SIGNIFIKANT
- Ensemble vs RF (AUC): median Δ +0.0229, p=0.0000 → SIGNIFIKANT

**Verdikt:** Fusion **hebt** den TCN6 (vs TCN6-solo: Δacc +0.0115, ΔAUC +0.0084).

Rohdaten: `models/tcn_rf_fusion_cv.csv`.

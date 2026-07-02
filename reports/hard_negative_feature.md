# Hard-Negative-Feature-Test: Gyro-Achsen-Jerk + Accel-rx-Korrelation + Ratio

N=20 legacy, LOSO-by-person, 20 Folds. Drei Varianten auf denselben Fenstern (base=88, hard_neg=98, hard_neg_weighted=98+3x-Sample-Weight auf keyboard/phone-Trainingsfenstern).

## LOSO (acc±σ / AUC)

| Metrik | base (88) | hard_neg (98) | hard_neg_weighted (98) |
|---|---|---|---|
| window | 0.869±0.032 / 0.946 | 0.869±0.031 / 0.946 | 0.868±0.033 / 0.945 |
| @5s | 0.857±0.041 / 0.932 | 0.857±0.040 / 0.932 | 0.857±0.040 / 0.931 |

## Signifikanz gegen base

| Variante | Δacc (window) | Δacc (@5s) |
|---|---|---|
| hard_neg | median -0.0008, p=0.2976 (n.s.) | median -0.0003, p=0.7323 (n.s.) |
| hard_neg_weighted | median +0.0002, p=0.3760 (n.s.) | median +0.0000, p=0.9702 (n.s.) |

## ZIELCHECK: keyboard/phone-FPR

| Task | base | hard_neg | hard_neg_weighted |
|---|---|---|---|
| keyboard_typing | 0.343 | 0.358 | 0.348 |
| phone_typing | 0.243 | 0.243 | 0.286 |

## Lesart

Erfolg = keyboard/phone-FPR sinkt UND LOSO-acc nicht signifikant schlechter. hard_neg isoliert den Feature-Effekt, hard_neg_weighted zusaetzlich den Trainings-Gewichtungs-Effekt — Vergleich beider zeigt, ob neue Features oder staerkeres Gewicht auf bekannten Fenstern der wirksamere Hebel ist.

Rohdaten: `models/hard_neg_oof_{base,hard_neg,hard_neg_weighted}.csv`.

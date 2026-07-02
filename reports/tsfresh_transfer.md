# tsfresh-Winner-Transfer: 88 vs 130 (destillierte Autokorr/Quantile/CQ/CID)

N=20 legacy, LOSO-by-person, 20 Folds, ALLE Fenster (natürliche Klassenverteilung — Transfer-Test des Subsample-Befunds aus `models/tsfresh_importances.csv`).

## LOSO (acc±σ / AUC)

| Metrik | baseline (88) | winners (130) | gepaart |
|---|---|---|---|
| window | 0.869±0.032 / 0.946 | 0.874±0.034 / 0.949 | Δ(winners−base) median +0.0048, p=0.0073 → SIGNIFIKANT |
| window-AUC | | | Δ(winners−base) median +0.0026, p=0.0002 → SIGNIFIKANT |
| @5s | 0.857±0.041 / 0.932 | 0.858±0.041 / 0.933 | Δ(winners−base) median -0.0002, p=0.5595 → n.s. |
| @5s-AUC | | | Δ(winners−base) median +0.0006, p=0.0037 → SIGNIFIKANT |

## keyboard/phone-FPR

| Task | baseline (88) | winners (130) | Δ |
|---|---|---|---|
| keyboard_typing | 0.343 | 0.336 | -0.007 |
| phone_typing | 0.243 | 0.225 | -0.018 |

## Lesart

Erfolg = window-acc UND -AUC signifikant über base (Trennbarkeitsgewinn hält auf natürlicher Verteilung). Dann sind die 42 Winner headline- und live-relevant (billig in _window_features portierbar, kein tsfresh-Dep).

Rohdaten: `models/tsfresh_winners_oof_{base,winners}.csv`.

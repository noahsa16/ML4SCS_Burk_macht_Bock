# harnet↔RF-Fusion: Ensemble + Stack (harnet5)

## Frage

Bringt es etwas, harnets Foundation-Repraesentation an den Baseline-RF (88 Hand-Features) zu koppeln — als Proba-Ensemble oder als zusaetzliches Feature (Stack 88+1)? Beide leakage-bewusst im LOSO-by-person, Vergleich auf nativer Decision-Skala (5s). Erwartung nach dem r≈0.92-Befund: gedaempft.

## Per-Window-Fehler-Korrelation (der entscheidende Test)

- Proba-Korrelation RF↔harnet: **r = +0.646**
- **Residuen-Korrelation** (Fehler RF vs. Fehler harnet): **r = +0.574**

Fusion kann nur helfen, wenn die Fehler *dekorreliert* sind. Die Residuen sind stark korreliert — die beiden Modelle irren an denselben Fenstern, kaum Fusions-Spielraum. Das ergaenzt die bisher nur per-Fold gemessene Korrelation (r≈0.92) um die window-genaue Sicht.

## Ergebnis (acc/AUC)

| Modell | per-window | @5s | @10s | @30s |
|---|---|---|---|---|
| RF-Headline (publiziert) | 0.899/0.962 | 0.899/0.962 | 0.882/0.952 | 0.838/0.917 |
| RF baseline (88) | 0.856/0.923 | 0.899/0.957 | 0.882/0.947 | 0.839/0.917 |
| harnet allein | 0.830/0.894 | 0.852/0.920 | 0.862/0.931 | 0.838/0.914 |
| Ensemble (mean) | 0.875/0.949 | 0.888/0.958 | 0.880/0.952 | 0.847/0.923 |
| Stack (88+1) | 0.886/0.946 | 0.904/0.963 | 0.890/0.954 | 0.847/0.923 |

**Verdikt:** Fusion **hebt die Headline nicht** (Δ in der Streuung) (native 5s: Ensemble ΔAcc -0.011/ΔAUC +0.001; Stack ΔAcc +0.005/ΔAUC +0.006, jeweils vs. baseline-88 im selben Lauf). Damit ist auch die Window-Level-Frage beantwortet: die Fehler sind korreliert, Fusion ist kein freier Headline-Sprung — Szenario (a), die Decke bleibt die Signal-Ambiguitaet.

## Leakage-Hinweis

Das Ensemble ist vollstaendig sauber (Mittel zweier OOF-Vorhersagen des gehaltenen Probanden). Der Stack nutzt das Standard-Stacking-CV-Rezept (globale harnet-OOF als Feature) mit milder Optimistik fuer die Trainings-Probanden; da das Ergebnis dennoch ~null ist, bleibt der Befund robust.

Rohdaten: `models/harnet_fusion_harnet5.csv`.

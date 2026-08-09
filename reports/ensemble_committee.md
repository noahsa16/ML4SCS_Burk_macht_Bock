# N-Wege-Ensemble-Komitees (Post-Processing auf OOF-CSVs)

Mitglieder: rf5, tcn6. Legacy-Pool, nativ, LOSO-by-person, 9093 aligned Fenster. Reines Post-Processing (kein GPU/Retraining).

## Solo-Baselines (per-Fold acc/AUC)

| Modell | acc | AUC |
|---|---|---|
| tcn6 | 0.8977 | 0.9692 |
| rf5 | 0.8791 | 0.9532 |

## Komitees — alle Kombinationen (nach acc)

Δacc = Ensemble − stärkstes Solo-Mitglied; r = mittlere Residuen-Korrelation (niedrig = mehr Fusions-Spielraum); p = gepaarter Wilcoxon vs. bestes Solo.

| Komitee | acc | AUC | r_resid | vs. best solo | Δacc | p | sig |
|---|---|---|---|---|---|---|---|
| rf5+tcn6 | 0.9092 | 0.9775 | +0.599 | tcn6 (0.8977) | +0.0115 | 0.0364 | **JA** |

## Lesart

**1 Komitee(s) heben das jeweils beste Solo-Mitglied signifikant** (p<0.05, Δacc>0): `rf5+tcn6` (Δ+0.0115)

Rohdaten: `models/ensemble_committee.csv`.

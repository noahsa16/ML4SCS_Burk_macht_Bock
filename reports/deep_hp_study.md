# Deep-HP-Studie — playbook-fairer Architektur-Vergleich (Suchphase)

Pool=legacy @ 5s | N=20 Folds | Sobol n_trials=16/Arch @ Seed 42 |
max_epochs=120 (Fairness-Cap) | infeasible=0

Quelle: GitHub-Actions-Run 28527728688 (dispatch 2026-07-01, nach 16,5 h
manuell beendet). 64 von 96 Trials abgeschlossen; die Sieger-@3-Seed-
Varianzstufe (collect-Job) ist **noch nicht gelaufen** — alle Zahlen
unten sind Ein-Seed-Punktschätzer mit dokumentiertem Seed-Rauschen-Floor
±1,7 pp und Max-Selektions-Bias (Bestwert aus 7–16 verrauschten Trials
überschätzt systematisch).

## Trial-Abdeckung

| Arch | Trials | fehlend |
|---|---|---|
| cnn | 16/16 | — |
| lstm | 16/16 | — |
| tcn | 16/16 | — |
| tcn6 | 9/16 | t2 t4 t5 t6 t10 t12 t13 (Run-Abbruch) |
| gru | 7/16 | t2 t4 t5 t7 t9 t10 t12 t13 t14 (Run-Abbruch) |
| transformer | 0/16 | alle — OOM, siehe unten |

**Transformer-Totalausfall:** alle Trials crashen in
`src/training/deep/train_loso.py::predict_proba` — der komplette
Train-Split geht in *einem* Forward durchs Modell; die Self-Attention
materialisiert dabei Batch×Heads×250×250-Matrizen (gemessen: 40,4 GB
Alloc auf einem 16-GB-Runner). Kein Trainings-, sondern ein
Inferenz-Batching-Problem. Zweiter Defekt: der Workflow-Step pipet den
Trial-Befehl in eine `while`-Loop ohne `pipefail` — die Crashes wurden
verschluckt, alle 11 gelaufenen Transformer-Jobs meldeten „success"
ohne Artefakt.

## Sieger je Architektur (@1 Seed Suche, nach accuracy)

| model | lr | dropout | batch | weight_decay | accuracy | roc_auc | best_epoch |
|---|---|---|---|---|---|---|---|
| tcn6 | 0.002107 | 0.049 | 128 | 1.39e-04 | **0.9194** | 0.9755 | 6.5 |
| gru | 0.005025 | 0.466 | 64 | 2.87e-05 | **0.9185** | 0.9743 | 9.5 |
| lstm | 0.0065 | 0.173 | 32 | 3.89e-05 | 0.9077 | 0.9705 | 17.5 |
| tcn | 0.000238 | 0.119 | 64 | 1e-06 | 0.9054 | 0.9732 | 17.9 |
| cnn | 0.000617 | 0.36 | 32 | 2.23e-04 | 0.8972 | 0.9666 | 11.4 |

Referenz auf derselben N=20-Kohorte, nativ-5s: RF 0.879 ± 0.027 /
AUC 0.953; tcn6 mit Default-HPs (ein Seed, Fusion-Lauf) 0.898 ± 0.045.

## HP-Sensitivität (min/median/max acc über die Sobol-Trials)

| model | min | median | max | std | n |
|---|---|---|---|---|---|
| tcn6 | 0.893 | 0.910 | 0.919 | 0.009 | 9 |
| cnn | 0.873 | 0.890 | 0.897 | 0.007 | 16 |
| tcn | 0.842 | 0.885 | 0.905 | 0.021 | 16 |
| gru | 0.494 | 0.905 | 0.918 | 0.219 | 7 |
| lstm | 0.493 | 0.641 | 0.908 | 0.128 | 16 |

Lesart:
- **tcn6 ist gleichzeitig bestes UND robustestes Modell** — schlechtester
  von 9 Sobol-Punkten immer noch 0.893. Die bisherige tcn6-Präferenz war
  also kein Default-Tuning-Glück; das war die Kernfrage der Studie.
- **GRU ist die Überraschung:** richtig getuned (hohe lr ~0.005, hoher
  Dropout ~0.47) liegt es gleichauf mit tcn6 (Δ 0,1 pp — weit unter dem
  Seed-Floor). Der bisherige Default-HP-Vergleich hat rekurrente Netze
  zu früh abgeschrieben. Aber: hochsensitiv — einzelne Configs
  kollabieren auf Chance-Level (min 0.494).
- **LSTM ist extrem HP-fragil** (Median 0.64 — die Hälfte der Configs
  kollabiert), erreicht mit der besten Config aber 0.908.
- **CNN ist HP-insensitiv, aber gedeckelt** (~0.897) — konsistent mit
  seiner Rolle als schwächstes Deep-Modell @5s.

## Suchraum-Rand-Warnungen

- cnn: bester batch_size=32 am Rand
- lstm: bester batch_size=32 am Rand
- tcn: bester weight_decay=1e-06 am Rand
- tcn6: bester batch_size=128 am Rand

Alle mild (kein lr am Rand, keine best_epoch an der 120er-Decke);
für tcn6/gru wäre batch 256 bzw. der lr-Bereich > 1e-2 die nächste
Erweiterung, lohnt aber erst nach der Varianzstufe.

## Offene Schritte

1. **Sieger-@3-Seed-Varianzstufe** (collect): erst danach sind
   tcn6-vs-gru-Aussagen und der Vergleich gegen die Default-HP-Headline
   belastbar (Winner-CVs → `significance.py`).
2. Fehlende gru/tcn6-Trials nachfahren (Run-Abbruch, keine Fehler).
3. Transformer nach dem predict_proba-Chunking-Fix erneut dispatchen.

Artefakte: `models/deep_hp_study_legacy.csv` (64 Trials),
`models/deep_hp_winners_legacy.csv` (Sieger-Configs) — beide lokal
(models/ ist gitignored), reproduzierbar aus den Run-Artefakten.

# HMM-Hyperparameter-Sweep (smoothing × eps × gamma × mode)

Legacy-Pool, 20 LOSO-Folds, 45,277 Fenster. Baseline (deployed): smoothing=1.0 / eps=1e-3 / gamma=1.0, filter-acc 0.8976.

Modi: **filter** = kausal (Live-Gimmick), **smoother/viterbi** = nicht-kausal (Scrybe-Tagestracker, darf in die Zukunft schauen). Sieger je Modus gepaart (Wilcoxon) vs. Default; **deploy-würdig nur bei p<0.05 ∧ Δ>0** (Anti-Dredge bei 450 Kombis).

| Modus | Sieger-HP | acc | Δ vs default | p | Verdikt |
|---|---|---|---|---|---|
| filter | sm=0.01 / eps=0.05 / gamma=1.25 | 0.8983 | +0.0007 | 0.2226 | n.s. (Rauschen) |
| smoother | sm=2 / eps=1e-05 / gamma=1 | 0.9164 | +0.0000 | 0.3173 | n.s. (Rauschen) |
| viterbi | sm=0.01 / eps=1e-05 / gamma=1 | 0.9165 | +0.0000 | 1.0000 | ≤ default |

## Lesart

Ein Sieger ist nur dann echt, wenn er die Default **signifikant** schlägt — bei 450 Ziehungen hebt reine Ordnungsstatistik das Max fast sicher um Bruchteile. Überlebt kein Modus das Gate, ist die deployte Default bestätigt und die HMM-Knöpfe sind ausgereizt. Ein deploy-würdiger `filter`-Sieger wandert nach `models/hmm_live.json` (+ gamma in `OnlineForwardFilter`); ein `smoother`/`viterbi`-Sieger ist der Decoder für den Tagestracker.

Rohdaten: `models/hmm_hyperparameter_sweep_results.csv`.

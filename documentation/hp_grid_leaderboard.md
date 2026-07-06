# Deep-HP-Grid — Modell-Leaderboard (grouped-5-fold Suche)

**Stand 2026-07-06** · Quelle: wandb-Projekt
`noah-samel-leuphana-universit-t-l-neburg/ML4SCS_HP_Grid` (81 abgeschlossene
Deep-Trials über 18 Modelle) · Rohdaten: `models/hp_grid/wandb_runs.csv`
(gezogen mit `python scripts/ml/pull_wandb_runs.py`).

Bestes Config je Modell (max `cv_mean_acc` über die Trials des Modells),
Legacy-Pool, 5-s-Fenster, grouped-5-fold Suche (`random_state=42`).

| Modell | cv_acc | cv_auc | burst@5s | Seeds | Trials | bestes Config (lr/drop/bs/wd) |
|---|---:|---:|---:|---:|---:|---|
| `tcn_bigru` | 0.9314 | 0.9794 | 0.8671 | 1 | 4 | 0.0003/0.2/64/1e-05 |
| `tcn_gru` | 0.9278 | 0.9805 | 0.8707 | 3 | 40 | 0.0003/0.05/128/0.001 |
| `tcn_bigru_attn` | 0.9257 | 0.9769 | 0.8636 | 1 | 4 | 0.001/0.05/64/1e-05 |
| `inception` | 0.9256 | 0.9777 | 0.8679 | 1 | 4 | 0.001/0.3/64/1e-05 |
| `tcn_gru_attn` | 0.9208 | 0.9754 | 0.8616 | 1 | 4 | 0.001/0.2/64/1e-05 |
| `tcn6` | 0.9196 | 0.9794 | 0.8627 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `tcn6k5` | 0.9194 | 0.9769 | 0.8654 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `tcn6wn` | 0.9187 | 0.9766 | 0.8656 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `tcn6se` | 0.9185 | 0.9793 | 0.8624 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `tcn8` | 0.9139 | 0.9778 | 0.8624 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `tcn6ap` | 0.9129 | 0.9750 | 0.8604 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `gru2` | 0.9125 | 0.9742 | 0.8612 | 1 | 6 | 0.003/0.5/64/1e-05 |
| `tcn_transformer` | 0.9117 | 0.9758 | 0.8595 | 3 | 3 | 0.0003/0.05/64/1e-05 |
| `bigru` | 0.9115 | 0.9708 | 0.8660 | 1 | 6 | 0.001/0.5/64/1e-05 |
| `tcn6w32` | 0.9088 | 0.9753 | 0.8530 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `transformer_p5` | 0.8898 | 0.9615 | 0.8519 | 1 | 1 | 0.0003/0.05/64/1e-05 |
| `tcn` | 0.8811 | 0.9675 | 0.8431 | 1 | 1 | 0.001/0.2/64/1e-05 |
| `transformer` | 0.8802 | 0.9467 | 0.8437 | 1 | 1 | 0.0003/0.05/64/1e-05 |

## Kernbefund: kein Modell bricht aus der Decke aus

Die Top-6 (0.9196–0.9314) liegen in einer Spanne von **1,2 pp — innerhalb des
dokumentierten ±1,7-pp-Rausch-Floors** (Seed + cuDNN-Nichtdeterminismus). Auf
Einzel-Seed-Basis sind sie **statistisch ununterscheidbar**; die gesamte
TCN/GRU-Hybrid-Familie clustert bei 0.91–0.93.

- **`tcn_gru` bleibt der belastbare Front-Runner** — das EINZIGE Modell mit
  Multi-Seed-Bestätigung (3 Seeds / 40 Trials). Zitierfähig ist **nicht** der
  selektions-inflationierte Max (0.9278), sondern das **3-Seed-Mittel des
  g00-Configs: 0.9222 ± 0.0036 / AUC 0.9786** (siehe
  [experiment_log.md](experiment_log.md) §3).
- **`tcn_bigru` (0.9314)** ist die höchste Einzelzahl, aber aus 4 Trials / 1 Seed —
  nicht belastbar über `tcn_gru`s multi-seed-robuste 0.922.
- **`tcn_bigru_attn` (0.9257, neu 2026-07-06)** — BiGRU + Attention-Pooling
  kombiniert (Kreuzung der beiden Einzel-Deltas): landet mittig im Pack, schlägt
  keinen der beiden Eltern (`tcn_bigru` 0.9314 / `tcn_gru_attn` 0.9208) klar.
- **Klar abgeschlagen (außerhalb des Rauschens):** die Transformer
  (`transformer` 0.880, `transformer_p5` 0.890), der 4-Ebenen-`tcn` (0.881),
  `tcn6w32` (0.909). Volle Attention über die Sequenz bzw. mehr Kapazität schaden
  eher.

## Methodik / Caveats

- **Suche, nicht Bestätigung.** Zwei-Stufen-Protokoll: grouped-5-fold Suche (hier)
  rankt Configs → Sieger @3 Seeds auf LOSO-20 bestätigen (`significance.py`). Die
  Config-Rangfolge ist robust gegen ±2 Probanden, aber Einzel-Seed-Deltas < 1,7 pp
  sind Rauschen.
- **Selektionsbias.** `cv_acc` je Modell ist der MAX über dessen Trials; Modelle mit
  mehr Trials (`tcn_gru` 40) haben mehr Ziehungen → höherer erwarteter Max bei
  gleicher wahrer Güte. Die vier Pre-Donnerstag-Hybride (`tcn_bigru`,
  `tcn_bigru_attn`, `inception`, `tcn_gru_attn`) liefen nur je 4 fokussierte Trials
  (Zeitdruck), also unter WENIGER Selektionsdruck als `tcn_gru`.
- **GPU-Nichtdeterminismus.** Dieselbe Config + fixer Seed 42 gab 0.9271 vs 0.9106
  (1,6 pp) durch cuDNN-Autotuning → Einzelzahlen sind grundsätzlich nicht belastbar.

## Offen (Stufe 2)

Sieger-Config @3 Seeds auf LOSO-20 bestätigen — braucht GPU (RunPod), verschoben auf
den nächsten Pod-Lauf zusammen mit dem N=22-Refresh. Bis dahin ist **`tcn_gru` 0.922**
die ehrliche Deep-Headline; die RF-Headline bleibt die Projekt-Headline (1s
0.869/0.946, siehe [headline_history.md](headline_history.md)).

## Verwandt: die Trainings-Achse ist ebenfalls ausgereizt

Der Reweighting-Test (Hard-Negative-Loss-Gewicht am `tcn6`, dieselbe Suche,
2026-07-06) ist NULL: acc 0.9149 → 0.9171 (+0.2 pp), ein Fold −2,6 pp, tief im
Rausch-Floor. Cost-Sensitive-Weighting ist damit über BEIDE Paradigmen falsifiziert
(RF-Features, siehe `reports/hard_negative_feature.md`, + Deep-Repräsentation).
Zusammen mit diesem Leaderboard: sowohl die Architektur- als auch die Reweighting-
Achse sind erschöpft → die Decke ist ein Signal-/Datenlimit, kein Modell-Limit.

## Reproduzieren

```bash
python scripts/ml/pull_wandb_runs.py --out models/hp_grid/wandb_runs.csv
# braucht wandb-Login (WANDB_API_KEY env oder ~/.netrc)
```

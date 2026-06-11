# Transfer-Learning Stufe 2: Oxford ssl-wearables (harnet5), fine-tuned

## Setup

- **Modell:** `harnet5` (pretrained), **end-to-end fine-tuned** — Conv-Trunk + 2-Klassen-Kopf, alle Parameter trainierbar.
- **Input:** 150 Samples = 5 s @ 30 Hz, 3 Accel-Kanaele (userAcceleration ohne Gravity), Stride 2.5 s.
- **Training:** Adam, LR 0.0001, max 15 Epochen, Early Stopping (Patience 3) auf rotierendem Val-Person-Holdout; balancierte CrossEntropy. Modell **pro Fold frisch pretrained** (kein Gewichts-Leak). mean best_epoch 0.8.
- **Protokoll:** LOSO-by-person, gleiche Session-Auswahl wie die RF-Headline (Pool `legacy`).

## Einheiten-Limitation

Input bleibt `userAcceleration` ohne Gravity (Domain-Shift ggue. Biobank-Total-Accel-Pretraining). Anders als beim Frozen-Transfer *kann* Fine-Tuning diesen Shift teilweise wegtrainieren — genau das ist die Hypothese dieser Stufe.

## Ergebnis

Vergleich auf nativer Decision-Skala (5s):

| Variante | per-window acc/AUC | @5s | @10s | @30s |
|---|---|---|---|---|
| RF (N=14) | 0.899/0.962 | 0.899/0.962 | 0.882/0.952 | 0.838/0.917 |
| frozen (Stufe 1) | 0.896/0.958 | 0.881/0.952 | 0.886/0.954 | 0.853/0.927 |
| **fine-tune (Stufe 2)** | 0.896/0.965 | 0.881/0.957 | 0.885/0.958 | 0.849/0.928 |

**Overfit-Diagnose:** Train/Test-Gap = +0.042 (train 0.938 vs test 0.896); per-window-acc-Std 0.045.

**Verdikt:** Fine-Tuning vs. RF@5s: ΔAcc -0.003, ΔAUC +0.003. Vs. Frozen (Stufe 1): ΔAcc +0.001, ΔAUC +0.007. Fine-Tuning bringt gegenueber dem Frozen-Transfer **keinen klaren Gewinn** (Δ innerhalb der Fold-Streuung). Das mean best_epoch 0.8 + Train/Test-Gap +0.042 zeigen: die vortrainierten Features sind schon nahe optimal, weiteres Training ueberanpasst bei N=14 fast sofort. Die Decke bleibt die Signal-Ambiguitaet, nicht die Repraesentation.

Per-Fold-AUC korreliert mit RF@5s: Pearson r = +0.921 (n = 14). Schwaechster Fold: P07.

Per-fold-Rohdaten: `models/harnet_finetune_harnet5.csv`.

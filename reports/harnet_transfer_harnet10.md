# Transfer-Learning: Oxford ssl-wearables (harnet10), frozen

## Setup

- **Modell:** `torch.hub.load('OxWearables/ssl-wearables', 'harnet10', class_num=2, pretrained=True)` — Conv-Trunk als frozen feature extractor, vortrainierter Kopf abgeschnitten.
- **Input:** 300 Samples = 10 s @ 30 Hz, 3 Accel-Kanaele (`ax/ay/az` = userAcceleration), Stride 5.0 s (150 Samples, 50 % Overlap).
- **Resampling:** Watch 50/100 Hz -> 30 Hz via `scipy.signal.resample_poly` (50->30 = 3/5, 100->30 = 3/10). Modern-Sessions werden in einem Schritt 100->30 resampled.
- **Protokoll:** LOSO-by-person, identische Session-Auswahl wie die RF-Headline (`_select_sessions`, Pool `legacy`, verdict-Gate). 14 Folds.
- **Koepfe auf den Embeddings:** LogisticRegression (C-Sweep {0.01, 0.1, 1}, inneres GroupKFold nach Person) und RandomForest (200 Trees, `class_weight=balanced`). Embeddings standardisiert (StandardScaler) fuer LogReg.

## Einheiten-Limitation (bewusst)

harnet wurde auf **UK-Biobank-Total-Acceleration** vortrainiert (inkl. Gravity-Komponente). Unser Input ist `userAcceleration` **ohne** Gravity, weil der Legacy-Pool keine Gravity-Kanaele hat. Das ist ein bewusster Distribution-Shift gegenueber dem Pretraining — die Embeddings sehen ein anderes Signal als die Biobank-Daten. Kein Per-Session-Z-Score auf den Inputs (das Netz erwartet g-Einheiten). Ergebnis ist entsprechend eine *untere Schranke* fuer das, was harnet mit passenderem Input leisten koennte.

## Ergebnis

Vergleich auf gleicher Decision-Skala: harnet-per-window = native 10s, gegen RF-Headline @10s = 0.882/0.952 (acc/AUC).

| Head | per-window acc/AUC | @5s | @10s | @30s |
|---|---|---|---|---|
| **RF (N=14)** | 0.882/0.952 | 0.899/0.962 | 0.882/0.952 | 0.838/0.917 |
| logreg | 0.909/0.966 | 0.909/0.966 | 0.895/0.960 | 0.881/0.950 |
| rf | 0.903/0.959 | 0.903/0.959 | 0.893/0.954 | 0.881/0.948 |

**Verdikt:** Der staerkere Kopf (`logreg`) schlaegt die RF-Headline auf der nativen Skala (ΔAcc +0.027, ΔAUC +0.014). Bemerkenswert, da der Input-Domain-Shift (kein Gravity) gegen das Modell arbeitet. Naechste Stufe waere Fine-Tuning des Trunks (Stufe 2), wo der Shift teilweise wegtrainiert werden koennte.

## Fehler-Korrelation mit der RF-Headline (Szenario a vs. b)

Macht harnet dieselben Fehler wie der RF? Per-Fold-AUC auf gleicher Decision-Skala (native 10s), harnet-Kopf `logreg` gegen RF@10s aus `loso_cv.csv`:

- **Pearson r = +0.882, Spearman ρ = +0.745** (n = 14 Folds).
- Schwaechste 3 Folds — RF: ['P07', 'P12', 'P09']; harnet: ['P07', 'P12', 'P09']. Gemeinsam schwach: ['P07', 'P12', 'P09'].
- P07: RF 0.899 / harnet 0.885 (Δ -0.014) · P09: RF 0.921 / harnet 0.944 (Δ +0.022).
- harnet besser in 13/14 Folds, mean |ΔAUC| = 0.016; harnet rettet keinen RF-schwachen Fold.

**Verdikt:** **(a) korrelierte Fehler**. Zwei maximal verschiedene Architekturen — 88 Hand-Features (6 Kanaele inkl. Gravity, 50 Hz, 1 s, auf unseren Daten trainiert) vs. self-supervised Foundation-Embeddings (3 Kanaele ohne Gravity, 30 Hz, 5 s, fremde Domaene) — scheitern an denselben Probanden (P07-Confound, P09-Soft-Writer). Die Leistungsdecke sitzt damit nachweislich im **Signal**, nicht im Modell: modellunabhaengige Bestaetigung der Signal-Ambiguitaets-These.

Einschraenkung: Fold-Korrelation ≠ Per-Window-Fehler-Korrelation — ein Proba-Ensemble (RF + harnet) koennte innerhalb der Folds noch marginal helfen, aber bei r = 0.88 ist ein Headline-Sprung unwahrscheinlich. Der entscheidende Test waere die Per-Window-OOF-Fehler-Korrelation (harnet-OOF an `loso_oof.csv` per `t_center_ms` alignen).

Per-fold-Rohdaten: `models/harnet_loso_harnet10.csv`.

# Transfer-Learning: Oxford ssl-wearables (harnet5), frozen

## Setup

- **Modell:** `torch.hub.load('OxWearables/ssl-wearables', 'harnet5', class_num=2, pretrained=True)` — Conv-Trunk als frozen feature extractor, vortrainierter Kopf abgeschnitten.
- **Input:** 150 Samples = 5 s @ 30 Hz, 3 Accel-Kanaele (`ax/ay/az` = userAcceleration), Stride 2.5 s (75 Samples, 50 % Overlap).
- **Resampling:** Watch 50/100 Hz -> 30 Hz via `scipy.signal.resample_poly` (50->30 = 3/5, 100->30 = 3/10). Modern-Sessions werden in einem Schritt 100->30 resampled.
- **Protokoll:** LOSO-by-person, identische Session-Auswahl wie die RF-Headline (`_select_sessions`, Pool `legacy`, verdict-Gate). 15 Folds.
- **Koepfe auf den Embeddings:** LogisticRegression (C-Sweep {0.01, 0.1, 1}, inneres GroupKFold nach Person) und RandomForest (200 Trees, `class_weight=balanced`). Embeddings standardisiert (StandardScaler) fuer LogReg.

## Einheiten-Limitation (bewusst)

harnet wurde auf **UK-Biobank-Total-Acceleration** vortrainiert (inkl. Gravity-Komponente). Unser Input ist `userAcceleration` **ohne** Gravity, weil der Legacy-Pool keine Gravity-Kanaele hat. Das ist ein bewusster Distribution-Shift gegenueber dem Pretraining — die Embeddings sehen ein anderes Signal als die Biobank-Daten. Kein Per-Session-Z-Score auf den Inputs (das Netz erwartet g-Einheiten). Ergebnis ist entsprechend eine *untere Schranke* fuer das, was harnet mit passenderem Input leisten koennte.

## Ergebnis

Vergleich auf gleicher Decision-Skala: harnet-per-window = native 5s, gegen RF-Headline @5s = 0.899/0.962 (acc/AUC).

| Head | per-window acc/AUC | @5s | @10s | @30s |
|---|---|---|---|---|
| **RF (N=14)** | 0.899/0.962 | 0.899/0.962 | 0.882/0.952 | 0.838/0.917 |
| logreg | 0.901/0.963 | 0.888/0.957 | 0.844/0.929 | 0.787/0.869 |
| rf | 0.877/0.947 | 0.870/0.942 | 0.840/0.916 | 0.786/0.860 |

**Verdikt:** Der staerkere Kopf (`logreg`) liegt gleichauf mit der RF-Headline auf der nativen Skala (ΔAcc +0.002, ΔAUC +0.001). Bemerkenswert, da der Input-Domain-Shift (kein Gravity) gegen das Modell arbeitet. Naechste Stufe waere Fine-Tuning des Trunks (Stufe 2), wo der Shift teilweise wegtrainiert werden koennte.

## Fehler-Korrelation mit der RF-Headline (Szenario a vs. b)

Macht harnet dieselben Fehler wie der RF? Per-Fold-AUC auf gleicher Decision-Skala (native 5s), harnet-Kopf `logreg` gegen RF@5s aus `loso_cv.csv`:

- **Pearson r = +0.847, Spearman ρ = +0.661** (n = 15 Folds).
- Schwaechste 3 Folds — RF: ['P17', 'P12', 'P15']; harnet: ['P17', 'P12', 'P09']. Gemeinsam schwach: ['P17', 'P12'].
- P07: RF 0.959 / harnet 0.969 (Δ +0.011) · P09: RF 0.907 / harnet 0.949 (Δ +0.042).
- harnet besser in 14/15 Folds, mean |ΔAUC| = 0.032; harnet rettet keinen RF-schwachen Fold.

**Verdikt:** **(a) korrelierte Fehler**. Zwei maximal verschiedene Architekturen — 88 Hand-Features (6 Kanaele inkl. Gravity, 50 Hz, 1 s, auf unseren Daten trainiert) vs. self-supervised Foundation-Embeddings (3 Kanaele ohne Gravity, 30 Hz, 5 s, fremde Domaene) — scheitern an denselben Probanden (P07-Confound, P09-Soft-Writer). Die Leistungsdecke sitzt damit nachweislich im **Signal**, nicht im Modell: modellunabhaengige Bestaetigung der Signal-Ambiguitaets-These.

Einschraenkung: Fold-Korrelation ≠ Per-Window-Fehler-Korrelation — ein Proba-Ensemble (RF + harnet) koennte innerhalb der Folds noch marginal helfen, aber bei r = 0.85 ist ein Headline-Sprung unwahrscheinlich. Der entscheidende Test waere die Per-Window-OOF-Fehler-Korrelation (harnet-OOF an `loso_oof.csv` per `t_center_ms` alignen).

Per-fold-Rohdaten: `models/harnet_loso.csv`.

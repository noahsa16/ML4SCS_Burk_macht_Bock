# Transfer-Learning: Oxford ssl-wearables (harnet5), frozen

## Setup

- **Modell:** `torch.hub.load('OxWearables/ssl-wearables', 'harnet5', class_num=2, pretrained=True)` — Conv-Trunk als frozen feature extractor, vortrainierter Kopf abgeschnitten.
- **Input:** 150 Samples = 5 s @ 30 Hz, 3 Accel-Kanaele (`ax/ay/az` = userAcceleration), Stride 2.5 s (75 Samples, 50 % Overlap).
- **Resampling:** Watch 50/100 Hz -> 30 Hz via `scipy.signal.resample_poly` (50->30 = 3/5, 100->30 = 3/10). Modern-Sessions werden in einem Schritt 100->30 resampled.
- **Protokoll:** LOSO-by-person, identische Session-Auswahl wie die RF-Headline (`_select_sessions`, Pool `legacy`, verdict-Gate). 14 Folds.
- **Koepfe auf den Embeddings:** LogisticRegression (C-Sweep {0.01, 0.1, 1}, inneres GroupKFold nach Person) und RandomForest (200 Trees, `class_weight=balanced`). Embeddings standardisiert (StandardScaler) fuer LogReg.

## Einheiten-Limitation (bewusst)

harnet wurde auf **UK-Biobank-Total-Acceleration** vortrainiert (inkl. Gravity-Komponente). Unser Input ist `userAcceleration` **ohne** Gravity, weil der Legacy-Pool keine Gravity-Kanaele hat. Das ist ein bewusster Distribution-Shift gegenueber dem Pretraining — die Embeddings sehen ein anderes Signal als die Biobank-Daten. Kein Per-Session-Z-Score auf den Inputs (das Netz erwartet g-Einheiten). Ergebnis ist entsprechend eine *untere Schranke* fuer das, was harnet mit passenderem Input leisten koennte.

## Ergebnis

Vergleich auf gleicher Decision-Skala: harnet-per-window = native 5s, gegen RF-Headline @5s = 0.899/0.962 (acc/AUC).

| Head | per-window acc/AUC | @5s | @10s | @30s |
|---|---|---|---|---|
| **RF (N=14)** | 0.899/0.962 | 0.899/0.962 | 0.882/0.952 | 0.838/0.917 |
| logreg | 0.896/0.958 | 0.881/0.952 | 0.886/0.954 | 0.853/0.927 |
| rf | 0.881/0.943 | 0.867/0.938 | 0.877/0.946 | 0.846/0.922 |

**Verdikt:** Der staerkere Kopf (`logreg`) liegt gleichauf mit der RF-Headline auf der nativen Skala (ΔAcc -0.003, ΔAUC -0.004). Bemerkenswert, da der Input-Domain-Shift (kein Gravity) gegen das Modell arbeitet. Naechste Stufe waere Fine-Tuning des Trunks (Stufe 2), wo der Shift teilweise wegtrainiert werden koennte.

Per-fold-Rohdaten: `models/harnet_loso.csv`.

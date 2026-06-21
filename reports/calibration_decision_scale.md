# Decision-Scale-Kalibrierung (Phase 2)

Sind die Wahrscheinlichkeiten ehrlich auf der Skala, die das Produkt anzeigt? ECE (Erwarteter Kalibrierungsfehler, < 0.05 = gut) + Brier (niedriger = besser) je Decision-Scale-Proba, leakage-frei auf `loso_oof.csv` (N=15, `proba_cal` ist per-fold isoton). Figur: `reports/figures/calibration_decision_scale.png`.

| Methode | ECE | Brier |
|---|---|---|
| raw 1s | 0.0198 | 0.0883 |
| cal 1s | 0.0201 | 0.0896 |
| burst 5s | 0.0563 | 0.1072 |
| burst 10s | 0.0456 | 0.1271 |
| burst 30s | 0.0345 | 0.1580 |
| HMM-filter | 0.0567 | 0.0797 |

## Befunde

- **Die 1-s-RF-Proba ist schon ehrlich.** ECE roh `proba_raw` 0.0198 (< 0.05 = gut); die isotone `proba_cal` — fuer die Regressions-Stufe eingefuehrt — verbessert das **nicht** (ECE 0.0201, Brier 0.0883 → 0.0896, beides minimal schlechter). Das per-Session-Z-Score + `class_weight=balanced` liefert von Haus aus brauchbare Wahrscheinlichkeiten — fuers Produkt ist die rohe 1-s-Proba bereits kalibriert, keine Nach-Kalibrierung noetig.

- **Burst-Aggregation verschlechtert die Kalibrierung.** ECE steigt (cal-1s 0.0201 → burst-5s 0.0563 → -10s 0.0456 → -30s 0.0345; am schlechtesten bei 5 s), und der **Brier waechst monoton** mit der Fensterlaenge (0.0896 → 0.1072 → 0.1580) — Aufloesungsverlust, weil das Mitteln die Probas zur Basisrate zieht. Die *thresholdete* Schreibzeit-Entscheidung bleibt davon unberuehrt; nur ein als Konfidenz **angezeigter** Aggregat-Proba waere unter-konfident.

- **Der HMM-Filter ist die nuetzlichste Proba — aber leicht ueber-konfident.** Bester Brier des Panels (0.0797 < roh 0.0883: schaerfste *und* im Schnitt treffsicherste Probas), aber erhoehte ECE (0.0567 > 0.05): der sticky Prior treibt die Konfidenz zu 0/1 — leichte Ueber-Konfidenz, **Vorhersage bestaetigt**. Deployment: 1-s-RF+HMM liefert die beste Entscheidungs-Proba; soll die Pille einen *ehrlichen Prozentwert* zeigen, lohnt eine leichte Nach-Kalibrierung des Posteriors (Platt/isoton, per-fold).

**Caveat:** ECE/Brier sind pooled ueber alle Folds; die Kalibrierung kann per Person streuen. Fuer Deployment-Konfidenz zaehlt der Decision-Scale-Wert, nicht die 1-s-Zahl.

# Deep Hard-Negative-Reweighting: tcn6 baseline vs. keyboard/phone-Gewicht

Pool legacy, tcn6, 5s-Fenster, 5 grouped-Folds, Gewicht **3.0x** auf keyboard/phone-Trainingsfenstern (3334/45271 = 7.4 %). Gepaart pro Fold (gleicher Seed/Init/HP, einzige Variable = sample_weight). Single-Seed (42).

> Report nachträglich aus den persistierten OOF/CV-CSVs erzeugt: der ursprüngliche Lauf (2026-07-06) wurde nach dem CSV-Dump, aber vor dem Report-Schritt beendet. Trainingszahlen unverändert; nur die Aggregation wurde nachgeholt.

## Window-Level (1 Fenster = 1 Entscheidung)

| Metrik | base | weighted | Δ |
|---|---|---|---|
| acc | 0.9162 | 0.9182 | +0.0020 |
| AUC | 0.9682 | 0.9691 | +0.0009 |

## Burst @5s (kausal)

| Metrik | base | weighted | Δ |
|---|---|---|---|
| acc | 0.8641 | 0.8640 | -0.0001 |
| AUC | 0.9429 | 0.9445 | +0.0017 |

## ZIELCHECK: keyboard/phone-FPR (Anteil Tipp-Fenster fälschlich 'writing')

| Task | base | weighted | Δ |
|---|---|---|---|
| keyboard_typing | 0.131 | 0.122 | -0.010 |
| phone_typing | 0.132 | 0.125 | -0.008 |

### FPR über alle Tasks (Kontext — Effekt ist global, nicht gezielt)

| Task | base | weighted | Δ |
|---|---|---|---|
| abschreiben | 0.227 | 0.181 | -0.046 |
| drawing | 0.000 | 0.000 | +0.000 |
| free_writing | 0.177 | 0.141 | -0.036 |
| gesturing | 0.000 | 0.000 | +0.000 |
| keyboard_typing *(gewichtet)* | 0.131 | 0.122 | -0.010 |
| math | 0.143 | 0.114 | -0.029 |
| pause | 0.023 | 0.009 | -0.014 |
| pen_fidgeting | 0.030 | 0.015 | -0.015 |
| phone_scrolling | 0.001 | 0.000 | -0.001 |
| phone_typing *(gewichtet)* | 0.132 | 0.125 | -0.008 |
| soft_writing | 0.237 | 0.166 | -0.071 |
| think_pause_writing | 0.065 | 0.053 | -0.012 |

## Signifikanz (gepaarter Wilcoxon, per-Fold window-acc)

- Δacc (weighted − base): median +0.0015, p=0.6250 (n.s.) (n=5 Folds, min mögliches p=0.0625 → strukturell unterpowert).

## Lesart

Erfolgskriterium war: keyboard/phone-FPR **sinkt** UND acc nicht signifikant schlechter. Beobachtung: acc ist neutral (n.s.), und die FPR sinkt tatsächlich — aber **global über fast alle Tasks**, nicht gezielt auf den gewichteten keyboard/phone-Fenstern. Die gewichteten Tasks profitieren sogar am **wenigsten** (keyboard −0.010, phone −0.008), während nicht-gewichtete Writing-Tasks stärker fallen (soft_writing −0.071, abschreiben −0.046). Das 3×-Gewicht hat dem Netz also nicht beigebracht, Tippen von Schreiben zu trennen, sondern es bloß insgesamt **konservativer** gemacht (seltener 'writing') — eine milde globale Regularisierung.

Das steht **gegen** den RF-Fall (`reports/hard_negative_feature.md`: phone-FPR 0.243 → 0.286, *schlechter*): das Netz konnte seine Repräsentation umformen, wo der RF es nicht konnte, und *schadet* damit nicht. Aber die Effektgröße (Δacc +0.002, FPR-Δ ~−0.01) liegt **komplett im dokumentierten Seed-Rausch-Floor (±1.7 pp)**; bei Single-Seed + n=5 (p=0.625) ist sie nicht von Null unterscheidbar.

**Fazit:** Die Feature-/Emphasis-Achse ist auch end-to-end **nicht der Hebel** für den Tipp-Confound — sie schadet (anders als beim RF) zwar nicht, löst ihn aber nicht gezielt auf. Verbleibender Hebel bleibt: mehr Trainingsdaten mit aggressivem Tippstil (bzw. der Confound ist am 50-Hz-Wrist-IMU intrinsisch isomorph).

Rohdaten: `models/deep_hard_neg_weight_oof.csv`, `models/deep_hard_neg_weight_cv.csv`.

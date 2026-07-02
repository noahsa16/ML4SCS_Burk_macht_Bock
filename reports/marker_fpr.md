# Marker-Per-Task-FPR: Hard-Negatives vs. easy negatives

OOF: `loso_oof_legacy.csv` | 20 Personen | 20 Sessions mit Markern

## Pooled (alle Sessions)

- **Hard-Negatives** (keyboard/phone/fidget/gesture) FPR: **0.168**
- **pause** FPR: **0.036**
- Verhältnis hard/easy: **4.7×**

## FPR je Task-Typ (pooled über Personen)

| task_id | n | FPR |
|---|---|---|
| keyboard_typing | 1668 | 0.360 |
| phone_typing | 1670 | 0.251 |
| pen_fidgeting | 1313 | 0.045 |
| pause | 5393 | 0.036 |
| gesturing | 953 | 0.034 |
| phone_scrolling | 1255 | 0.029 |

## FPR je v2-Proband × Task (die Trainingslücken-Kandidaten)

- **Noah**: keyboard_typing=0.32(n239), pause=0.07(n120), gesturing=0.04(n179), pen_fidgeting=0.04(n180), phone_typing=0.01(n239), phone_scrolling=0.01(n178)
- **P17**: phone_typing=0.68(n234), keyboard_typing=0.63(n237), pause=0.07(n120), gesturing=0.07(n180), phone_scrolling=0.06(n181), pen_fidgeting=0.05(n179)
- **P26**: phone_typing=0.11(n240), pause=0.04(n119), keyboard_typing=0.03(n240), pen_fidgeting=0.02(n240), phone_scrolling=0.01(n180), gesturing=0.00(n119)
- **P27**: keyboard_typing=0.11(n238), phone_scrolling=0.09(n178), phone_typing=0.09(n240), gesturing=0.08(n118), pen_fidgeting=0.02(n238)
- **P29**: keyboard_typing=0.40(n238), phone_typing=0.03(n238), pause=0.02(n119), gesturing=0.01(n120), phone_scrolling=0.01(n179)
- **P31**: phone_typing=0.69(n239), keyboard_typing=0.69(n238), pen_fidgeting=0.01(n238), pause=0.01(n120), gesturing=0.00(n118), phone_scrolling=0.00(n179)
- **P32**: keyboard_typing=0.35(n238), phone_typing=0.17(n240), pen_fidgeting=0.13(n238), phone_scrolling=0.04(n180), gesturing=0.02(n119), pause=0.01(n121)

## Lesart

Hard-FPR ≫ pause-FPR (task-spezifische Cluster auf keyboard/phone) → die Fold-Schwäche ist eine **Hard-Negative-Trainingslücke** (Artefakt). Flache FPR über alle Idle-Tasks → echte **Signal-Ambiguität** (Decke).

Rohdaten: `models/marker_fpr.csv`.

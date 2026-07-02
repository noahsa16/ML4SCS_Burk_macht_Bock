# Rhythmus-Feature-Test: 88 vs 92 (Autokorr-Peak + spektrale Flatness)

N=20 legacy, LOSO-by-person, 20 Folds. Perfekt kontrolliert (dieselben Fenster, nur Feature-Satz unterscheidet sich).

## LOSO (acc±σ / AUC)

| Metrik | baseline (88) | rhythm (92) | gepaart |
|---|---|---|---|
| window | 0.869±0.032 / 0.946 | 0.870±0.032 / 0.946 | Δ(rhythm−base) median +0.0011, p=0.5420 → n.s. |
| @5s | 0.857±0.041 / 0.932 | 0.857±0.041 / 0.932 | Δ(rhythm−base) median +0.0000, p=0.8871 → n.s. |

## ZIELCHECK: keyboard/phone-FPR (sinkt sie durch Rhythmus?)

| Task | baseline (88) | rhythm (92) | Δ |
|---|---|---|---|
| keyboard_typing | 0.343 | 0.336 | -0.007 |
| phone_typing | 0.243 | 0.247 | +0.004 |

## Lesart

Erfolg = keyboard/phone-FPR **sinkt** (zielgenauer Effekt) UND LOSO-acc nicht signifikant schlechter (kein Schaden). Sinkt die FPR nicht, trennen Autokorr/Flatness Tippen nicht von Schreiben — dann ist die Verwechslung tiefer (mehr Daten/anderes Feature nötig).

Rohdaten: `models/rhythm_oof_{base,rhythm}.csv`.

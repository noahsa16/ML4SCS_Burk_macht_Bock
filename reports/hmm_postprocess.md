# HMM-Post-Processing der LOSO-Predictions (kausal)

Zwei-Zustands-HMM (idle/writing) als Post-Processor auf den RF-OOF-Probas, N=20 Folds. Scaled-Likelihood-Hybrid: `proba_cal` ist die Emission, Übergangsmatrix + Prior werden **leakage-frei** pro Fold nur aus den Train-Personen geschätzt (Laplace-Glättung 1). **Headline = kausaler Forward-Filter** `P(state_t | o_1..t)` — kein Look-ahead. Forward-Backward/Viterbi sind die **nicht-kausale Obergrenze** (nutzen die Zukunft).

## Methoden im Vergleich (Mittel ± Std über Folds)

| Methode | kausal | Latenz | accuracy | ROC-AUC |
|---|---|---|---|---|
| RF roh @1s (Floor) | ✓ | 1 s | 0.874 ± 0.034 | 0.949 ± 0.023 |
| Burst @5s (proba_cal) | ✓ | 5 s | 0.858 ± 0.041 | 0.933 ± 0.025 |
| Burst @10s (proba_cal) | ✓ | 10 s | 0.825 ± 0.047 | 0.908 ± 0.032 |
| Burst @30s (proba_cal) | ✓ | 30 s | 0.770 ± 0.048 | 0.855 ± 0.040 |
| **HMM-Filter** | **✓** | **~17 s adaptiv** | **0.899 ± 0.038** | **0.965 ± 0.022** |
| HMM-Smoother (Obergrenze) | ✗ | offline | 0.918 ± 0.043 | 0.976 ± 0.021 |
| HMM-Viterbi (Obergrenze) | ✗ | offline | 0.917 ± 0.044 | — |

**Latenz-Charakterisierung.** Die gelernte Matrix ist klebrig (A[w,w]=0.968, A[i,i]=0.972) → effektives Gedächtnis ~17 s. Der faire Vergleich ist also Burst@10–30s, nicht @5s — und genau dort ist der Rolling-Mean mit ~0.82/0.77 weit schwächer. Der Filter ist **nicht** ein verstecktes langes Fenster: bei vergleichbarer Latenz schlägt er den Rolling-Mean um ~10 pp, weil er bei schwacher Evidenz den Zustand hält und bei starker schnell kippt (adaptiv statt fix-mittelnd).

## Primärtest: HMM-Filter vs. Burst @5s (gleicher Input)

- **accuracy:** Δ = +0.0412  (Wilcoxon p = 0.0000, **signifikant**, N=20)
- **ROC-AUC:** Δ = +0.0311  (Wilcoxon p = 0.0000, **signifikant**, N=20)

*Wert des Look-aheads* (Smoother − Filter): Δacc +0.0184, ΔAUC +0.0118 — so wenig würde eine nicht-kausale (offline) Variante zusätzlich holen; der kausale Filter ist nahe am offline-Optimum.

## Negativkontrolle (Falsifikation: Block-Erkennung?)

Würde die Per-Window-Accuracy nur die langen Label-Blöcke belohnen, bliebe ein klebriges HMM auch ohne echtes Signal hoch. Test: Emission in-session shuffeln (Timing zerstört, Verteilung bleibt) bzw. konstant setzen.

| Emission | acc |
|---|---|
| echte `proba_cal` | **0.899 ± 0.038** |
| in-session geshuffelt | 0.517 ± 0.031 |
| konstant 0.5 | 0.483 ± 0.077 |

Der Kollaps auf Zufall ohne zeit-aligniertes Signal zeigt: der Gewinn ist signalgetrieben, **keine** Block-Erkennungs-Inflation.

## Dissoziation pro Fold: Δ(HMM-Filter − Burst @5s)

| Fold | Klasse | Burst@5s acc | HMM-Filter acc | Δacc |
|---|---|---|---|---|
| Noah | — | 0.907 | 0.933 | +0.0264 |
| P01 | — | 0.893 | 0.929 | +0.0369 |
| P02 | — | 0.871 | 0.914 | +0.0429 |
| P03 | — | 0.860 | 0.909 | +0.0488 |
| P04 | — | 0.867 | 0.908 | +0.0418 |
| P05 | — | 0.873 | 0.909 | +0.0364 |
| P07 | **P07 · Sequenz** | 0.893 | 0.921 | +0.0282 |
| P08 | — | 0.871 | 0.909 | +0.0378 |
| P09 | **P09 · Amplitude** | 0.812 | 0.879 | +0.0674 |
| P12 | — | 0.830 | 0.875 | +0.0449 |
| P13 | — | 0.866 | 0.931 | +0.0649 |
| P14 | — | 0.908 | 0.931 | +0.0232 |
| P15 | — | 0.822 | 0.874 | +0.0526 |
| P17 | — | 0.749 | 0.785 | +0.0356 |
| P26 | — | 0.891 | 0.920 | +0.0290 |
| P27 | — | 0.840 | 0.896 | +0.0563 |
| P29 | — | 0.861 | 0.911 | +0.0502 |
| P31 | — | 0.781 | 0.815 | +0.0336 |
| P32 | — | 0.895 | 0.916 | +0.0207 |
| Taji | — | 0.872 | 0.919 | +0.0472 |

## Vorab-Registrierung — Ausgang

- **P07** (Sequenz-Failure) — erwartet *hilft*: Δacc = +0.0282 → bestätigt.
- **P09** (Amplituden-Failure) — erwartet *null*: Δacc = +0.0674 → **gescheitert**. P09 gewinnt entgegen der Hypothese; die „Amplitude-nicht-Sequenz“-Dichotomie war zu scharf — ein rückgewinnbarer Flacker-Anteil (Negativkontrolle bestätigt Signalbindung) profitiert sehr wohl von Sequenz-Glättung.

## Bottom line

Ein gelerntes 2-Zustands-HMM schlägt den Rolling-Mean (den einzigen bisher getesteten Post-Processor) bei jeder Skala signifikant (p=0.0000) und übertrifft sogar den 1-s-Floor — als **kostenloser Post-Processor auf dem bestehenden RF, ohne Retraining**. Das verfeinert den dokumentierten Befund „kausale Post-Glättung hebt nichts“: der *Rolling-Mean* nicht, ein *HMM* schon. Caveat: ~17 s adaptive Entscheidungs-Latenz (gut für Schreibzeit-Tracking, nicht für 1-s-Auflösung), und es bleibt knapp unter dem nativen Lang-Fenster-TCN (~0.911 @5s) — bricht also die 1-s-Signal-Ambiguitäts-Decke nicht, sondern holt den Lang-Kontext-Gewinn post-hoc statt in der Repräsentation.

**Cross-Model-Generalisierung:** Dieser Gewinn ist RF-1s-spezifisch — auf 5-s- oder Deep-Modellen hilft das HMM nicht (es überglättet leicht). Kontext-Leiter + 2×2-Faktordesign in `reports/hmm_context_ladder.md` (`scripts/ml/hmm_cross_model.py`).

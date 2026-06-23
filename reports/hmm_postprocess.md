# HMM-Post-Processing der LOSO-Predictions (kausal)

Zwei-Zustands-HMM (idle/writing) als Post-Processor auf den RF-OOF-Probas, N=15 Folds. Scaled-Likelihood-Hybrid: `proba_cal` ist die Emission, Übergangsmatrix + Prior werden **leakage-frei** pro Fold nur aus den Train-Personen geschätzt (Laplace-Glättung 1). **Headline = kausaler Forward-Filter** `P(state_t | o_1..t)` — kein Look-ahead. Forward-Backward/Viterbi sind die **nicht-kausale Obergrenze** (nutzen die Zukunft).

## Methoden im Vergleich (Mittel ± Std über Folds)

| Methode | kausal | Latenz | accuracy | ROC-AUC |
|---|---|---|---|---|
| RF roh @1s (Floor) | ✓ | 1 s | 0.881 ± 0.034 | 0.956 ± 0.019 |
| Burst @5s (proba_cal) | ✓ | 5 s | 0.862 ± 0.041 | 0.936 ± 0.027 |
| Burst @10s (proba_cal) | ✓ | 10 s | 0.824 ± 0.044 | 0.907 ± 0.036 |
| Burst @30s (proba_cal) | ✓ | 30 s | 0.772 ± 0.050 | 0.856 ± 0.047 |
| **HMM-Filter** | **✓** | **~16 s adaptiv** | **0.905 ± 0.034** | **0.969 ± 0.018** |
| HMM-Smoother (Obergrenze) | ✗ | offline | 0.920 ± 0.035 | 0.979 ± 0.019 |
| HMM-Viterbi (Obergrenze) | ✗ | offline | 0.918 ± 0.035 | — |

**Latenz-Charakterisierung.** Die gelernte Matrix ist klebrig (A[w,w]=0.969, A[i,i]=0.967) → effektives Gedächtnis ~16 s. Der faire Vergleich ist also Burst@10–30s, nicht @5s — und genau dort ist der Rolling-Mean mit ~0.82/0.77 weit schwächer. Der Filter ist **nicht** ein verstecktes langes Fenster: bei vergleichbarer Latenz schlägt er den Rolling-Mean um ~10 pp, weil er bei schwacher Evidenz den Zustand hält und bei starker schnell kippt (adaptiv statt fix-mittelnd).

## Primärtest: HMM-Filter vs. Burst @5s (gleicher Input)

- **accuracy:** Δ = +0.0435  (Wilcoxon p = 0.0001, **signifikant**, N=15)
- **ROC-AUC:** Δ = +0.0329  (Wilcoxon p = 0.0001, **signifikant**, N=15)

*Wert des Look-aheads* (Smoother − Filter): Δacc +0.0148, ΔAUC +0.0102 — so wenig würde eine nicht-kausale (offline) Variante zusätzlich holen; der kausale Filter ist nahe am offline-Optimum.

## Negativkontrolle (Falsifikation: Block-Erkennung?)

Würde die Per-Window-Accuracy nur die langen Label-Blöcke belohnen, bliebe ein klebriges HMM auch ohne echtes Signal hoch. Test: Emission in-session shuffeln (Timing zerstört, Verteilung bleibt) bzw. konstant setzen.

| Emission | acc |
|---|---|
| echte `proba_cal` | **0.905 ± 0.034** |
| in-session geshuffelt | 0.500 ± 0.023 |
| konstant 0.5 | 0.474 ± 0.073 |

Der Kollaps auf Zufall ohne zeit-aligniertes Signal zeigt: der Gewinn ist signalgetrieben, **keine** Block-Erkennungs-Inflation.

## Dissoziation pro Fold: Δ(HMM-Filter − Burst @5s)

| Fold | Klasse | Burst@5s acc | HMM-Filter acc | Δacc |
|---|---|---|---|---|
| Noah | — | 0.898 | 0.926 | +0.0287 |
| P01 | — | 0.897 | 0.927 | +0.0298 |
| P02 | — | 0.864 | 0.916 | +0.0526 |
| P03 | — | 0.857 | 0.898 | +0.0401 |
| Taji | — | 0.878 | 0.923 | +0.0450 |
| P04 | — | 0.873 | 0.914 | +0.0412 |
| P05 | — | 0.864 | 0.908 | +0.0445 |
| P07 | **P07 · Sequenz** | 0.910 | 0.942 | +0.0326 |
| P08 | — | 0.874 | 0.912 | +0.0378 |
| P09 | **P09 · Amplitude** | 0.824 | 0.889 | +0.0647 |
| P12 | — | 0.822 | 0.871 | +0.0487 |
| P13 | — | 0.877 | 0.935 | +0.0578 |
| P14 | — | 0.904 | 0.925 | +0.0205 |
| P15 | — | 0.834 | 0.889 | +0.0553 |
| P17 | — | 0.745 | 0.798 | +0.0530 |

## Vorab-Registrierung — Ausgang

- **P07** (Sequenz-Failure) — erwartet *hilft*: Δacc = +0.0326 → bestätigt.
- **P09** (Amplituden-Failure) — erwartet *null*: Δacc = +0.0647 → **gescheitert**. P09 gewinnt entgegen der Hypothese; die „Amplitude-nicht-Sequenz“-Dichotomie war zu scharf — ein rückgewinnbarer Flacker-Anteil (Negativkontrolle bestätigt Signalbindung) profitiert sehr wohl von Sequenz-Glättung.

## Bottom line

Ein gelerntes 2-Zustands-HMM schlägt den Rolling-Mean (den einzigen bisher getesteten Post-Processor) bei jeder Skala signifikant (p=0.0001) und übertrifft sogar den 1-s-Floor — als **kostenloser Post-Processor auf dem bestehenden RF, ohne Retraining**. Das verfeinert den dokumentierten Befund „kausale Post-Glättung hebt nichts“: der *Rolling-Mean* nicht, ein *HMM* schon. Caveat: ~16 s adaptive Entscheidungs-Latenz (gut für Schreibzeit-Tracking, nicht für 1-s-Auflösung), und es bleibt knapp unter dem nativen Lang-Fenster-TCN (~0.911 @5s) — bricht also die 1-s-Signal-Ambiguitäts-Decke nicht, sondern holt den Lang-Kontext-Gewinn post-hoc statt in der Repräsentation.

**Cross-Model-Generalisierung:** Dieser Gewinn ist RF-1s-spezifisch — auf 5-s- oder Deep-Modellen hilft das HMM nicht (es überglättet leicht). Kontext-Leiter + 2×2-Faktordesign in `reports/hmm_context_ladder.md` (`scripts/ml/hmm_cross_model.py`).

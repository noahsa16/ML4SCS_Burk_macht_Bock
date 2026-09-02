# HMM-Post-Processing der LOSO-Predictions (kausal)

Zwei-Zustands-HMM (idle/writing) als Post-Processor auf den RF-OOF-Probas, N=32 Folds. Scaled-Likelihood-Hybrid: `proba_cal` ist die Emission, Übergangsmatrix + Prior werden **leakage-frei** pro Fold nur aus den Train-Personen geschätzt (Laplace-Glättung 1). **Headline = kausaler Forward-Filter** `P(state_t | o_1..t)` — kein Look-ahead. Forward-Backward/Viterbi sind die **nicht-kausale Obergrenze** (nutzen die Zukunft).

## Methoden im Vergleich (Mittel ± Std über Folds)

| Methode | kausal | Latenz | accuracy | ROC-AUC |
|---|---|---|---|---|
| RF roh @1s (Floor) | ✓ | 1 s | 0.865 ± 0.035 | 0.942 ± 0.029 |
| Burst @5s (proba_cal) | ✓ | 5 s | 0.861 ± 0.036 | 0.934 ± 0.027 |
| Burst @10s (proba_cal) | ✓ | 10 s | 0.830 ± 0.040 | 0.909 ± 0.031 |
| Burst @30s (proba_cal) | ✓ | 30 s | 0.773 ± 0.041 | 0.856 ± 0.040 |
| **HMM-Filter** | **✓** | **~18 s adaptiv** | **0.898 ± 0.034** | **0.962 ± 0.025** |
| HMM-Smoother (Obergrenze) | ✗ | offline | 0.917 ± 0.036 | 0.973 ± 0.025 |
| HMM-Viterbi (Obergrenze) | ✗ | offline | 0.915 ± 0.037 | — |

**Latenz-Charakterisierung.** Die gelernte Matrix ist klebrig (A[w,w]=0.967, A[i,i]=0.975) → effektives Gedächtnis ~18 s. Der faire Vergleich ist also Burst@10–30s, nicht @5s — und genau dort ist der Rolling-Mean mit ~0.82/0.77 weit schwächer. Der Filter ist **nicht** ein verstecktes langes Fenster: bei vergleichbarer Latenz schlägt er den Rolling-Mean um ~10 pp, weil er bei schwacher Evidenz den Zustand hält und bei starker schnell kippt (adaptiv statt fix-mittelnd).

## Primärtest: HMM-Filter vs. Burst @5s (gleicher Input)

- **accuracy:** Δ = +0.0371  (Wilcoxon p = 0.0000, **signifikant**, N=32)
- **ROC-AUC:** Δ = +0.0276  (Wilcoxon p = 0.0000, **signifikant**, N=32)

*Wert des Look-aheads* (Smoother − Filter): Δacc +0.0187, ΔAUC +0.0112 — so wenig würde eine nicht-kausale (offline) Variante zusätzlich holen; der kausale Filter ist nahe am offline-Optimum.

## Negativkontrolle (Falsifikation: Block-Erkennung?)

Würde die Per-Window-Accuracy nur die langen Label-Blöcke belohnen, bliebe ein klebriges HMM auch ohne echtes Signal hoch. Test: Emission in-session shuffeln (Timing zerstört, Verteilung bleibt) bzw. konstant setzen.

| Emission | acc |
|---|---|
| echte `proba_cal` | **0.898 ± 0.034** |
| in-session geshuffelt | 0.516 ± 0.025 |
| konstant 0.5 | 0.444 ± 0.083 |

Der Kollaps auf Zufall ohne zeit-aligniertes Signal zeigt: der Gewinn ist signalgetrieben, **keine** Block-Erkennungs-Inflation.

## Dissoziation pro Fold: Δ(HMM-Filter − Burst @5s)

| Fold | Klasse | Burst@5s acc | HMM-Filter acc | Δacc |
|---|---|---|---|---|
| P04 | — | 0.865 | 0.911 | +0.0461 |
| P12 | — | 0.827 | 0.870 | +0.0433 |
| P32 | — | 0.892 | 0.913 | +0.0211 |
| P33 | — | 0.821 | 0.853 | +0.0320 |
| P34 | — | 0.844 | 0.865 | +0.0208 |
| P57 | — | 0.915 | 0.945 | +0.0306 |
| P71 | — | 0.879 | 0.895 | +0.0155 |
| P02 | — | 0.852 | 0.906 | +0.0532 |
| P07 | **P07 · Sequenz** | 0.892 | 0.922 | +0.0293 |
| P08 | — | 0.871 | 0.916 | +0.0457 |
| P26 | — | 0.891 | 0.924 | +0.0329 |
| P27 | — | 0.843 | 0.910 | +0.0679 |
| P64 | — | 0.864 | 0.897 | +0.0329 |
| P72 | — | 0.896 | 0.921 | +0.0253 |
| P03 | — | 0.832 | 0.894 | +0.0618 |
| P05 | — | 0.876 | 0.908 | +0.0320 |
| P13 | — | 0.858 | 0.931 | +0.0724 |
| P54 | — | 0.908 | 0.917 | +0.0082 |
| P60 | — | 0.912 | 0.933 | +0.0214 |
| P61 | — | 0.893 | 0.915 | +0.0217 |
| P15 | — | 0.807 | 0.867 | +0.0597 |
| P17 | — | 0.798 | 0.840 | +0.0414 |
| Noah | — | 0.901 | 0.933 | +0.0316 |
| P29 | — | 0.838 | 0.894 | +0.0552 |
| P31 | — | 0.779 | 0.814 | +0.0349 |
| P63 | — | 0.813 | 0.818 | +0.0046 |
| P01 | — | 0.879 | 0.921 | +0.0423 |
| Taji | — | 0.875 | 0.926 | +0.0515 |
| P09 | **P09 · Amplitude** | 0.805 | 0.874 | +0.0691 |
| P14 | — | 0.900 | 0.929 | +0.0292 |
| P66 | — | 0.884 | 0.926 | +0.0418 |
| P73 | — | 0.840 | 0.850 | +0.0102 |

## Vorab-Registrierung — Ausgang

- **P07** (Sequenz-Failure) — erwartet *hilft*: Δacc = +0.0293 → bestätigt.
- **P09** (Amplituden-Failure) — erwartet *null*: Δacc = +0.0691 → **gescheitert**. P09 gewinnt entgegen der Hypothese; die „Amplitude-nicht-Sequenz“-Dichotomie war zu scharf — ein rückgewinnbarer Flacker-Anteil (Negativkontrolle bestätigt Signalbindung) profitiert sehr wohl von Sequenz-Glättung.

## Bottom line

Ein gelerntes 2-Zustands-HMM schlägt den Rolling-Mean (den einzigen bisher getesteten Post-Processor) bei jeder Skala signifikant (p=0.0000) und übertrifft sogar den 1-s-Floor — als **kostenloser Post-Processor auf dem bestehenden RF, ohne Retraining**. Das verfeinert den dokumentierten Befund „kausale Post-Glättung hebt nichts“: der *Rolling-Mean* nicht, ein *HMM* schon. Caveat: ~18 s adaptive Entscheidungs-Latenz (gut für Schreibzeit-Tracking, nicht für 1-s-Auflösung), und es bleibt knapp unter dem nativen Lang-Fenster-TCN (~0.911 @5s) — bricht also die 1-s-Signal-Ambiguitäts-Decke nicht, sondern holt den Lang-Kontext-Gewinn post-hoc statt in der Repräsentation.

**Cross-Model-Generalisierung:** Dieser Gewinn ist RF-1s-spezifisch — auf 5-s- oder Deep-Modellen hilft das HMM nicht (es überglättet leicht). Kontext-Leiter + 2×2-Faktordesign in `reports/hmm_context_ladder.md` (`scripts/ml/hmm_cross_model.py`).

# Per-Subject-Threshold — gegen den P09-Soft-Writer-Modus

Erzeugt von `scripts/ml/per_subject_threshold.py`. Frage: hebt ein
per-Person kalibrierter Entscheidungs-Schwellwert (statt global 0.5) die
schwachen Folds, insbesondere P09?

**Leakage-frei:** Schwellwert wird auf dem ersten Drittel jeder Session
(„Eichphase", F1(writing)-optimal) gewählt, ausgewertet wird nur auf den
restlichen zwei Dritteln. Die 0.5-Baseline läuft auf **denselben** Eval-
Fenstern — fairer Vergleich. Quelle: `models/loso_oof.csv`, `proba_raw`
(reproduziert die LOSO-Headline exakt).

## Ergebnis

**Per-Subject-Threshold hilft nicht** — er verschlechtert F1(writing) im Mittel über N=10.

Aggregat über N=10 (Eval = letzte 2/3, identische Fenster):

- **F1(writing):** Baseline 0.858 → Per-Subject 0.846 (Δ -0.011) → Oracle 0.865
- **Accuracy:** Baseline 0.851 → Per-Subject 0.831 → Oracle 0.857
- 1 Fold verbessert, 7 verschlechtert (ΔF1w-Schwelle ±0.002)

Der **Oracle** tunt den Schwellwert direkt auf den Eval-Labels (Leakage —
nur als Obergrenze). Selbst er hebt F1(writing) nur um +0.007.
Das ist die eigentliche Aussage: auch im allerbesten Fall ist Thresholding praktisch wirkungslos — die Eichphasen-Variante scheitert nicht am Design, sondern Thresholding ist schlicht nicht der Hebel.

Wichtig für die Einordnung: die **ROC-AUC ist invariant unter der
Schwellwert-Wahl** (mathematische Identität, keine Messung). Der
Oracle-Gain misst also ausschließlich, wie flach die F1-Kurve in der
Umgebung von 0.5 verläuft — ein winziger Gain bedeutet, dass 0.5 schon
nahe am F1-Optimum jeder Person liegt.

## P09 (der Ziel-Failure-Modus)

Eichphase wählt für P09 Schwellwert **0.44** (verschoben von 0.5). Auf den Eval-2/3: acc 0.824 → 0.808, F1(w) 0.833 → 0.827.

Der Soft-Writer-Modus profitiert **nicht**. Entscheidend: P09's *Oracle*-Schwellwert ist **0.49** — praktisch 0.5 (Oracle-F1(w) 0.834 vs. Baseline 0.833). Selbst mit Leakage ist 0.5 für P09 schon fast optimal. Die CLAUDE.md-Hypothese „P09 braucht Per-Subject-Threshold“ ist damit **widerlegt** — P09's Fehler sitzen in der Klassen-*Trennung* (Modell/Signal), nicht im Schwellwert. Eine Verschiebung tauscht nur FP gegen FN.

## Per-Session-Tabelle

| session_id | person_id | pct_writing_eval | threshold | thr_oracle | f1_base | f1_subj | f1_oracle | d_f1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S007 | Noah | 0.572 | 0.410 | 0.420 | 0.892 | 0.894 | 0.894 | 0.002 |
| S008 | P01 | 0.583 | 0.290 | 0.540 | 0.901 | 0.869 | 0.904 | -0.032 |
| S009 | P02 | 0.506 | 0.530 | 0.460 | 0.891 | 0.892 | 0.900 | 0.000 |
| S011 | P03 | 0.665 | 0.510 | 0.340 | 0.875 | 0.868 | 0.889 | -0.006 |
| S013 | Taji | 0.473 | 0.500 | 0.440 | 0.834 | 0.834 | 0.846 | 0.000 |
| S015 | P04 | 0.465 | 0.360 | 0.520 | 0.855 | 0.846 | 0.860 | -0.009 |
| S017 | P05 | 0.404 | 0.470 | 0.610 | 0.826 | 0.813 | 0.847 | -0.013 |
| S019 | P07 | 0.465 | 0.190 | 0.420 | 0.788 | 0.750 | 0.791 | -0.038 |
| S020 | P08 | 0.578 | 0.660 | 0.480 | 0.884 | 0.871 | 0.886 | -0.013 |
| S022 | P09 | 0.518 | 0.440 | 0.490 | 0.833 | 0.827 | 0.834 | -0.006 |

## Einordnung

Der Schwellwert verschiebt nur den Trade-off zwischen False Positives und
False Negatives — er kann ein Modell, das zwei Klassen schlecht *trennt*,
nicht besser trennen (die ROC-AUC bleibt unverändert). Ein Per-Subject-
Threshold hilft genau dann, wenn das pro-Person-Optimum systematisch von
0.5 abweicht (z. B. schiefe Schreibanteile, subjekt-abhängige proba-
Kalibrierung). Hilft er nicht, ist die Schwäche im *Signal/Modell* und
nicht in der Schwellwert-Wahl — was den Hebel auf mehr Signal (100 Hz)
zurückverweist.

Warum die Eichphasen-Variante zusätzlich *aktiv schadet*: selbst Personen,
deren Oracle-Schwellwert praktisch 0.5 ist (P08: 0.48), bekommen aus dem
Kalibrier-Drittel einen Schwellwert wie 0.66 zugewiesen. Die Eichphase ist
also nicht nur unrepräsentativ, sondern verschiebt den Schwellwert
systematisch in die falsche Richtung — eine kurze Eichphase am
Session-Anfang ist für Schwellwert-Kalibrierung ungeeignet.

Deployment-Bezug: die Eichphase ist genau der Mechanismus, den der
Per-Session-Z-Score ohnehin braucht — beides ließe sich in derselben
kurzen Kalibrier-Aufnahme zu Sitzungsbeginn erledigen.

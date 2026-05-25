# 100-Hz-Ablation — bringt die höhere Sample-Rate Modell-Verbesserung?

Erzeugt aus `scripts/ml/predict_s032.py`, `scripts/ml/within_noah_100hz.py`
und `scripts/ml/cnn_within_noah_100hz.py`. Frage: bringt der Wechsel auf
100 Hz Watch-Streaming (H1/H3/H4-Commits) für die binäre
Writing-Detection messbare Verbesserung gegenüber dem 50-Hz-Korpus?

## Hintergrund

Bis 2026-05-24 fuhr die Watch-IMU mit 50 Hz; die Streaming-Arbeit der
H1/H3/H4-Commits hat einen verlustfreien 100-Hz-Pfad ermöglicht (Disk-
Spill als Fallback, konfigurierbare Sample-Rate und Batch-Größe,
Background-Queue für Motion-Callbacks). Zwei Selbsttest-Sessions am
2026-05-24 (S032, S033) liefern den ersten 100-Hz-Datenpunkt.

Voraussetzung für jeden ehrlichen A/B war der **`fs_hz`-Auto-Detect-Fix**
in `src.features.windows` und der zugehörige Test in
`tests/test_features_windows.py`: ohne ihn rechnet die Feature-Pipeline
bei 100-Hz-Input still falsch (halbierte Fensterlänge, halbierte
FFT-Bin-Breite, halbierte Jerk-Skalierung). Vor dem Fix wäre jeder
100-Hz-Vergleich Rauschen über einem Bug.

## Sessions

| Session | Proband | study_mode | Hz (eff.) | σ-Align | Dauer | Pen-Zeit |
|---|---|---|---|---|---|---|
| S032 | Noah | test | 99.1 | −5.26 | 933 s | 36.4 % |
| S033 | Noah | test | 99.1 | −4.91 | 922 s | 33.9 % |

Beide v1-Protokoll (Math → Abschreiben → Free Writing mit Pausen),
beide auf dem gleichen Watch, ca. 45 min Abstand.

## Vier unabhängige Konfigurationen

| Train → Test | Modell | acc | F1(w) | AUC | @5s AUC | @30s AUC |
|---|---|---|---|---|---|---|
| **rf_all (50 Hz × 10) → S032** | RF | 0.872 | 0.898 | 0.928 | 0.956 | 0.924 |
| **rf_all (50 Hz × 10) → S033** | RF | 0.871 | 0.894 | 0.945 | 0.983 | 0.967 |
| S032 (100 Hz, 1 Sess) → S033 | RF | 0.882 | 0.907 | 0.941 | 0.983 | 0.970 |
| S033 (100 Hz, 1 Sess) → S032 | RF | 0.872 | 0.901 | 0.924 | 0.954 | 0.925 |
| S032 (100 Hz, 1 Sess) → S033 | **CNN** | 0.875 | 0.897 | 0.939 | 0.986 | 0.974 |
| S033 (100 Hz, 1 Sess) → S032 | **CNN** | 0.866 | 0.902 | 0.908 | 0.953 | 0.926 |

LOSO-Headline-Referenz (RF auf N=10 50-Hz-Probanden, Mittel ± σ):
acc 0.856 ± 0.032, AUC 0.928 ± 0.033, F1(w) 0.864, @5s AUC 0.960,
@30s AUC 0.909.

## Ergebnis

**Die Sample-Rate ist nicht der limitierende Faktor.** Drei Belege:

1. **Cross-Subject 50 Hz ≈ Within-Subject 100 Hz.** Das 50-Hz-Modell
   (10 fremde Probanden) erreicht auf Noahs 100-Hz-Sessions
   AUC 0.928–0.945 / @5s AUC 0.956–0.983. Das 100-Hz-Modell auf Noah
   selbst trainiert erreicht 0.924–0.941 / 0.954–0.983. Die Zahlen sind
   austauschbar — *obwohl* Within-Subject einen erheblichen Vorteil
   genießen sollte (gleicher Wrist, gleiche Handschrift).
2. **CNN konvergiert auf dieselbe Decke wie RF.** Eine zur RF
   architektonisch fundamental verschiedene Modellfamilie
   (convolutional, lernt zeitliche Filter selbst) trifft auf identische
   100-Hz-Daten dieselbe Performance-Decke: AUC 0.908–0.939,
   @5s AUC 0.953–0.986. Wenn 100 Hz Mehr-Signal hätte, das der RF aus
   88 Hand-Features nicht zieht, müsste das CNN es finden — tut es
   nicht.
3. **Physikalisch plausibel.** Schreibbewegungen am Wrist liegen in
   0–15 Hz; 25 Hz Nyquist (= 50 Hz Sample-Rate) deckt das Band
   vollständig ab. Die zusätzliche Bandbreite oberhalb 12.5 Hz im
   100-Hz-Stream enthält im Schnitt kein Schreibsignal.

## Wo die Decke wirklich sitzt

Aus diesem Vergleich + dem LOSO-Verlauf N=3→10 wird klar: die
Performance-Decke (AUC ~0.93 @1s, ~0.96 @5s) wird **nicht** vom Modell
und **nicht** von der Sample-Rate getrieben. Die wahrscheinlichsten
Quellen sind:

- **Label-Ambiguität.** Pen-Truth mit Mikropausen-Closing erzeugt
  Übergangs-Fenster, die strukturell mehrdeutig sind (Übergang
  Schreiben ↔ Pause innerhalb desselben Fensters). Belegt durch P07-
  Math-Fold und P09-Soft-Writer-Modus (siehe CLAUDE.md `N=10`-Eintrag).
- **IMU-Informationsgehalt.** 6-Kanal-Wrist-IMU hat physikalische
  Grenzen; Phone-Typing in Pausen erzeugt schreibähnliche Wrist-Muster
  (siehe P07 Pause 2 und der 9-Fenster-Burst in S032 Pause 4 bei
  t=622 s).
- **Probanden-Heterogenität.** Bei N=10 hilft eine bessere Architektur
  nicht; man bräuchte N=30+ für stabile Generalisierungs-Schätzer.

## Konsequenz fürs Projekt

**Streaming-Pipeline (H1/H3/H4): behalten.** Die 100-Hz-Arbeit ist eine
saubere Engineering-Verbesserung — verlustfreier Pfad, konfigurierbare
Rate, Background-Queue, mehr Headroom für künftige Sensoren. Der
S032-Selbsttest hat zusätzlich den `fs_hz`-Bug in der Feature-Pipeline
aufgedeckt — Wert allein dadurch gerechtfertigt.

**Für die ML-Headline (RF, 50 Hz, 10 Probanden): unverändert.** Die
Decke ist ehrlich. Weitere Recordings sollten weiterhin auf 100 Hz
fahren (kostet nichts, gibt mehr Diagnostik-Spielraum), aber das
*Modell* ist nicht durch Datenrate verbessbar.

**Was 100 Hz *könnte*:** Bei Phone-Typing-Confound-Diskriminierung
hilft die höhere Frequenzauflösung möglicherweise — Phone-Typing hat
höhere Frequenz-Komponenten als Schreiben. Das wäre ein eigenes
A/B-Experiment, nicht Teil dieser Ablation.

## Methodisches Caveat

Beide 100-Hz-Sessions sind vom selben Probanden (Noah) und an
demselben Tag mit ~45 min Abstand. Die "100 Hz bringt nichts"-Aussage
ist robust an dieser Stichprobe, aber:

- Within-subject ist die *schwächere* Generalisierungs-Aussage
  (CLAUDE.md-Punkt). Die Konvergenz mit Cross-Subject-50-Hz-Numbers
  ist trotzdem ein starkes Indiz, gerade *weil* Within-Subject
  eigentlich vorne liegen sollte.
- Echter Test bräuchte ≥3 100-Hz-Probanden mit echtem LOSO. Aufwand
  unverhältnismäßig zum Erwartungswert (siehe oben).

Das CNN-Training läuft 30 fixe Epochen ohne Early-Stop und ohne
Val-Set-Spähung — ein zeitlicher Holdout-Split auf einer einzelnen
Session lieferte einen klassen-unbalancierten Val-Bereich
(letzte 20 % = nur Free-Writing-Task), was Early-Stop sofort triggert
und unfair niedrige Ergebnisse produziert.

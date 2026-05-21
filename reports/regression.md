# Regression — Schreib-Prozent pro Zeitfenster

Fortschritts- und Vorgehens-Log für Prio 1 der Zwischenpräsi-Roadmap:
eine kontinuierliche Schätzung „wie viel Prozent eines Zeitfensters
wurde geschrieben", aufgesetzt als Auswertungs-Schicht über dem
bestehenden LOSO-Klassifikationsmodell.

- Spec: `docs/specs/2026-05-21-regression-schreibprozent-design.md`
- Plan: `docs/plans/2026-05-21-regression-schreibprozent-plan.md`
- Branch: `feature/regression-schreibprozent`

## Ziel

Das Headline-Modell klassifiziert pro 1-s-Fenster binär writing/idle.
Die Regression aggregiert diese Sekunden-Vorhersagen über längere
Zeitfenster zu einer Prozent-Schätzung. Das Modell selbst wird **nicht**
verändert — neue Bewertungs-Metriken (MAE/RMSE/Bias in Prozentpunkten)
plus ein Calibration-Check gegen die Pen-Ground-Truth.

## Vorgehen

### Architektur — zwei über ein CSV entkoppelte Stufen

```
train_loso.py --save-oof
  pro Fold: RF (Headline) + CalibratedClassifierCV(isotonic) parallel
  → models/loso_oof.csv   (session_id, person_id, t_center_ms,
                            label, proba_raw, proba_cal)
                  ↓
src/evaluation/regression.py   (reines Post-Processing, kein Training)
  → models/regression_metrics.csv
  → reports/figures/regression_calibration.png
  → reports/figures/regression_scatter.png
```

Stufe 1 schreibt die out-of-fold-Vorhersagen pro Fenster heraus —
**roh und isotonisch kalibriert**. Die Headline-Metriken
(acc/F1/AUC) laufen unverändert auf der rohen Proba; die Kalibrierung
ist rein additiv. Verifiziert: Headline bleibt 0.856 ± 0.032 /
AUC 0.928 ± 0.033.

Stufe 2 ist trainings-frei: aggregiert die OOF-Vorhersagen auf
Decision-Windows (60 s / 300 s / ganze Session), bildet pro Block
`pred_pct` und vergleicht gegen zwei Wahrheiten. Der Schätzer ist der
**binäre** Anteil `mean(proba_cal ≥ 0,5)` (Begründung s. „Shrinkage"
unten); `pred_pct_proba = mean(proba_cal)` bleibt als Vergleichsspalte
erhalten.

### Zwei Ground-Truth-Definitionen

- **Geschlossene Wahrheit** — Mittel der geschlossenen Window-Labels
  (`max_gap_ms=2500`). Konsistent mit dem, was das Modell vorhersagt
  → Kern-Metrik für die Calibration.
- **Rohe Pen-Wahrheit** — Anteil 50-Hz-Samples mit `label_writing=1`
  aus `merged.csv`. Physikalisch ehrlichste Größe; das Modell
  überschätzt sie systematisch, weil das Closing Mikropausen zur
  Schreibzeit zählt.

### Kalibrierung

`CalibratedClassifierCV(method="isotonic", cv=3)` pro LOSO-Fold,
intern auf den Trainings-Folds cross-validiert → die ausgeschriebene
OOF-Proba ist leakage-frei kalibriert. Bekannte Vereinfachung: `cv=3`
splittet nicht personen-gruppiert (bei N=10 vertretbar).

### Umsetzung

7 Tasks, TDD, subagent-driven. Stufe 2 zuerst gebaut (definiert das
OOF-CSV-Schema), dann `train_loso.py --save-oof` verdrahtet. Der
Schätzer-Wechsel proba-Mittel → binär kam als TDD-Folgeänderung nach
der Shrinkage-Analyse hinzu. Testabdeckung:
`tests/test_regression_eval.py` (9 Tests, trainings-frei, OOF + merged
gemockt). Gesamt-Suite: 151 Tests grün.

## Ergebnisse (N=10, 18.392 Fenster, Stand 2026-05-21)

### Kalibrierung — sehr gut

| | roh | kalibriert |
|---|---|---|
| ECE (Expected Calibration Error) | 0.052 | **0.006** |

Isotonische Kalibrierung senkt den Kalibrierungsfehler um Faktor 8,6.
In allen 10 Reliability-Bins liegt die Lücke vorhergesagt↔empirisch
innerhalb ±0,03 — auf Fenster-Ebene ist die Proba ehrlich. Das
Reliability-Diagramm bleibt die Modell-Qualitäts-Diagnostik.

### Skalen-Effekt — Kern-Story für die Endpräsentation

Binärer Schätzer (`mean(proba_cal ≥ 0,5)`):

| Decision-Window | n | MAE | RMSE | Bias |
|---|---|---|---|---|
| 60 s | 161 | 7,6 pp | 10,4 pp | +0,27 |
| 300 s | 40 | 6,8 pp | 9,2 pp | +1,26 |
| ganze Session | 10 | **3,5 pp** | 4,4 pp | +0,15 |

Der **Bias bleibt auf jeder Skala ~0** — die Schätzung ist unverzerrt.
Was mit der Fenstergröße schrumpft, ist allein die **Streuung**
(MAE 7,6 → 3,5 pp). Das beweist: der Sekunden-Fehler des Modells ist
überwiegend Rauschen, nicht systematische Fehleinschätzung. Über eine
ganze Sitzung schätzt das Modell den Schreibanteil auf ~3,5 pp genau.

Gegen die rohe Pen-Wahrheit: Bias durchgehend ~+21 pp (Überschätzung)
— der erwartete, sauber sichtbare Closing-Effekt.

### Shrinkage — warum der binäre Schätzer

Der ursprüngliche Schätzer `mean(proba_cal)` ist ein **Shrinkage-
Schätzer**: das Mitteln von Wahrscheinlichkeiten eines unsicheren
Klassifikators zieht jede Schätzung zur Mitte (Regression zur Mitte).
Empirisch: Korrelation echter Schreibanteil ↔ Fehler = **−0,85**,
`err ≈ −0,68 × truth% + 36` → Fehler null bei truth ≈ 53 %. Wenig-
Schreiber werden überschätzt, Viel-Schreiber unterschätzt.

Das ist **kein Zufall, der sich glücklich ausgleicht**: Pausen-
Überschätzung und Writing-Unterschätzung sind ein Phänomen von zwei
Seiten (die Mitte liegt bei ~53 %). Der proba-Mittel-Schätzer war auf
Session-Ebene nur deshalb so genau (MAE 4,1 pp), weil das counter-
balanced Protokoll alle Sessions bei 46–66 % Schreibanteil hält —
nahe am 53-%-Neutralpunkt. Auf schiefe Deployment-Anteile (90 % oder
15 % Schreiben) würde der proba-Schätzer deutlich schlechter
generalisieren.

**Fix:** Der binäre Schätzer `mean(proba_cal ≥ 0,5)` schrumpft nicht —
das Schwellen ist eine harte Entscheidung (ein 0,85-Fenster zählt als
100 %, nicht 85 %). Er schlägt das proba-Mittel auf **jeder** Skala
(Session 4,1 → 3,5; 60 s 10,6 → 7,6; 300 s 8,5 → 6,8). Eine LOSO-
leakagefreie *Recalibration* des proba-Schätzers wurde prototypisiert,
half aber nur auf Block-Ebene (60 s/300 s) und verschlechterte die
Session-Skala (4,1 → 5,3) — die Entzerrung verstärkt auf engem
pred-Bereich das Rauschen. Der binäre Schätzer ist die einfachere und
durchgehend bessere Lösung. `pred_pct_proba` bleibt als Vergleichs-
spalte erhalten.

### Per-Task-Fehleranalyse (Marker-Cross-Reference)

Whole-Session-Werte verdecken die Struktur. Aufschlüsselung der drei
auffälligsten Probanden über `data/raw/markers/{session}_markers.csv`.
*Hinweis: diese Analyse wurde auf dem proba-Mittel-Schätzer gemacht —
sie war die Diagnostik, die den Shrinkage-Effekt aufdeckte.*

**Noah (S007), netto −7,0** — unterschätzt **jede** Schreib-Task um
~12 pp, überschätzt **jede** Pause um ~11 pp. FN (writing) und FP
(pause) heben sich auf Session-Ebene teilweise auf.

**P01 (S008), netto −6,6** — gleiches Vorzeichen, aber Abschreiben
kollabiert auf −21 pp (pred 73 % / truth 94 %). Geht über das
Decken-Artefakt hinaus → echte Modellschwäche bei P01's Abschreib-Stil.

**P05 (S017), netto +10,7 — der Ausreißer.** Schreib-Tasks selbst sind
gut (−4,3 / +1,2). Die Überschätzung kommt aus (a) Pausen-FPs von
+27 pp — ~2,5× so hoch wie bei allen anderen, Fidgeting/Phone-Typing-
Confound — und (b) dem Mathe-Block: real nur 22,8 % Schreibzeit, Modell
sagt 44 %.

### Drei Erkenntnisse

1. **Decken-Artefakt.** Die kalibrierte Proba sättigt bei ~0,94 (das
   Modell sagt nie „100 % sicher"). Eine Task mit real 98 % Schreiben
   kann strukturell höchstens ~94 % geschätzt werden → eingebaute
   −4…−12 pp Unterschätzung bei saturierten Schreib-Tasks. Noahs
   gleichmäßige −12 pp sind großteils dies; P01's −21 pp nicht.
2. **Pausen-FPs sind universell** (~10 % „Schreiben" in echten Pausen),
   P05 mit +27 pp ist eine eigene Fehlerklasse — Fidgeting erzeugt
   schreibähnliche Wrist-IMU.
3. **P05's Mathe-Block ist die Engagement-Story**, kein klassischer
   Modellfehler: P05 hat dort kaum geschrieben. Genau die Lehrprobe
   fürs geplante Engagement-Modell (Prio 2).

## Offene Punkte / nächste Schritte

- Per-Task-Analyse mit dem **binären** Schätzer wiederholen — die
  oben dokumentierten Befunde stammen vom proba-Mittel und sollten
  gegengeprüft werden.
- Decken-Artefakt quantifizieren: P01's Abschreiben vom Decken-Effekt
  abgrenzen (wie viel der −21 pp ist Sättigung, wie viel echte
  Schwäche?).
- Pausen-FP-Rate pro Proband als eigenes Diagnose-Maß.
- Generalisierung auf schiefe Schreibanteile testen, sobald nicht-
  counterbalanced Daten vorliegen — die Session-MAE ist aktuell vom
  Protokoll geschützt.
- Engagement-Modell (Prio 2) baut direkt auf der Per-Task-Aggregation
  hier auf — `aggregate()` + Marker-Spans sind die Substrat-Bausteine.

## Reproduktion

```bash
python -m src.training.train_loso --save-oof   # → models/loso_oof.csv
python -m src.evaluation.regression            # → metrics + Plots
```

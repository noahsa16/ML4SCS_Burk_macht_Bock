# Design: Regression — Schreib-Prozent pro Zeitfenster

**Datum:** 2026-05-21
**Status:** Entwurf, freigegeben zur Implementierungs-Planung
**Scope:** Prio 1 der Zwischenpräsi-Roadmap. Engagement-Modell (Prio 2)
ist ausdrücklich *nicht* Teil dieses Specs.

## Ziel

Aus den bestehenden binären 1-s-Vorhersagen des LOSO-Modells eine
kontinuierliche Schätzung ableiten: *wie viel Prozent eines Zeitfensters
wurde geschrieben*. Das Modell selbst wird nicht verändert — die
Regression ist eine Auswertungs-Schicht obendrauf. Neue Bewertungs-
Metriken: MAE / RMSE / Bias in Prozentpunkten, plus ein Calibration-
Check gegen die Pen-Ground-Truth.

## Begriffsklärung: zwei Ground-Truth-Definitionen

Über ein Aggregationsfenster werden **beide** Wahrheiten reportet:

- **Geschlossene Wahrheit** — Mittel der geschlossenen Window-Labels
  (`max_gap_ms=2500`, „Schreibmodus inkl. Mikropausen"). Konsistent mit
  dem, was das Modell trainiert wurde vorherzusagen → Kern-Metrik für
  die Calibration.
- **Rohe Pen-Wahrheit** — Anteil der 50-Hz-`merged.csv`-Samples mit
  `label_writing == 1` („Tinte auf Papier"). Physikalisch ehrlichste
  Größe. Das Modell überschätzt sie systematisch, weil das Label-
  Closing Mikropausen zur Schreibzeit zählt — dieser Bias wird
  explizit reportet, nicht versteckt.

## Architektur & Datenfluss

Zwei Stufen, über ein CSV-Artefakt entkoppelt:

```
train_loso.py  (--save-oof)
  pro Fold: RF → CalibratedClassifierCV(isotonic) → OOF-Vorhersage
  └→ models/loso_oof.csv   1 Zeile pro Fenster:
        session_id, person_id, t_center_ms, label, proba_raw, proba_cal
                    ↓
src/evaluation/regression.py   (reiner Post-Processing-Schritt)
  ├─ liest loso_oof.csv
  ├─ liest data/processed/{session}_merged.csv  → rohe Pen-Wahrheit
  ├─ bildet Aggregationsfenster (60 s / 300 s / ganze Session)
  ├─ pro Fenster:  pred%         = mean(proba_cal)
  │                truth_closed% = mean(window-label)
  │                truth_pen%    = Anteil Pen-down-Samples
  └→ MAE / RMSE / Bias je Skala  +  Calibration-Plots
                    ↓
  models/regression_metrics.csv   +   reports/figures/regression_*.png
```

Stufe 2 trainiert kein Modell → Sekundenbruchteile Laufzeit, voll
testbar. Die *geschlossene* Wahrheit kommt aus der `label`-Spalte der
OOF-CSV (das ist bereits das geschlossene Window-Label); das
`merged.csv` wird nur für die *rohe* Pen-Wahrheit gelesen.

## Komponente 1 — Änderung an `src/training/train_loso.py`

- Neues CLI-Flag `--save-oof [PATH]` (Default `models/loso_oof.csv`),
  analog zu `--save-cv-csv` (`nargs="?"`, `const=...`).
- In `_fit_eval_fold`: der RF wird zusätzlich in
  `CalibratedClassifierCV(clf, method="isotonic", cv=3)` gewickelt.
  Die **rohe** Proba (`clf.predict_proba`) bleibt unverändert die
  Quelle für alle bestehenden Headline-Metriken (Accuracy, F1, ROC-AUC,
  Burst-Aggregation). Die **kalibrierte** Proba kommt additiv dazu.
- `_fit_eval_fold` gibt zusätzlich ein kleines DataFrame der OOF-Zeilen
  zurück (`session_id, person_id, t_center_ms, label, proba_raw,
  proba_cal`). `train_loso` konkateniert alle Folds und schreibt die
  CSV, wenn `--save-oof` gesetzt ist.

**Invarianz-Garantie:** ROC-AUC ist gegenüber monotoner (isotonischer)
Kalibrierung invariant; die Headline-Accuracy/F1 bleiben unberührt,
weil sie weiter auf `proba_raw` berechnet werden. Die Änderung kann
keine bestehende Metrik verschieben.

**Bekannte Vereinfachung** (als `# Why:`-Kommentar im Code): `cv=3` in
`CalibratedClassifierCV` splittet die Trainings-Folds nicht personen-
gruppiert. Bei N=10 und isotonischer Kalibrierung vertretbar; ein
gruppierter Split wäre der saubere Weg, ist hier aber Over-Engineering.

## Komponente 2 — `src/evaluation/regression.py`

Neues, fokussiertes Modul. Schnittstelle:

- `load_oof(path) -> DataFrame` — liest `loso_oof.csv`.
- `pen_truth_per_session(session_id) -> DataFrame` — liest
  `data/processed/{session}_merged.csv`, liefert `label_writing` je
  Sample mit `local_ts_ms`. **Zeit-Achsen-Konsistenz (verifiziert):**
  `windows.py` setzt `t_center_ms = mean(local_ts_ms)` aus genau
  diesem `merged.csv` — OOF-`t_center_ms` und `merged.local_ts_ms`
  liegen also auf derselben Achse, die Aggregations-Blöcke greifen
  ohne Umrechnung auf beide.
- `aggregate(oof_df, scale) -> DataFrame` — Kernfunktion. Pro
  `session_id` nicht-überlappende Blöcke der Länge `scale`,
  verankert am ersten `t_center_ms` der Session. `scale=None` ⇒ ganze
  Session als ein Block. Gibt pro Block: `session_id`, `person_id`,
  `block_start_ms`, `pred_pct`, `truth_closed_pct`, `truth_pen_pct`,
  `n_windows`.
- `regression_metrics(agg_df) -> dict` — **MAE**, **RMSE**, **Bias**
  (mittlerer vorzeichenbehafteter Fehler), jeweils gegen beide
  Wahrheiten, in Prozentpunkten.
- `evaluate(oof_path, scales=(60, 300, None)) -> dict` — orchestriert
  über alle Skalen, schreibt `models/regression_metrics.csv`.

**CLI:** `python -m src.evaluation.regression` mit `--oof PATH` und
`--scales`. Die bestehende Placeholder-`src/evaluation/evaluate.py`
bleibt unberührt — Regression ist eine eigene benannte Sache.

### Plots (`reports/figures/`)

1. `regression_calibration.png` — Reliability-Diagramm der
   kalibrierten Proba auf Sekunden-Ebene: vorhergesagte vs. empirische
   Schreibfrequenz, 10 Bins, mit y=x-Referenzlinie.
2. `regression_scatter.png` — ein Panel je Skala (60 s / 300 s /
   Session): geschätztes % vs. wahres % je Aggregationsfenster, Punkte
   um die y=x-Diagonale, MAE/Bias annotiert.

**Bias** ist die methodisch wichtigste Zahl: er zeigt das systematische
Vorzeichen des Fehlers und macht die Lücke zwischen „Schreibmodus" und
„Tinte auf Papier" erklärbar. Erwartung: Bias ≈ 0 gegen die geschlossene
Wahrheit, Bias > 0 (Überschätzung) gegen den rohen Pen-Kontakt.

## Komponente 3 — Tests

Neue Datei `tests/test_regression_eval.py` (Tier-1-Smoke, Stil von
`test_merge.py`):

- `aggregate` mit synthetischer OOF: bekannte `t_center_ms` → korrekte
  Block-Anzahl bei 60 s / 300 s / ganze Session; verankerter,
  nicht-überlappender Block-Schnitt.
- `regression_metrics`: handgebaute `agg_df` mit bekanntem Fehler →
  MAE/RMSE/Bias exakt nachgerechnet; Vorzeichen des Bias geprüft.
- `pen_truth_per_session`: synthetisches `merged.csv` → korrekter
  Pen-down-Anteil.
- Kein Test, der RF/Kalibrierung trainiert — Stufe 2 ist per Design
  trainings-frei; die OOF-CSV wird in Tests gemockt.

## Nicht im Scope (YAGNI)

- Gleitende/überlappende Aggregationsfenster (korrelierte Residuen).
- Stündliche Skala (passt nicht in eine ~15-min-Session).
- Engagement-Aufsplittung pro Task/Proband (Prio 2, separates Spec).
- Deployment-Inferenz-Pfad / Live-Eichphase.

## Erfolgskriterien

- `python -m src.training.train_loso --save-oof` erzeugt
  `models/loso_oof.csv`; Headline-Accuracy/F1/AUC im selben Lauf
  unverändert gegenüber vorher.
- `python -m src.evaluation.regression` erzeugt
  `models/regression_metrics.csv` mit MAE/RMSE/Bias je Skala gegen
  beide Wahrheiten, plus die zwei Plot-Dateien.
- `pytest tests/` grün inklusive `test_regression_eval.py`.

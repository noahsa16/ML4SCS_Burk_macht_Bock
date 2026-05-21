# Engagement — Schreibzeit-Anteil pro Aufgabe

Fortschritts- und Vorgehens-Log für Prio 2 der Zwischenpräsi-Roadmap:
pro Schreib-Aufgabe und Proband den tatsächlichen Schreibzeit-Anteil
auswerten — ein Engagement-Proxy als Auswertungs-Schicht über den
LOSO-Vorhersagen.

- Spec: `docs/specs/2026-05-21-engagement-design.md`
- Plan: `docs/plans/2026-05-21-engagement-plan.md`
- Branch: `feature/engagement`

## Ziel

Das LOSO-Modell klassifiziert pro 1-s-Fenster binär writing/idle. Die
Engagement-Auswertung ordnet diese Sekunden über die Study-Mode-Marker
den einzelnen Aufgaben zu und aggregiert pro (Proband, Aufgabe) den
Schreibzeit-Anteil. Das Modell selbst wird nicht verändert.

Motivation: P07s 0.58 Math-Accuracy ist kein Modellfehler — die Person
hat in dieser Aufgabe kaum geschrieben. Der Schreibzeit-Anteil macht
das zur Messgröße statt zur Fehlerquelle.

## Wichtige Einschränkung

Schreibzeit ≠ Aufmerksamkeit. Der Wert ist ein **Engagement-Proxy** für
Aufgabenbearbeitung, kein Aufmerksamkeits-Detektor. Eine Person kann
konzentriert denken, ohne zu schreiben.

## Architektur

`src/evaluation/engagement.py` — reines Post-Processing über
`models/loso_oof.csv` + den `data/raw/markers/`-CSVs. Die
Per-Block-Prozent-Formel wird über `block_percentages()` mit
`regression.py` geteilt.

## Ergebnisse

(wird beim ersten echten Lauf gefüllt)

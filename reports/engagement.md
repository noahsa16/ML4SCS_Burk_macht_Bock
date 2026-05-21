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

Erster Lauf 2026-05-21 über `models/loso_oof.csv` (N=10 Probanden,
29 Schreib-Task-Blöcke, 20 Pausen-Blöcke).

**Schreib-Tasks — echter Schreibzeit-Anteil je Aufgabentyp:**

| Task | `true_pct` Ø | n |
|------|-------------|---|
| `abschreiben`   | 83,3 % | 10 |
| `free_writing`  | 81,7 % | 10 |
| `math`          | **39,6 %** | 9 |

Der Math-Block hat über *alle* Probanden hinweg nur rund die Hälfte
des Schreibzeit-Anteils der anderen beiden Aufgaben. Das bestätigt den
N=10-Befund aus CLAUDE.md: P07s schwache Math-Accuracy (0.58) ist kein
Modellfehler — Mathe ist strukturell schreibarm (Denkzeit). P07-Math
konkret: `true_pct` 39,2 %, `pred_pct` 47,6 %.

**Schätzgüte:** mittlerer |`error_pp`| über die Schreib-Tasks = 6,4 pp
— das Modell schätzt den Schreibzeit-Anteil ohne Pen im Schnitt auf
~6 Prozentpunkte genau.

**Pausen-Kontrolle:** `true_pct` ist über alle 20 Pausen-Blöcke exakt
0,0 % — die Methode erfindet keinen Schreibanteil, wo keiner ist.
`pred_pct` in den Pausen Ø 6,4 %, Maximum 20,2 %; 4 von 20 Pausen
liegen über 10 % (P05 ×2, P07 Pause 4, P08 Pause 4). Diese
Pausen-FPs decken sich mit dem dokumentierten Phone-Typing-Confound
(Handy-Tippen in Idle-Blocks erzeugt schreibähnliche Wrist-IMU-Muster).

Artefakte: `models/engagement_metrics.csv`,
`reports/figures/engagement_heatmap.png`.

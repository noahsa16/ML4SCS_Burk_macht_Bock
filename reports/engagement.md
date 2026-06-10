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

Aktualisiert 2026-05-26 nach Sort-Stability-Fix + S022-Marker-
Reconstruction + OOF-Re-Generation. Aktueller Stand: N=10 Probanden,
**30 Schreib-Task-Blöcke**, 20 Pausen-Blöcke, 18.544 OOF-Fenster.

**Schreib-Tasks — echter Schreibzeit-Anteil je Aufgabentyp:**

| Task | `true_pct` Ø | `pred_pct` Ø | mittlerer \|err\| | n |
|------|------:|------:|------:|--:|
| `abschreiben`   | 87,1 % | 81,2 % | 7,4 pp | 10 |
| `free_writing`  | 82,7 % | 81,0 % | 4,9 pp | 10 |
| `math`          | **44,0 %** | 47,1 % | 7,0 pp | 10 |

Der Math-Block hat über *alle* Probanden hinweg etwa die Hälfte
des Schreibzeit-Anteils der anderen beiden Aufgaben. Das bestätigt den
N=10-Befund aus CLAUDE.md: P07s schwache Math-Accuracy (0.58) ist kein
Modellfehler — Mathe ist strukturell schreibarm (Denkzeit). P07-Math
konkret: `true_pct` 40,3 %, `pred_pct` 46,3 %. P09 (mit dem
rekonstruierten Marker) ist mit `true_pct` 55,1 % der schreibstärkste
Math-Block des Kohorts — kein Widerspruch zum *soft-writer*-Profil:
`max_gap_ms=2500` absorbiert P09s viele kurze Mikropausen, aber nicht
die langen Denkpausen anderer Probanden im Math-Block.

**Schätzgüte:** mittlerer |`error_pp`| über die Schreib-Tasks = 6,4 pp.

*Hinweis zur Verschiebung gegenüber älteren Notizen* (z. B. abschreiben
83,3 → 87,1 %): die Differenz zur Pre-2026-05-26-Auswertung ist
**nicht** der Marker-Fix, sondern Folge des Sort-Stability-Fixes vom
2026-05-25. Stable Sort auf `ts` ändert, welches Sample Fenster 0
startet → alle Fenstergrenzen verschieben sich leicht → andere
Sample-Sets pro Fenster → andere ≥60-%-Label-Verteilung. Die
Headline-LOSO-Metriken haben sich entsprechend um +0,7 pp verbessert
(siehe [`reports/sort_stability_bug.md`](./sort_stability_bug.md)),
die Engagement-`true_pct`-Werte sind eine zweite Sichtbarkeit dieses
Effekts.

> **Marker-Hiccup-Fix (2026-05-26).** S022 / P09 fehlte zunächst in
> der Math-Aggregation, weil der Server beim ersten Task einmal den
> `task_start`-Marker nicht geschrieben hat (Einzelfall, 1/30
> Sessions). Symptom: orphan `task_end` ohne `task_start` →
> `task_timeline` droppte den Block still. Beheben in zwei Schichten:
> (a) `data/raw/markers/S022_markers.csv` um den fehlenden
> `task_start` ergänzt (Zeitstempel = `study_start + pre_task_ms`),
> (b) `task_timeline` rekonstruiert orphan `task_end`-Blöcke jetzt
> automatisch (`engagement.py::RECONSTRUCT_PRE_TASK_MS`, +Test in
> `test_engagement_eval.py`).

**Schätzgüte:** mittlerer |`error_pp`| über die Schreib-Tasks = 6,4 pp
— das Modell schätzt den Schreibzeit-Anteil ohne Pen im Schnitt auf
~6 Prozentpunkte genau.

**Pausen-Kontrolle:** `true_pct` ist über alle 20 Pausen-Blöcke exakt
0,0 % — die Methode erfindet keinen Schreibanteil, wo keiner ist.
`pred_pct` in den Pausen Ø 6,4 %, Maximum 20,8 %; 4 von 20 Pausen
liegen über 10 % (P05 ×2 bei 20,8 / 15,0, P07 Pause 4 bei 18,3,
P08 Pause 4 bei 11,8). Diese Pausen-FPs decken sich mit dem
dokumentierten Phone-Typing-Confound (Handy-Tippen in Idle-Blocks
erzeugt schreibähnliche Wrist-IMU-Muster).

Artefakte: `models/engagement_metrics.csv`,
`reports/figures/engagement_heatmap.png`.

## Update 2026-06-10 — Refresh auf N=14-OOF

Mit der Headline-Promotion auf N=14 wurde `models/engagement_metrics.csv`
+ `reports/figures/engagement_heatmap.png` neu erzeugt — die Heatmap
umfasst jetzt 14 Probanden inkl. P12–P15 (Study-Mode-Marker vorhanden,
Fenster-Zuordnung über `t_center_ms` der 50hz-View-Windows). Pausen
bleiben als Kontrolle sauber (pred_pct überwiegend < 15 %, P14 Pause 2
sogar 0,0 %).

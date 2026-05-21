# Design: Engagement — Schreibzeit-Anteil pro Aufgabe

**Datum:** 2026-05-21
**Status:** Entwurf, freigegeben zur Implementierungs-Planung
**Scope:** Prio 2 der Zwischenpräsi-Roadmap. Baut auf der Regression
(Prio 1) auf, verändert sie aber nicht. CNN/LSTM (Prio 3+) sind
ausdrücklich *nicht* Teil dieses Specs.

## Ziel

Pro Schreib-Aufgabe und Proband auswerten, wie viel der Aufgabenzeit
tatsächlich geschrieben wurde. Das Modell selbst wird nicht verändert —
Engagement ist, wie die Regression, eine reine Auswertungs-Schicht über
den bestehenden 1-s-Vorhersagen.

Motivation: P07 erreicht im Math-Block nur 0.58 Accuracy. Das ist *kein*
Modellfehler — die Person hat in dieser Aufgabe kaum geschrieben (10 %
Pen-Zeit). Der Schreibzeit-Anteil pro Aufgabe macht das sichtbar und
wird so von einer Fehlerquelle zu einer Messgröße.

## Begriffsklärung: Engagement-Proxy, nicht Aufmerksamkeit

Der gemessene Wert ist der **Schreibzeit-Anteil** einer Aufgabe — der
Anteil der Aufgabenzeit, in dem die Person geschrieben hat. Er wird als
**Engagement-Proxy** geframt, ausdrücklich **nicht** als Aufmerksamkeits-
Detektor:

> Schreibzeit ≠ Aufmerksamkeit. Eine Person kann konzentriert denken,
> lesen oder rechnen, ohne zu schreiben. Ein niedriger Schreibzeit-
> Anteil bedeutet nicht „nicht engagiert". Der Wert ist ein
> beobachtbarer Proxy für Aufgabenbearbeitung, kein psychologischer
> Messwert.

Diese Einschränkung gehört in jede nach außen sichtbare Darstellung
(Bericht, Präsentation).

## Begriffsklärung: zwei Zahlen pro Aufgabe

Pro Task-Block werden **beide** Werte reportet:

- **`true_pct`** — Mittel der geschlossenen Window-Labels
  (`label` aus `loso_oof.csv`, `max_gap_ms=2500`). Das ist der echte
  Schreibzeit-Anteil in der Definition, auf die das Modell trainiert
  wurde.
- **`pred_pct`** — binärer Schätzer `mean(proba_cal ≥ 0.5) · 100`,
  dieselbe Größe wie `pred_pct` in der Regression. Das ist der Anteil,
  den das Modell *ohne Pen* selbst schätzen würde.

Die Nähe beider Werte validiert, dass der Engagement-Proxy auch im
Deployment (kein Pen verfügbar) funktioniert. Die rohe Pen-Wahrheit
(`merged.csv`, „Tinte auf Papier") wird hier **nicht** zusätzlich
ausgewiesen — sie lässt sich später analog zur Regression billig
nachrüsten, ist für die Engagement-Aussage aber nicht nötig (YAGNI).

## Architektur — Auswertungs-Schicht über zwei CSVs

Reines Post-Processing, kein Modell-Training. Entkoppelt über zwei
bereits existierende Artefakte:

```
models/loso_oof.csv              data/raw/markers/{session}_markers.csv
  session_id, person_id,           timestamp_ms, event, task_id,
  t_center_ms, label, proba_raw,   task_name, task_index,
  proba_cal                        task_category, protocol_id
        │                                  │
        └────────── src/evaluation/engagement.py ──────────┘
                          │
   1. Marker-Timeline: task_start ↔ task_end je Session paaren
      → Blöcke (task_index, task_id, task_name, task_category,
                start_ms, end_ms)
   2. jedes OOF-Fenster per t_center_ms ∈ [start_ms, end_ms)
      einem Task-Block zuordnen
   3. aggregieren pro (Session, task_index):
        true_pct = mean(label) · 100
        pred_pct = mean(proba_cal ≥ 0.5) · 100
        error_pp = pred_pct − true_pct
                          │
   models/engagement_metrics.csv      (1 Zeile pro Task-Block)
   reports/figures/engagement_heatmap.png
```

### Zeitachsen

`timestamp_ms` der Marker-CSV und `t_center_ms` der OOF-CSV liegen auf
**derselben** Unix-ms-Wall-Clock — der Server stempelt sowohl die
Marker als auch (über `local_ts_ms` == `server_received_ms` der Watch-
CSV) die Sample-Zeitstempel. Verifiziert an S019: Marker `study_start`
und erstes Watch-Sample liegen 140 ms auseinander. Es ist **keine**
Uhren-Konversion nötig; das Stroke-Variance-Alignment (`pen_match.py`)
betrifft nur Pen↔Watch und ist hier irrelevant.

## Komponenten

`src/evaluation/engagement.py`:

| Funktion | Zweck | Abhängigkeit |
|----------|-------|--------------|
| `load_oof(path)` | OOF-CSV laden | wiederverwendet aus `regression.py` (Import) |
| `task_timeline(session_id)` | Marker-CSV lesen, `task_start`↔`task_end` je `task_index` paaren | `data/raw/markers/` |
| `assign_tasks(oof_session, timeline)` | jedem OOF-Fenster per `t_center_ms` einen Task-Block zuordnen | — |
| `engagement_per_task(oof_df, timeline_loader)` | 1 Zeile pro `(Session, task_index)` aggregieren | obige |
| `plot_engagement_heatmap(eng_df, out_path)` | Proband × Task-Grid + Pausen-Streifen | matplotlib |
| `evaluate(...)` | Orchestrator: CSV + Plot schreiben, Diagnose loggen | alle obigen |

`task_timeline` und `assign_tasks` sind der wiederverwendbare,
deployment-fähige Kern (Marker → Task → zugeordnete Fenster). `evaluate`
ist die Präsi-Schicht obendrauf.

### Marker-Timeline

Ein Task-Block ist ein `task_start`-Event gepaart mit dem `task_end`
gleichen `task_index`. Pausen sind gewöhnliche Blöcke
(`task_id='pause'`, `task_category='idle'`) — es gibt **keine**
separaten Pause-Events. Eindeutiger Schlüssel pro Session ist
`task_index` (`task_id='pause'` wiederholt sich, z. B. Index 2 und 4).
Die am Session-Ende mehrfach auftretenden `abort`/`study_end`-Zeilen
werden ignoriert; nur `task_start`/`task_end` werden gelesen.

## Output

**`models/engagement_metrics.csv`** — eine Zeile pro Task-Block:

```
session_id, person_id, task_index, task_id, task_name, task_category,
n_windows, true_pct, pred_pct, error_pp
```

Schreib-Tasks und Pausen stehen beide in der Datei, unterscheidbar über
`task_category`. Die Pausen (`idle`) sind der Kontroll-Datensatz: sie
sollten durchgehend niedrigen `true_pct` zeigen — Beleg, dass die
Methode nicht überall hohe Werte produziert.

**`reports/figures/engagement_heatmap.png`** — Grid: Zeilen =
Probanden, Spalten = die 3 Schreib-Tasks (`abschreiben`, `math`,
`free_writing`). Zellfarbe = `true_pct`, Zell-Beschriftung zeigt beide
Zahlen (`true / pred`). Darunter ein schmaler Pausen-Streifen als
Kontrolle.

**`reports/engagement.md`** — Fortschritts-/Vorgehens-Log, parallel zu
`reports/regression.md`.

## Edge Cases

- **Session im OOF, aber keine Marker-CSV** (z. B. `free`-Modus) →
  Session überspringen, Warnung loggen, kein Crash.
- **`abort`-Session**: letzter `task_start` ohne passendes `task_end`
  → Block verwerfen, loggen.
- **Fenster in Übergängen** (Vor-Task-Countdown, zwischen Blöcken) →
  `task_index = NaN`, nicht ins Grid, aber pro Session als
  „nicht zugeordnet" gezählt und geloggt (Sanity-Check: Summe
  zugeordnet + nicht zugeordnet = Session-Fensterzahl).
- **Doppelte `abort`/`study_end`-Zeilen** → ignoriert.

## Nicht im Scope (YAGNI)

- Rohe Pen-Wahrheit als dritte Spalte (später analog zur Regression
  nachrüstbar).
- Engagement aus Roh-Signalen statt aus OOF-Vorhersagen.
- Per-Task-Threshold-Tuning oder Modell-Änderungen.
- Aufmerksamkeits-/ADHS-Inferenz — bleibt ehrlich ein Anschluss-
  Ausblick, keine gegenwärtige Behauptung.

## Erfolgskriterien

- `python -m src.evaluation.engagement` erzeugt
  `models/engagement_metrics.csv` mit dem oben definierten Schema
  (eine Zeile pro Task-Block, Schreib-Tasks und Pausen) plus
  `reports/figures/engagement_heatmap.png`.
- Die Pausen-Zeilen (`task_category='idle'`) zeigen sichtbar
  niedrigeren `true_pct` als die Schreib-Tasks.
- Der P07-Math-Block erscheint als Zelle mit niedrigem `true_pct` —
  die Auswertung reproduziert den bekannten Befund.
- `pytest tests/` grün inklusive `test_engagement_eval.py`.

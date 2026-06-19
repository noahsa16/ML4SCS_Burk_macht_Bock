# Deep-Sequenz-Modelle im Training-Cockpit

**Datum:** 2026-06-19
**Status:** Design (genehmigt → Plan)
**Kontext:** Folgeschritt zum Web-Training-Cockpit
([2026-06-16-web-training-cockpit-design.md](2026-06-16-web-training-cockpit-design.md)).
Die klassischen Modelle (RF/ExtraTrees/HistGB/LogReg/SVM-RBF/MLP) sind seit
dem `--model`-Ausbau in `train_loso` verdrahtet; dieses Design bringt die
**Deep-Sequenz-Modelle** (`cnn`, `lstm`, `gru`, `tcn`) ins Cockpit.

## Ziel

Ein Nutzer wählt im Training-Tab ein Deep-Modell, startet einen LOSO-Lauf und
sieht denselben Live-Fortschritt (Folds, Konfusionsmatrix, Konvergenz,
HW-Sampling) wie bei einem RF-Lauf. Der fertige Lauf landet in der
Run-Historie mit Per-Fold-Tabelle, ROC-Kurve und Fehler-nach-Task.

**Nicht-Ziel:** Deep-Modelle in die Live-Inferenz bringen. Deep-Läufe sind
**reine LOSO-Evaluationen** — `Promote` und `Sandbox` (beide laden ein
sklearn-Joblib in den Live-Tracker) bleiben für Deep-Runs gesperrt. Auch
harnet/Foundation bleibt vorerst gated (eigener torch.hub-Download, kein
Demo-Showpiece).

## Architektur-Entscheidung

Der bestehende Deep-Runner (`src/training/deep/train_loso.py` +
`__main__.py`) wird **in-place** mit demselben Event-/Artefakt-Protokoll
instrumentiert, das `train_loso` schon nutzt. Ein Runner pro Modellfamilie,
keine Adapter-Schicht. Verworfen: ein Shim-Runner (reine Indirektion) und
volle Promote/Sandbox-Parität (würde den Live-Inferenz-Vertrag auf torch
erweitern — bewusst out of scope).

## Komponenten

### 1 · Runner-Instrumentierung (`src/training/deep/`)

`train_deep_loso(...)` bekommt zwei neue optionale Parameter `on_event=None`
und `run_dir=None` (Signatur-Muster identisch zu `train_loso`). Ohne sie
bleibt das Verhalten unverändert (Print + `deep_loso_{pool}.csv`).

**Emittierte Events** (spiegelbildlich zum RF-Runner, gleiche Feldnamen, vom
`TrainingRun._handle_event` schon konsumiert):

| Event | Felder | Zeitpunkt |
|---|---|---|
| `run_start` | `model, by="person", pool, n_folds` | nach dem Daten-Laden, sobald `person_ids` feststeht |
| `fold_start` | `idx, person` | vor jedem Fold |
| `fold_end` | `idx, person, n, acc, auc, f1, burst:{scale→acc}, confusion:{tn,fp,fn,tp}` | nach jedem Fold |
| `run_end` | `partial, n_done, mean_acc, std_acc, auc, f1, burst:{scale→mean_acc}, out_dir` | am Ende |
| `error` | `message` | im Except-Pfad |

- `confusion` wird neu aus `(pred = proba>=0.5, test_y)` berechnet
  (`sklearn.metrics.confusion_matrix`), analog zum RF-Runner.
- `burst` nutzt die schon vorhandenen `acc_5s/auc_5s/...`-Spalten bzw.
  `fold_metrics`-Ausgabe — feste Skalen 5/10/30 s (keine `--burst-scales`).
- `emit = on_event or (lambda *_: None)` als no-op-Fallback, damit der
  CLI-Pfad ohne Callback nicht verzweigen muss.

**Graceful Stop:** Die Per-Fold-Schleife in `train_deep_loso` wird in
`try/except KeyboardInterrupt` gewickelt. Bei SIGINT (vom Stop-Knopf via
`TrainingRun.stop`) bricht die Schleife ab, setzt `partial=True` und
finalisiert die fertigen Folds (Schreiben von `cv.csv`/`oof.csv` + `run_end`)
— wie der RF-Runner. Der torch-Trainingsloop selbst muss dafür nichts
zusätzlich tun; das `KeyboardInterrupt` propagiert aus `train_one_model`.

**CLI** (`__main__.py`): zwei neue Flags `--emit-json` (→
`events.json_line_emitter()`) und `--run-dir PATH`. Ohne sie ist das CLI
bit-identisch. Reihenfolge der Argument-Auswertung wie bei `train_loso`.

### 2 · Run-Artefakte + Promote-Gate

In `run_dir` schreibt ein Deep-Lauf:

- **`cv.csv`** — die per-Fold-Tabelle, die `train_deep_loso` schon baut
  (Spalten u. a. `held_out`, `accuracy`, `roc_auc`, `f1_writing`,
  `acc_5s`…). Damit funktionieren `_attach_cv_summary` (Run-Historie
  `mean_acc`/`mean_auc`/`n_folds`) und der Per-Fold-Block im Drawer
  unverändert.
- **`oof.csv`** — gesammelte OOF-Vorhersagen über alle Folds mit den Spalten
  `label, proba_raw, session_id, person_id, t_center_ms`. Quelle: pro Fold
  `proba`, `test_y` und das schon gebaute `test_df` (hat `session_id`,
  `t_center_ms`); `person_id` = `test_p`. Damit funktionieren ROC-Kurve
  (`run_detail`) und Fehler-nach-Task (`run_tasks`) im Drawer.
- **kein `model.joblib`** — Deep-Läufe sind eval-only. `run_detail` liefert
  dann `feature_groups == []` (kein `feature_importances_`), was die UI
  bereits sauber behandelt (kein Importance-Card).

**Promote-Gate** (`routes/training.py::promote`): gibt **HTTP 400** zurück,
wenn `models/runs/{id}/model.joblib` fehlt — Begründung „eval-only run, nicht
promotebar". Verhindert das halb-promotete `loso_cv.csv`/`loso_oof.csv` ohne
passendes `rf_all.joblib`. `Sandbox` ist über die fehlende `model.joblib`
schon natürlich gegated (bestehender 404).

### 3 · Cockpit-Verdrahtung (`src/server/training.py` + `registry.py`)

`_build_cmd` verzweigt auf `registry.get(model).runner`:

- `src.training.train_loso` (klassisch): unverändert.
- `src.training.deep`: baut
  `[python, -u, -m, src.training.deep, --model {m}, --pool {pool},
  --emit-json, --run-dir {d}]`, plus `--max-gap-ms {v}` (falls gesetzt) und
  `--zscore` (falls an). Deep ignoriert `by`, `burst_scales`, `window_sec`
  bewusst (immer person-LOSO, festes 1-s-Input, feste 5/10/30-Burst).

`registry.py`: `cnn`/`lstm`/`gru` auf `enabled=True`, neuer `tcn`-Spec
(`family="deep"`, `runner="src.training.deep"`, `enabled=True`,
`supports_feature_importance=False`). harnet-Specs bleiben `enabled=False`.

### 4 · Frontend „Deep-Modus" (`static/js/pages/training.js` + `training.css`)

`_loadModels` legt eine `_modelFamily`-Map (`id → family`) an und setzt
`data-family` auf jeder Option. Bei Modell-Wechsel:

- **Dunkler Look:** `root.classList.toggle('trn-deep', family === 'deep')`.
  `training.css` definiert unter `.trn-deep` ein dunkleres Cockpit-Theme
  (das visuelle „deep"-Signal). Reine CSS-Override, keine Layout-Änderung.
- **Z-Score auto-aus:** Beim Wechsel auf ein Deep-Modell wird
  `#trn-zscore` auf `unchecked` gesetzt (Deep-Konvention: kein Per-Session-
  Z-Score, BatchNorm übernimmt). Manuell wieder einschaltbar.
- **Nicht zutreffende Regler dimmen+deaktivieren:** Fenster-Select,
  Burst-Chips und by-Achse werden im Deep-Modus `disabled` + visuell gedimmt
  (`.trn-deep`-Styling), damit keine stille Wirkungslosigkeit entsteht. Pool,
  Gap und Z-Score bleiben aktiv.

**Promote/Sandbox ausgrauen:**
- Live-Done-State (`onStatus`): wenn `_modelFamily[t.model] === 'deep'`,
  bleiben `#trn-promote` und `#trn-sandbox` versteckt/disabled.
- Run-Historie (`_loadRuns`) und Run-Drawer (`_openRunDrawer`): die
  „als Headline"-Buttons werden disabled (gedimmt, Titel „eval-only"),
  wenn `_modelFamily[r.model] === 'deep'`.

### 5 · Tests

- `tests/test_training_registry.py` — bestehender Test angepasst: alle vier
  Deep-Modelle (`cnn`/`lstm`/`gru`/`tcn`) `enabled=True`, harnet-Varianten
  `enabled=False`.
- `tests/test_deep.py` (oder neu) — `train_deep_loso` mit monkeypatched
  `_load_all_sessions` (winzige Arrays für ≥ 3 Personen) und `on_event` +
  `run_dir`: assert es emittiert `run_start`/`fold_end`/`run_end`, der
  `run_start.model` trägt das gewählte Modell, und es schreibt `cv.csv` +
  `oof.csv`, **keine** `model.joblib`.
- `_build_cmd`-Branch-Test (`tests/test_training_endpoints.py` oder
  `test_training.py`): Deep-Modell → Kommando enthält `src.training.deep`,
  `--emit-json`, `--run-dir`, `--model {m}` und **nicht** `--by`/
  `--burst-scales`.
- `tests/test_training_endpoints.py` — Deep-Modell passiert das enabled-Gate
  (`/training/start` 200 mit gemocktem `run.start`); `POST
  /runs/{id}/promote` auf ein Run-Verzeichnis ohne `model.joblib` → 400.

## Datenfluss (Deep-Lauf)

```
UI: Modell=cnn, Pool=legacy, Z-Score=aus (auto), Gap=2500
  → POST /training/start
  → registry.validate + enabled-Gate (passt)
  → TrainingRun.start → _build_cmd (Deep-Branch)
  → subprocess: python -u -m src.training.deep --model cnn --pool legacy
                --emit-json --run-dir models/runs/{id} --max-gap-ms 2500
  → train_deep_loso(on_event=json_line_emitter, run_dir=…)
       emit run_start{n_folds}
       für jede Person: fold_start → train torch → fold_end{acc,auc,confusion}
       schreibt cv.csv + oof.csv (kein model.joblib)
       emit run_end{mean_acc, burst, …}
  → stdout-Reader (TrainingRun._read) → _handle_event → snapshot
  → WS-Tick `training`-Block → training.js rendert Live-Cockpit
  → Done: Promote/Sandbox ausgegraut (Deep), Drawer mit cv/ROC/Tasks
```

## Risiken / offene Punkte

- **Subprozess-Startzeit:** `import torch` ist schwer; der Deep-Subprozess
  braucht ein paar Sekunden bis zum ersten Event. Kein Funktionsproblem (der
  RF-Pfad hat dieselbe Architektur), nur gefühlte Latenz vor `run_start`.
- **Laufzeit:** Deep-LOSO dauert ~Minuten (CPU/MPS). Das Cockpit ist dafür
  gebaut (HW-Sampling, Stop-Knopf). Kein Live-Demo-Speed wie RF.
- **`watch_profile`-Spalte:** Der Deep-Runner braucht sie in `sessions.csv`
  (Pool-Plan). Im laufenden Server vorhanden (Quality-Refresh schreibt sie);
  in Tests gemockt.

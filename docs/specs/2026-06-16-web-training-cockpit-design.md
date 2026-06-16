# Web-Training-Cockpit — Design-Spec

**Datum:** 2026-06-16
**Status:** Entwurf zur Review
**Autoren:** Noah Samel (+ Claude, Brainstorming)

## Überblick

Ein neuer **„Training"-Tab** im Dashboard, von dem aus sich Modell-Läufe
**starten** und **live verfolgen** lassen, mit einer **richtig schönen,
demo-tauglichen Visualisierung** im bestehenden Dashboard-Look.

**Primärer Zweck: Demo-Showpiece** für die Endpräsentation — beeindruckende
Live-Visualisierung steht über Robustheit. Schnelle Läufe (RF-LOSO, ~1–3 min)
sind live im Vortrag zuschaubar; lange Läufe (Deep/harnet, 10+ min) laufen im
Hintergrund weiter und zeigen trotzdem Fold-Fortschritt.

Das Feature ist **rein additiv** — die bestehende ML-CLI
(`python -m src.training.train_loso` etc.) bleibt unverändert das maßgebliche
Werkzeug; das Cockpit ist eine zweite Bedienoberfläche darüber.

## Ziele / Nicht-Ziele

**Ziele**
- Modell-Lauf von der Website starten (gruppiertes Modell-Menü, Parameter).
- Live-Fortschritt streamen (Fold-für-Fold, für Deep auch Epoch-Loss).
- Drei Zustände: **idle** (Config) → **läuft** (Cockpit) → **fertig** (Analyse).
- Tiefes Drill-in pro KPI-/Stat-Card (Detail-Drawer).
- Nicht-destruktive Run-Historie; kanonische Artefakte nur per expliziter Promotion.
- Robust ggü. Study-Designs (v1/v2/künftig) und Session-Arten (legacy/modern).
- Light- **und** Dark-Mode, volles Branding.
- Genau **ein Lauf gleichzeitig**.

**Nicht-Ziele**
- Kein Multi-User / keine Auth (lokales Demo-Tool).
- Keine verteilte/Cluster-Ausführung.
- Kein Persistieren laufender Jobs über Server-Restart (Subprozess ist Kind des Servers).
- Kein Hyperparameter-Tuning-Framework (siehe Roadmap-Begründung).

## Architektur

### Datenfluss

```
[Training-Tab UI]  ──POST /training/start──▶  [TrainingRun-State-Machine]
       ▲                                              │  (ein Lauf gleichzeitig)
       │ WS: training-Events                          ▼
       │                              asyncio.create_subprocess_exec
       │                              python -m src.training.<runner>
       │                                --emit-json --run-dir models/runs/{id}
       │                                              │
       │   stdout (JSON-Lines)                        ▼
[stdout-Reader] ◀──────────  on_event(dict) → json.dumps → stdout
       │  parse JSON → update state → _broadcast({type:"training", ...})
       ▼
   models/runs/{run_id}/  (cv.csv, oof.csv, model.joblib, config.json, events.jsonl)
       │
   POST /training/runs/{id}/promote  ──▶  models/{rf_all.joblib, loso_cv.csv, loso_oof.csv}
```

### Fortschritts-Mechanismus (Ansatz B — beschlossen)

Die LOSO-Runner emittieren **strukturierte Events** statt dass der Server
menschenlesbaren stdout regex-parst.

- **`src/training/events.py`** (neu): Event-Schema + Emitter.
  - `on_event` ist ein `Callable[[dict], None] | None`.
  - `json_line_emitter(event)` schreibt `json.dumps(event)` + `\n` auf stdout
    und flusht (Subprozess läuft mit `-u`, analog `pen_proc`).
  - Default in allen Runnern: `on_event=None` → **bisheriges Print-Verhalten
    unverändert** (CLI-Nutzung bit-identisch, keine Regression).
- **Event-Typen** (eine JSON-Zeile pro Event):
  | type | Felder |
  |---|---|
  | `run_start` | `model, pool, axis, n_folds, config{}` |
  | `fold_start` | `idx, person, n` |
  | `epoch` *(nur Deep)* | `fold_idx, epoch, train_loss, val_acc` |
  | `fold_end` | `idx, person, acc, auc, f1, burst{5s,10s,30s}` |
  | `run_end` | `mean_acc, std_acc, auc, f1, burst{}, out_dir` |
  | `error` | `message` |
- **Eingriff in bestehende Runner** (minimal, ein optionaler Parameter, der
  vorhandene Print-Stellen spiegelt):
  - `src/training/train_loso.py`
  - `src/training/deep/train_loso.py`
  - `src/training/deep/harnet_frozen.py`, `harnet_finetune.py`
  - je ein `--emit-json`-CLI-Flag → setzt `on_event=json_line_emitter`.
  - je ein `--run-dir PATH`-Flag → schreibt Artefakte dorthin statt in die
    kanonischen Pfade (Default bleibt kanonisch für CLI-Kompatibilität).

*Verworfen:* stdout-Regex (brüchig, kein Per-Epoch-Loss → keine Live-Sparkline),
Progress-Datei (mehr bewegliche Teile, für „ein Lauf gleichzeitig" unnötig).

### Modell-agnostische Job-Registry

- **`src/training/registry.py`** (neu): eine Liste von Modell-Specs, *single
  source of truth* für Menü, Validität und Tooltips.
  ```python
  ModelSpec(
    id, label, family,            # "classical" | "deep" | "foundation"
    speed,                        # "fast" (live) | "slow" (background)
    valid_pools,                  # {"legacy","modern", ...}
    supports_feature_importance,  # nur Tree-Modelle
    supports_zscore, causal,      # causal=False → nicht live-tauglich (BiLSTM!)
    runner, runner_args,          # wie der Subprozess gestartet wird
    description,                  # Tooltip-Text
  )
  ```
- Neue Modelle (TCN, CNN+BiLSTM, Focal-Loss-Variante) docken hier an, **ohne
  den Launcher zu ändern** — sie tauchen automatisch im Menü auf.

### Server

- **`src/server/training.py`** (neu): `TrainingRun`-State-Machine
  (`idle → running → done | error`), Subprozess-Lifecycle **1:1 nach dem
  `pen_proc.py`-Muster** (`create_subprocess_exec`, stdout-Reader-Task,
  SIGINT→Timeout→SIGKILL), `start_run` mit **Guard „ein Lauf gleichzeitig"**.
  Der Reader parst JSON-Lines → aktualisiert State → `_broadcast`.
- **`src/server/routes/training.py`** (neu, ein `APIRouter`):
  - `GET /training/models` — Registry + pro Modell die Pool-Validität/Flags.
  - `POST /training/start {model, pool, axis, params}` — startet Lauf;
    **409** wenn bereits einer läuft; **400** bei ungültiger Modell×Pool-Kombi.
  - `POST /training/stop` — bricht den laufenden Lauf ab.
  - `GET /training/runs` — Run-Historie (scannt `models/runs/`).
  - `GET /training/runs/{id}` — Detail eines Laufs (cv/oof/config).
  - `POST /training/runs/{id}/promote` — setzt Lauf als Headline (kopiert in
    die kanonischen Pfade). **Einziger** Weg, kanonische Artefakte zu ändern.
  - `GET /training/runs/{id}/compare?other={id}` — zwei Läufe + gepaarter
    Wilcoxon (`src/evaluation/significance.py`).
- **WS:** das bestehende `_status_loop`/`_broadcast` trägt zusätzlich
  `{type:"training", phase, model, pool, fold, n, folds[], mean_acc, ...}`.

### Run-Output (nicht-destruktiv)

- Jeder Lauf: **`models/runs/{run_id}/`** mit `cv.csv`, `oof.csv`,
  `model.joblib`, `config.json`, `events.jsonl`.
  `run_id = {YYYY-MM-DD_HH-MM}_{model}_{pool}`.
- Die kanonischen Artefakte (`rf_all.joblib`, `loso_cv.csv`, `loso_oof.csv`)
  werden **nur** durch `promote` überschrieben — Läufe können sich nie
  gegenseitig (oder die Headline) versehentlich plätten.

### Frontend

- Neues Page-Modul **`static/js/pages/training.js`** mit dem etablierten
  Vier-Funktionen-Contract (`mount/onStatus/onShow/onHide`).
- View-Partial **`static/views/training.html`**, Styles
  **`static/css/training.css`**.
- **Ästhetik:** vollflächig-immersiv (full-bleed) — translucente Topbar,
  geschichtete warme Radial-Gradienten, Glas-Cards mit Blur, glühender
  Live-Puls, große Hero-Zahlen, 15er-Per-Person-Grid in einer Reihe, große
  Hintergrund-Slash-Glyphe. **Identische Struktur in Light + Dark.**
- Neuer **„Training"-Tab** in der Topbar (`dashboard.html`), zwischen Sessions
  und Settings; Routing/Indicator in `router.js`.
- **Drei Zustände** im selben Page-Modul umgeschaltet:
  - *idle:* Config-Panel + „Letzter Lauf" + großer Start-CTA.
  - *läuft:* Cockpit — Hero-KPIs (zählen hoch), Per-Person-Grid (poppt rein),
    Konvergenz-Kurve (Mean ± σ), Live-Rail (aktueller Fold + Loss/Tree-Build),
    Log-Ticker, Stop. **Bewusst keine Stats** (wären halbleer).
  - *fertig:* Verdict („vs. Headline"), volles Per-Person-Grid, die sechs
    Analyse-Module, CTAs „Nochmal" / „Als Headline speichern".
- **Drill-in-Drawer:** jede KPI-/Stat-/Person-Card ist anklickbar → rechter
  Slide-over mit Tiefendaten (s. *Visuals*).
- **Hover-Tooltips:** jede Config-Control trägt ein „?" → Tooltip mit Funktion
  + Fallstrick (Text aus der Registry/Param-Metadaten).
- **Inline-`onclick`-Handler:** falls verwendet, im
  `Object.assign(window, …)`-Block in `dashboard.js` registrieren (Projekt-Konvention).

## Visuals

**Cockpit (läuft + fertig)**
- Hero-KPIs: accuracy (±σ), ROC-AUC, F1, Fold-Counter.
- Per-Person-Grid: 1 Kachel/Person, Farbe nach acc (grün stark / gelb schwach /
  Akzent = läuft / gestrichelt = offen).
- Konvergenz-Kurve: Mean ± σ über Folds.
- Live-Rail: aktueller Fold, Epoch-Loss (Deep) / Tree-Build (RF), „vs Headline".
- Log-Ticker mit `/`-Branding-Präfix.

**Analyse-Module (nur im *fertig*-Zustand) — je mit Drill-in:**
1. **Confusion-Matrix** → Drawer: volle Raten + Precision/Recall (optional per Task).
2. **ROC-Kurve** → Drawer: pooled + per Fold.
3. **Feature-Gruppen-Importance** (6 Gruppen, nur Tree-Modelle) → Drawer:
   die 88/92 Einzel-Features. Bei Nicht-Tree-Modellen ausgegraut.
4. **Burst-Skalen-Kurve** (acc/AUC @1/5/10/30 s) → Drawer: volle Tabelle.
5. **Modell-Leaderboard** (alle Läufe aus `models/runs/`) → Drawer:
   Vergleichstabelle + Wilcoxon-Signifikanz.
6. **Fehler nach Task-Kategorie** (marker-getrieben) → Drawer: FP/FN-Cluster
   aller Personen.

**Per-Person-Drill-in (Klick auf Kachel):** Drawer mit KPIs, **Genauigkeit pro
Task aus den Markern**, Predicted-vs-True-Zeitleiste (FP/FN-Marker), kurze
Failure-Mode-Notiz.

## Modelle

**Bestehend (sofort lauffähig)**
- *Klassisch (88/92 Feat.):* RandomForest, ExtraTrees, HistGradBoost,
  LogReg (⚡) · MLP, SVM-RBF (🕐) — via `compare_models`-Codepfad.
- *Deep-Sequenz:* CNN, LSTM, GRU (🕐), Input-Fenster 1 s/5 s.
- *Foundation:* harnet5/harnet10 je frozen (🕐) / finetune (🕐🕐).

**Neu zu implementieren (je eigener ML-Task im Plan)**
- **TCN** (dilated, **kausal**, langer Kontext) — evidenz-aligned (Window-Sweep/
  harnet10: längerer Kontext hilft); live- + watch-tauglich.
- **1D-CNN + BiLSTM** — HAR-Standard. **Caveat:** BiLSTM ist **nicht-kausal**
  → taugt für die LOSO-Headline, **nicht** für die Live-Inferenz
  (`causal=False` in der Registry + UI-Hinweis).
- **Focal-Loss-Option** für die Deep-Modelle (zielt auf Hard Negatives /
  Phone-Typing-Confound); RF hat keinen Loss → `class_weight=balanced` bleibt.

**Modell×Pool-Validität** wird in der Registry geführt und am API + UI
durchgesetzt (Deep-Modelle mischen keine Sample-Raten; harnet ohne
Per-Session-Z-Score; Feature-Importance nur Tree-Modelle; legacy 88 vs.
modern 92 Features).

## Robustheit (explizite Anforderungen)

- **Study-Design-robust:** Task-Namen im Drawer + „Fehler nach Task" kommen
  **dynamisch aus den Markern** der jeweiligen Session (v1/v2/künftig), nichts
  hartkodiert. Sessions ohne Marker (free/legacy ohne Study-Mode) → Task-Module
  werden **ausgeblendet** statt geraten.
- **Session-Arten/Pools:** Pool-Filter respektiert verdict-Gate + `watch_profile`
  wie der bestehende LOSO; gemischte Pools werden wie `--pool auto` behandelt
  (Gravity-Spalten global gedroppt).
- **Nicht-destruktiv:** Läufe in `models/runs/{id}/`; Headline nur per Promotion.
- **Tooltips überall:** keine Fehleinstellung ohne Erklärung.
- **Concurrency:** genau ein Lauf; `start` → 409 wenn belegt.
- **Theme:** Light **und** Dark, **beide premium-immersiv** umgesetzt
  (vollflächige warme Gradient-Washes statt flacher Flächen, Glas-Cards mit
  weichen/glühenden Schatten, Hintergrund-Slash-Glyphe, gleiche Vollflächen-
  Struktur in beiden) — ausschließlich über die `--token`-Variablen, derselbe
  Toggle wie der Rest des Dashboards. Dark ist der Hero-Look, Light gleichwertig
  poliert (kein „braves" Light).
- **Branding:** Wordmark „Burk macht Bock /", orange Slash-Motiv (auch als
  `/`-Präfix), große Hintergrund-Slash-Glyphe (Training-eigener Anker), IBM Plex,
  Orange als Primär-/Live-Akzent (on-brand statt Fremdfarbe).

## Fehlerbehandlung

- Subprozess-Crash → `error`-Event → State `error`, in der UI sichtbar (mit
  letzter stderr/Log-Zeile).
- Server-Restart während Lauf → Kind stirbt → State resettet auf `idle`
  (keine Persistenz, bewusst).
- harnet torch.hub-Download-Fehler → `error` mit Hinweis (CA-Bundle/Netz).
- Ungültige Modell×Pool-Kombi → am API abgelehnt + im UI deaktiviert.
- `max_gap_ms` ändern triggert Feature-Rebuild → UI-Warnung „langsamer".

## Tests (analog der bestehenden Tier-1-Smokes)

- `test_training_registry.py` — Specs vollständig, Modell×Pool-Regeln,
  `causal`-Flags (BiLSTM=False, TCN=True).
- `test_training_events.py` — Event-Schema, `json_line_emitter` Round-Trip,
  Parser robust gegen Nicht-JSON-Zeilen (gemischter stdout).
- `test_training_state.py` — State-Machine-Übergänge, „ein Lauf"-Guard.
- `test_training_endpoints.py` — start/stop/runs/promote/compare; 409 bei belegt;
  Promotion ist der einzige Schreibpfad auf kanonische Artefakte.
- `test_dashboard_static.py` — `training.js` / `training.html` / `training.css`
  zur Parametrize-Liste hinzufügen (404-Falle).
- Runner-Integration: je ein Smoke, dass `--emit-json` ein valides
  `run_start`/`fold_end`/`run_end` produziert (kleiner synthetischer Datensatz
  oder Mock), und dass **ohne** `--emit-json` der Print-Output unverändert ist.

## Roadmap / bewusst ausgelassen

- **Siamese / Few-Shot (für später gemerkt):** zielt auf P09-Soft-Writer als
  *Personalisierungs*-Problem (within-subject ≫ cross-subject; `rf_noah`
  existiert). 10-s-Kalibrierung beim Start trifft die Decke konzeptionell am
  besten — aber großer Bau + anderer Produkt-Pfad → nach der Demo.
- **Verworfen mit Begründung:** PatchTST/Transformer (datenhungrig, Overfit bei
  N=15; harnet-Foundation-Model hat die Decke nicht durchbrochen), Optuna
  (Cross-Fold-HPO ohne nested CV = Leakage; Gewinne unter Fold-σ = Rauschen),
  SMOTE (physikalisch unplausible IMU-Fenster; `balanced` adressiert Imbalance
  bereits).
- **Kontext:** Die Leistungsdecke ist modellunabhängig vermessen
  (frozen harnet scheitert an denselben Folds wie RF, per-Fold-AUC r≈0.92;
  CNN Train/Test-Gap 0.019 = data-limited). Neue Architekturen werden die
  Headline voraussichtlich nicht heben — Wert liegt in Demo/Lehre und in den
  evidenz-alignten Ideen (TCN, Siamese), nicht in roher Kapazität.

## Offene Punkte für den Plan

- Genaue Verdrahtung des `compare_models`-Pfads für die klassischen
  Nicht-RF-Modelle (eigener Runner vs. Parameter an `train_loso`).
- Ob das Modell-Leaderboard live mitwächst oder erst im *fertig*-Zustand lädt.
- Granularität der Deep-`epoch`-Events (jede Epoche vs. gedrosselt).

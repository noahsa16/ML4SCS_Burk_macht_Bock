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
  | `fold_end` | `idx, person, acc, auc, f1, burst{5s,10s,30s}, confusion{tn,fp,fn,tp}` |
  | `run_end` | `mean_acc, std_acc, auc, f1, burst{}, out_dir, partial, n_done` |
  | `error` | `message` |

  `confusion` speist die **Live-Confusion-Matrix**; `partial`/`n_done` markieren
  einen per Graceful-Stop verkürzten Lauf. Die **Hardware-Last**
  (`{cpu_pct, ram_gb}`) ist **kein** Runner-Event — der Server misst sie per
  `psutil` am Subprozess und hängt sie an die training-WS-Payload (s.
  *Demo-Bühnen-Features*).
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
  - `POST /training/stop` — **Graceful Stop** (SIGINT → Teilergebnis retten,
    s. *Demo-Bühnen-Features*); SIGKILL nur als Timeout-Fallback.
  - `POST /training/runs/{id}/sandbox` — lädt das Run-Joblib **temporär** in die
    `LiveInference`-Singleton (ohne Promotion), für den Live-Test am Handgelenk.
  - `GET /training/runs` — Run-Historie (scannt `models/runs/`).
  - `GET /training/runs/{id}` — Detail eines Laufs (cv/oof/config).
  - `POST /training/runs/{id}/promote` — setzt Lauf als Headline (kopiert in
    die kanonischen Pfade). **Einziger** Weg, kanonische Artefakte zu ändern.
  - `GET /training/runs/{id}/compare?other={id}` — zwei Läufe + gepaarter
    Wilcoxon (`src/evaluation/significance.py`).
- **WS:** das bestehende `_status_loop`/`_broadcast` trägt zusätzlich
  `{type:"training", phase, model, pool, fold, n, folds[], mean_acc,
  confusion{}, hw{cpu_pct,ram_gb}, ...}`.

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
    Log-Ticker, Hardware-Sparkline, **Live-Confusion-Matrix** (akkumuliert),
    Stop. Die übrigen Analyse-Module (ROC, Feature-Importance, Burst,
    Leaderboard, Task) bleiben dem *fertig*-Zustand vorbehalten (live halbleer).
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

**Analyse-Module (im *fertig*-Zustand — Ausnahme: Confusion akkumuliert schon
live) — je mit Drill-in:**
1. **Confusion-Matrix** (akkumuliert bereits im *läuft*-Zustand) → Drawer:
   volle Raten + Precision/Recall (optional per Task).
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

## Demo-Bühnen-Features (Tier 1 — fest im Scope)

Macht aus dem Cockpit eine interaktive Bühne für die Verteidigung.

- **Graceful Stop (Soft-Stop).** Stop sendet **SIGINT**; die Runner fangen
  `KeyboardInterrupt`, finalisieren die bereits fertigen Folds, schreiben die
  Artefakte und emittieren `run_end {partial:true, n_done}` → Zustand „fertig".
  Erlaubt das „ich stoppe bei Fold 5"-Manöver: die volle Analyse baut sich für
  die fertigen Folds auf, **klar als *partial n/N* gelabelt** (kein Verkaufen
  als volle Zahl). SIGKILL nur als Timeout-Fallback (wie `pen_proc`).
- **Live-Confusion-Matrix.** `fold_end` trägt die per-Fold-2×2; die UI
  akkumuliert sie **schon während des Laufs**. Einzige Stat, die live sinnvoll
  wächst (ROC/Feature-Importance brauchen den vollen Lauf) — bei P17 leuchtet
  die FP-Zelle live auf.
- **Hardware-Sparkline.** Der `TrainingRun` misst per `psutil` CPU-/RAM-Last des
  Subprozesses (1 Hz) → WS. Glühende Mini-Sparkline im Cockpit-Header („die
  Maschine schuftet", v. a. bei Deep/harnet).
- **Sandbox-Inference.** Button neben „Als Headline speichern" → lädt das
  Run-Joblib **temporär** in die `LiveInference`-Singleton (nutzt den
  vorhandenen Hot-Swap + Buffer-Clear), **ohne** die Headline zu überschreiben.
  **Gate:** nur live-fähige Modelle (RF/Tree/kausale Deep wie TCN); BiLSTM
  (nicht-kausal) und harnet (kein Live-Embedding-Pfad) ausgegraut.

## Stretch (God-Tier — additiv, eigene Plan-Phase)

- **SHAP-Waterfall.** Im Drill-in eines **einzelnen** Fensters (z. B. ein
  P17-False-Positive): `shap.TreeExplainer` (schnell + exakt für Tree-Modelle)
  zeigt den Beitrag jedes Features zur Vorhersage als Wasserfall. „Öffne die
  Blackbox" — passt zum Lehr-Charakter. Nur Tree-Modelle (Deep bräuchte einen
  anderen Explainer → später).
- **Session-Replay-Geist.** Held-out-Session im Schnelldurchlauf durchs Modell
  (nutzt `scripts/ml/replay_live_inference.py`); Predicted-vs-True scrollt live,
  FP/FN leuchten. Echte Predictions auf echten Daten — die ehrliche Alternative
  zum 3D-Twin.
- **Auto-Narrativ schwache Folds.** Ein-Zeilen-Erklärung pro schwachem Fold aus
  den Markern (P07 Denkpausen, P09 Soft-Writer) — die dokumentierten
  Failure-Modi als Live-Text statt nur Zahlen.

## Neue Abhängigkeiten

- `psutil` (Hardware-Sparkline, Tier 1).
- `shap` (SHAP-Waterfall, Stretch).
- Beide in `requirements.txt` ergänzen.

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
- Graceful Stop: SIGINT auf einen laufenden Runner → `run_end {partial:true}`
  mit den fertigen Folds, Artefakte geschrieben (kein Datenverlust).
- `fold_end` trägt `confusion{}`; `test_training_endpoints.py` deckt
  `/runs/{id}/sandbox` (temporärer Live-Load, kein Promote) + 404 ab.
- Hardware-Sample: `psutil`-Messung liefert plausible `cpu_pct/ram_gb` (Mock).

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
- **Quaternion-Capture (forward-only, jetzt anfangen):**
  `CMDeviceMotion.attitude.quaternion` (qx/qy/qz/qw) liegt im selben `motion`-
  Objekt bereit, das `MotionManager.swift` schon abgreift (Z. 158-184) — es wird
  nur nicht in den Sample geschrieben. Es ist die **hardware-fusionierte
  Handgelenk-Orientierung** (50 Hz). Mitzustreamen (4 Floats zum Sample, neue
  Watch-CSV-Spalten, neuer Pool wie damals bei Gravity) ist billig und
  **forward-only** — nicht retro-imputierbar, jede ohne sie aufgenommene Session
  verliert die Orientierung dauerhaft. Empfehlung: **früh sammeln**, auch wenn
  die Nutzung später kommt (das Gravity-Playbook). Schaltet frei: (a) den
  faithful 3D-Twin, (b) world-frame-/orientierungs-invariante Features
  (userAccel per Quaternion in den gravity-aligned World-Frame drehen).
- **3D Digital Twin (Roadmap, nicht Demo-Scope):** mit getracktem Quaternion
  **faithful machbar** — animiert die echte Watch-/Handgelenk-Orientierung (kein
  geratener Avatar). *Korrektur:* meine frühere Ablehnung „Watch hat kein
  Quaternion" war falsch. Grenze bleibt: Quaternion = Wrist-Pose, **nicht**
  Finger-Level-Handschrift; Kosten = Three.js-Dep + Datensammlung. Daher nach
  der Demo; der **Session-Replay-Geist** ist die sofort baubare ehrliche
  Alternative.
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

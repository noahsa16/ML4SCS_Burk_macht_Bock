# Fusions-Kandidaten + Pod-Run-Plan (Stand 2026-07-07)

Kontext: Abschlusspräsi Donnerstag. Das HP-Grid-Leaderboard
([hp_grid_leaderboard.md](hp_grid_leaderboard.md)) ist komplett; offen sind die
Stage-2-Bestätigung, der N=22-Headline-Refresh und die Frage, welche
Modell-Kombinationen noch Fusions-Potenzial haben.

## Leitgröße: Residuen-Korrelation, nicht Solo-Stärke

Ob Proba-Mittelung zweier Modelle hebt, entscheidet nicht die Güte der
Solo-Arme, sondern wie **unkorreliert ihre Fehler** sind — gemessen als
`r(a−y, b−y)` auf den OOF-Probas. Empirische Anker im Projekt:

| Paar | r(Residuen) | Ergebnis |
|---|---:|---|
| tcn6 × RF (nativ-5s, LOSO-20) | **0.599** | Ensemble 0.909, schlägt BEIDE Solos signifikant (`reports/tcn_rf_fusion.md`) |
| harnet5 × RF (nativ-5s, N=14) | 0.574 | null — Gewinn redundant zur Burst-Aggregation (`reports/harnet_rf_fusion.md`) |
| tcn6 × tcn_gru (Smoke, grouped-3-fold, 1 Epoche) | **0.902** | null — alle Wilcoxon n.s. |

Kernmechanismus: alle Deep-Netze lernen aus denselben rohen 6-Kanal-Sequenzen
mit demselben Loss und konvergieren auf ähnliche Entscheidungsgrenzen — sie
irren an denselben ambigen Fenstern (P17-Tippen). Der RF sieht eine *andere
Projektion* (88 handgebaute Features). Fehler-Diversität entsteht durch
verschiedene **Repräsentationen**, nicht verschiedene Architekturen auf
gleicher Repräsentation. Deep×Deep-Paare starten daher mit strukturellem
Handicap (erwartetes r ≳ 0.75); Cross-Paradigma (Deep×RF) ist der einzige
Fusions-Typ mit nachgewiesenem Lift.

## Paarungs-Ranking (nach erwarteter Fehler-Diversität)

1. **`inception × tcn_bigru`** — das diverseste Deep-Paar: reines
   Multi-Scale-CNN (parallele Kernel 9/19/39, keine Rekurrenz) vs.
   TCN-Trunk + bidirektionaler GRU. Default-Arme des Tools
   `scripts/ml/deep_deep_fusion.py`. Ehrliche Erwartung: r fällt ggü. 0.902,
   bleibt aber hoch; Lift klein bis null.
2. **`inception × tcn_gru`** — gleiche Logik, Partner ist der einzige
   multi-seed-bestätigte Front-Runner (0.9222 ± 0.0036 @3 Seeds).
3. **`inception × RF`** — der Kandidat mit dem höchsten Erwartungswert:
   Cross-Paradigma wie der einzige Fusions-Erfolg (tcn6×RF, r=0.599 →
   0.909), aber mit dem solo stärkeren Deep-Arm (inception 0.9256 vs. tcn6
   0.9196 auf der grouped-5-fold-Suche). Wenn ein Paar über die 0.909 kommt,
   dann dieses. *Voraussetzung:* `scripts/ml/tcn_rf_fusion.py` ist auf tcn6
   fest verdrahtet und muss auf ein `--model`-Flag parametrisiert werden
   (kleiner Umbau, offen).

## Nicht mehr testen: weitere Hybrid-Architekturen

**`InceptionBiGRUHybrid` (verworfen).** Die Evidenz gegen weitere
Gewinner-Kreuzungen liegt seit `tcn_bigru_attn` vor: die Kreuzung der beiden
Einzel-Deltas (BiGRU + Attention-Pooling) landete mittig im Pack (0.9257) und
schlug keinen der Eltern. Die Top-6 des Leaderboards liegen in 1,2 pp Spanne
bei ±1,7 pp Rausch-Floor (Seed + cuDNN-Nichtdeterminismus) — eine weitere
Architektur @1 Seed ist ein Lotterielos, keine Messung. GPU-Zeit gehört in die
Stage-2-Bestätigung, die als einzige aus einer Einzelzahl eine zitierbare
Aussage macht.

## Pod-Queue (priorisiert)

| Prio | Lauf | Zweck / Output |
|---|---|---|
| 1 | **Stage 2: `tcn_bigru` @3 Seeds auf LOSO-20**, Sieger-HP aus dem Leaderboard (lr 3e-4 / drop 0.2 / bs 64 / wd 1e-5), gepaart gegen `tcn_gru` via `src/evaluation/significance.py` | einzige Zahl, die zitierfähig wird — hält 0.9314 → neuer Front-Runner; kollabiert es → „kein Modell bricht aus" bestätigt |
| 2 | **N=22-RF-Headline-Refresh** (`train_loso --pool legacy --save-cv-csv --save-oof --save-final-model` + `train_rf_all_live.py`) | finale Projekt-Headline; regeneriert `loso_cv_legacy.csv` / `rf_all.joblib` / `rf_all_live.joblib` (alle noch N=15/N=14) |
| 3 | **`deep_deep_fusion.py --model-a inception --model-b tcn_bigru`** (Tool committet, turnkey) | Deep×Deep-Test; erwartet Negativ-Bullet mit r-Diagnose |
| 4 | **inception × RF** (nach Parametrisierung von `tcn_rf_fusion.py`) | höchster Erwartungswert für einen echten Lift über 0.909 |

Alle vier parallelisieren (der Pod trug zuletzt 5 Jobs bei 98–99 % GPU).
Step 0: Pod hochfahren + Sync (Repo-Pull `development`, Daten inkl.
S062/S063-Legacy-Views, Secrets) — der Pod von 2026-07-06 wurde gekillt.

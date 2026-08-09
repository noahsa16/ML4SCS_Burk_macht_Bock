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

## Ungetestete Config-Taschen (und die Messlatte davor)

Das HP-Grid deckt nur **Trainings-Nuisance-Parameter** ab (lr / dropout /
batch / wd). Die **Kapazitäts-Achsen** der Modelle wurden nie variiert:

| Ungetestete Achse | Status | Erwartungswert |
|---|---|---|
| `tcn_bigru`-Breite (rnn_hidden 32→64, Trunk 16→24) | 4 Trials gesamt, Breite nie variiert — der 0.9314-Leader ist praktisch ungetunt | am ehesten lohnend: stärkstes Modell + kleinste Suche bisher |
| `inception`-eigene HPs (Tiefe, nf, Bottleneck, Kernel-Set) | 4 Trials, nur lr/dropout — die InceptionTime-Paper-Achsen unberührt | mittel |
| Trainings-Rezept (Cosine-Schedule, Label-Smoothing, Warmup) | komplett ungetestet, orthogonal zu allem bisherigen | Wildcard |
| Fenster > 5 s | getestet — plateauiert bei ~5 s (Log §3) | ✗ erledigt |
| Augmentation, Reweighting, neue Features | dreifach/mehrfach falsifiziert | ✗ erledigt |

**Die Messlatte:** Rausch-Floor ±1,7 pp bei *fixem* Seed (cuDNN; 0.9271 vs
0.9106 dokumentiert). Ein neuer 1-Seed-Trial müsste **~0.948+** zeigen, um
unterscheidbar über tcn_bigrus 0.9314 zu liegen. Kein Modell aus sechs
Familien (RF, MiniRocket, TCN-Zoo, GRU-Zoo, Transformer, InceptionTime) plus
Transfer-Learning (harnet) kam in die Nähe — alle klemmen bei 0.91–0.93 mit
denselben schwachen Folds (P17). Fingerabdruck einer **Daten-Decke**, nicht
einer Config-Decke.

**Selektions-Falle:** jeder weitere 1-Seed-Trial ist eine Ziehung aus einer
Verteilung mit σ ≈ 1,7 pp. 20 neue Lose schieben das Leaderboard-Max fast
sicher um +0,5–1 pp — durch reine Ordnungsstatistik, bei null echter
Verbesserung. Mehr Suche ohne Stage-2-Priorität macht die Zahlen *schlechter*
zitierbar.

**Kompromiss (Prio 5):** EIN fokussiertes Kapazitäts-Probe —
`tcn_bigru`-Breiten-Grid, 4 Trials (rnn_hidden {32, 64} × Trunk-hidden
{16, 24}), Sieger-Trainings-HP fix, 1 Seed, grouped-5-fold
(`configs/hp/tcn_bigru_wide.json`, gleiche focused-probe-Mechanik wie die
Pre-Donnerstag-Probes). Entscheidungsregel a priori: **nur > 0.945 ist ein
Signal** und wandert in Stage 2; alles darunter wird als Rauschen dokumentiert.

## Multi-Modell-Komitees (N > 2)

OOF-Probas aus verschiedenen Läufen liegen auf **identischen Folds**
(grouped-5-fold, `random_state=42`, gleiche Session-Selektion) —
N-Wege-Ensembles sind daher reines **Post-Processing auf vorhandenen CSVs,
null GPU**. Optionen, gerankt:

1. **Seed-Ensemble (3× tcn_bigru @ Seeds 42/43/44 mitteln) — bestes
   Preis-Leistungs-Verhältnis.** Der ±1,7-pp-Floor ist Seed-/cuDNN-*Rauschen*,
   und genau Rauschen bügelt Mittelung garantiert weg. Die 3 Seeds trainiert
   Stage 2 (Prio 1) ohnehin → das Ensemble ist eine Zeile Post-Processing auf
   einem Lauf, der sowieso läuft. Erwartung: Stabilität sicher, acc +0,3–0,8 pp
   plausibel.
2. **Drei Paradigmen: RF + Deep + MiniRocket.** Konzeptionell das schönste
   Komitee — drei fundamental verschiedene *Repräsentationen* (handgebaute
   Features / gelernte Features / zufällige Conv-Kernel). MiniRocket ist
   CPU-billig (läuft lokal); braucht einen `--save-oof`-Neuzug der
   MiniRocket-Probas. Caveat: MiniRocket hat dieselbe schwache Fold P17 —
   auf den harten Fenstern korrelieren die Fehler paradigmen-übergreifend.
3. **Triple RF + inception + tcn_bigru.** Fällt gratis aus Prio 3+4 ab
   (beide Fusion-Tools speichern OOF-CSVs mit den Arm-Probas → offline joinen
   und dritteln). Der zweite Deep-Arm bringt kaum *neue* Information
   (r ≈ 0.8–0.9 untereinander), wirkt aber als Varianz-Reduktion des
   Deep-Arms vor der RF-Fusion.
4. **Gelernte Gewichte / Stacking — verworfen.** Bereits getestet und null
   (harnet×RF-Stack, `reports/harnet_rf_fusion.md`); bei 5–20 Folds ist
   Gewichts-Fitting selbst nur Rauschen plus Leakage-Risiko. Simples Mittel
   bleibt der Default.

**Obergrenze für jedes Komitee:** Ensembling mittelt *idiosynkratisches*
Rauschen weg, nicht *geteilten systematischen* Fehler. Sechs Modellfamilien
scheitern an denselben P17-Tipp-Fenstern — dieser Anteil bleibt im Mittel
aller Probas. Realistische Decke des besten Komitees: ~0.91–0.92 (nativ-5s);
tcn6×RF (0.909) hat davon vermutlich schon das meiste abgeschöpft.

**Tooling-Idee:** `scripts/ml/ensemble_committee.py` — nimmt beliebig viele
OOF-CSVs, joined auf Fold + Fenster, rechnet alle 2er/3er/Ner-Kombinationen
mit Residuen-r + gepaartem Wilcoxon durch. Einmal gebaut, beantwortet es alle
Komitee-Fragen aus einem Aufruf.

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
| 5 | **`tcn_bigru_wide`-Kapazitäts-Probe** (4 Trials, 1 Seed, grouped-5-fold; Signal-Schwelle 0.945) | schließt die größte offene Config-Tasche mit vorab fixierter Entscheidungsregel |

**Post-Processing danach (null GPU):** Seed-Ensemble aus den Stage-2-Probas
(Prio 1), Triple-Komitee aus den OOF-CSVs von Prio 3+4, optional
Drei-Paradigmen-Komitee nach lokalem MiniRocket-`--save-oof`-Zug — Auswertung
gebündelt via `ensemble_committee.py` (siehe oben).

Alle Läufe parallelisieren (der Pod trug zuletzt 5 Jobs bei 98–99 % GPU).
Step 0: Pod hochfahren + Sync (Repo-Pull `development`, Daten inkl.
S062/S063-Legacy-Views, Secrets) — der Pod von 2026-07-06 wurde gekillt.

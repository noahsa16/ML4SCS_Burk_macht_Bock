# Sort-Stability-Bug — Trainings-/Live-Diskrepanz (2026-05-25)

Forensik. Discovered beim ersten Live-Inference-Test auf der Recording-
Page: das deployte `rf_noah`-Modell sagte Schreiben praktisch garnicht
vorher (Accuracy ~0.57), obwohl es offline 0.876/0.938 erreichte.

## Symptom

Replay-Skript `scripts/ml/replay_live_inference.py` fütterte
`data/raw/watch/S033_watch.csv` Sample-für-Sample durch
`LiveInference.predict()` und verglich mit den gespeicherten
`S033_windows.csv`-Labels — der Test-Fold seines eigenen Modells:

| Metrik | Replay | Offline-Benchmark |
|---|---|---|
| Accuracy | 0.573 | 0.878 |
| F1(writing) | 0.506 | 0.907 |
| ROC-AUC | **0.962** | 0.939 |
| mean proba(writing-Samples) | **0.455** | ~0.95 |
| mean proba(idle-Samples) | 0.130 | ~0.08 |

**Diagnose-Signatur:** AUC bleibt hoch (Ranking funktioniert), Accuracy
kollabiert (Decisions falsch). Der Klassifikator weiss noch, *welche*
Fenster Schreiben sind — aber alle Schreib-Probas sind systematisch
**unter** den 0.5-Threshold geschoben. Klassisches Distribution-Shift-
Bild: Trainings-Features und Live-Features kommen aus zwei
unterschiedlichen Verteilungen.

## Root cause

`src/features/windows.py` Zeile 231 (vor Fix):

```python
df = merged.dropna(subset=[*IMU_COLS, "local_ts_ms"]).sort_values("local_ts_ms")
```

Und analog in `src/merge/merge.py` Zeile 132.

`pandas.DataFrame.sort_values` benutzt **per Default `kind='quicksort'`**,
welches **nicht stabil** ist. Bei gleichen Sortier-Keys verteilt es
Zeilen willkürlich um.

Die Watch streamt in **Batches** (10 Samples per WCSession-Message bei
50 Hz, mehr bei 100 Hz mit Disk-Spill). Der Server stempelt den
**Batch-Empfang** mit `local_ts_ms = int(time.time() * 1000)` — alle
Samples eines Batches teilen sich dieselbe `local_ts_ms`.

Konsequenz: Quicksort scrambled die Sample-Reihenfolge **innerhalb
jedes Batches**. Bei Disk-Spill-Drain (S032/S033: 100 Hz mit
Backfill von verspaeteten Samples) liegen bis zu 30 Samples mit
identischer `local_ts_ms` direkt nebeneinander → grosszuegiger Scramble.

### Live-Inferenz war NICHT betroffen

`src/server/inference.py`-Buffer ist eine `deque`, die Samples in
**Append-Reihenfolge** speichert — also genau wie sie aus dem
`POST /watch`-Handler kommen, ts-monoton. Live sieht eine *saubere*
Welt; Training sah eine *gescrambled* Welt. Modell wurde auf der
gescrambled Welt kalibriert und gibt bei der sauberen Welt Junk
zurueck.

## Was war wie betroffen

**Order-sensitive Features (alle gescrambled-anfaellig):**
- Spektrale Features (FFT): `dom_freq`, `spec_centroid`, `spec_entropy`,
  `band_3_8` — ueber alle 6 Achsen (24 Features).
- Jerk-Features: `np.diff(x) * fs_hz` — Acc-Achsen, Magnitudes
  (10 Features).
- ZCR: zero-crossing rate haengt an consecutive Sign-Changes (6 Features).
- Cross-Korrelationen: paaren Sample i in x mit Sample i in y
  (6 Features).

**46 / 88 Features = ~52 %** des Feature-Vektors sind order-abhaengig.

**Order-unabhaengige Features (unbetroffen):**
- Time-Stats: mean, std, min, max, rms, range (36 Features).
- Magnitude-Mean/Std/Energy (6 Features).

= 42 / 88 Features = ~48 %.

## Feature-Diff auf S033 (vor Fix)

`scripts/ml/diff_live_features.py S033`:

| Feature | mean\|diff\| (live − cached) |
|---|---|
| `gyro_mag_jerk_std` | 21.75 |
| `gyro_mag_jerk_mean_abs` | 12.92 |
| `ay_spec_centroid` | 9.86 |
| `rx_spec_centroid` | 9.10 |
| `ax_spec_centroid` | 9.06 |
| `az_spec_centroid` | 9.02 |
| `ay_jerk_std` | 4.86 |
| `az_dom_freq` | 4.78 |
| `ax_dom_freq` | 4.29 |

Order-sensitive Features waeren bei *konsistenter* Sortierung in beiden
Pfaden bit-exakt gleich. Die zweistelligen mean-abs-Diffs sind
empirischer Beweis, dass die Trainings-Pipeline auf einer anderen
Sample-Reihenfolge rechnete.

## Fix

Beide Stellen auf einen **stabilen Sort** umgestellt, mit dem
Watch-Per-Sample-Clock `ts` als Sort-Key (per-Sample monotonic,
keine Ties):

`src/features/windows.py`:
```python
sort_col = "ts" if "ts" in merged.columns else "local_ts_ms"
df = merged.dropna(subset=[*IMU_COLS, sort_col]).sort_values(sort_col, kind="stable")
```

`src/merge/merge.py`:
```python
watch = watch.dropna(subset=["local_ts_ms"]).sort_values("local_ts_ms", kind="stable")
pen = pen.dropna(subset=["local_ts_ms"]).sort_values("local_ts_ms", kind="stable")
```

Damit ist:
1. Die Sample-Reihenfolge in `merged.csv` und `windows.csv`
   per-Sample monotonic via `ts`.
2. Live-Buffer ebenfalls per-Sample monotonic (war es schon).
3. **Trainings- und Live-Features bit-identisch** modulo der
   fs_hz-Schaetzungs-Diff (siehe unten).

## Verifikation

Nach Re-Training von `rf_noah` (S032+S033) und `rf_all_live` (10
Probanden) auf den korrigierten Features:

**Replay S033:**

| Metrik | Vor Fix | Nach Fix |
|---|---|---|
| Accuracy | 0.573 | **0.978** |
| F1(writing) | 0.506 | **0.983** |
| ROC-AUC | 0.962 | **0.992** |
| mean proba(writing) | 0.455 | **0.894** |
| mean proba(idle) | 0.130 | 0.119 |

`gyro_mag_jerk_std` mean|diff| 21.75 → **4.41** (5× besser). Rest-Diff
kommt aus fs_hz-Schaetzung: Training uses *global* `infer_fs_hz()`
(99.302), live uses *per-window* `_estimate_fs()` (~99.526). 0.2%
Diskrepanz, in der Praxis irrelevant (RF robust dagegen).

## Impact auf publizierte Headline-Zahlen

Alle bestehenden LOSO-Auswertungen wurden auf gescrambled Features
gerechnet. **Trainings- und Test-Daten lagen in derselben gescrambled
Welt** → das Modell war intern konsistent kalibriert, das LOSO mass
ehrlich Generalisierung auf gescrambled Daten. Aber:

1. Das Modell deployed auf live-saubere Daten brach zusammen.
2. Die "wahren" Headline-Zahlen sind die Re-Runs mit Fix.
3. **Alle relativen Vergleiche** (gap-Sweep, N-Verlauf, Per-Subject-
   Threshold, Sync-Audit, Modell-Vergleich) bleiben gueltig, weil
   beide Seiten symmetrisch durch den Bug liefen.

**Headline-LOSO N=10 nach Fix:**

| Metrik | Pre-Fix (CLAUDE.md alt) | Post-Fix | Δ |
|---|---|---|---|
| Acc @1s | 0.856 ± 0.032 | **0.863 ± 0.032** | +0.7 pp |
| AUC @1s | 0.928 ± 0.033 | **0.935 ± 0.032** | +0.7 pp |
| F1(w) @1s | 0.864 | **0.875** | +1.1 pp |
| Acc @5s | 0.887 | **0.902 ± 0.035** | +1.5 pp |
| AUC @5s | 0.960 | **0.968 ± 0.030** | +0.8 pp |
| Acc @10s | 0.870 | **0.885 ± 0.037** | +1.5 pp |
| AUC @10s | 0.944 | **0.957 ± 0.025** | +1.3 pp |
| Acc @30s | 0.831 | **0.844 ± 0.034** | +1.3 pp |
| AUC @30s | 0.909 | **0.922 ± 0.029** | +1.3 pp |

Systematischer Gain ueber alle Skalen — das Scrambling hatte dem Modell
echte Information verbrannt. Per-Fold:

| Fold | Pre-Fix Acc | Post-Fix Acc | Δ |
|---|---|---|---|
| Noah | 0.910 | 0.912 | +0.2 |
| P01 | 0.893 | 0.897 | +0.4 |
| P02 | 0.864 | 0.883 | +1.9 |
| P03 | 0.825 | 0.855 | +3.0 |
| Taji | 0.832 | 0.864 | +3.2 |
| P04 | 0.870 | 0.883 | +1.3 |
| P05 | 0.825 | 0.861 | +3.6 |
| P07 | 0.808 | 0.801 | −0.7 |
| P08 | 0.858 | 0.851 | −0.7 |
| P09 | 0.812 | 0.823 | +1.1 |

8 von 10 Folds verbessern sich. P07/P08 marginal regredieren, aber
beide @30s-Burst-AUC steigt deutlich (P07: 0.853 @1s → 0.932 @30s
mit Fix, war 0.808 → 0.932 vor Fix; @30s also unveraendert stark).

## Was als naechstes nachgefahren werden sollte

1. **100-Hz-Ablation (`reports/100hz_ablation.md`)** — Disk-Spill bei
   100 Hz hatte deutlich mehr Ties (30 Samples / batch nach Drain) als
   50 Hz (10 Samples / batch). Das Vergleichs-Setup war stark *ungleich*
   verrauscht; "100 Hz bringt nichts" basiert auf einer ungleichen
   Stichprobe und verdient einen Re-Run.
2. **CNN/LSTM/GRU-Vergleich** (Roadmap-Memory `zwischenpraesi-roadmap.md`)
   — Deep-Modelle lernen Features aus Rohwellen, der Scramble haette
   sie hart getroffen. RF blieb relativ robust (cumulative Statistiken
   ueberwiegen). Deep-Re-Run koennte den Gap zu RF kleiner machen.
3. **Headline-Update in `CLAUDE.md`** — die alte 0.856-Zahl muss
   sauber durch 0.863 ersetzt werden, mit Verweis auf diesen Report.

## Lehre

`pandas.sort_values` ist nicht stabil per Default. Bei Daten mit
*natuerlichen Ties* in der Sortier-Spalte (Batch-Timestamps, gleiche
Score-Bins, replizierte Events) **immer** `kind='stable'` setzen oder
auf einen tie-freien Key sortieren. Tests, die End-to-End-Pipeline
gegen sich selbst pruefen, fangen das nicht — beide Seiten sind dann
gleich gescrambled. Erst der Live-Pfad mit anderer Eingangs-Ordnung
deckt es auf.

Tautologische Test-Versionen (vgl. `tests/test_inference.py::test_feature_parity_with_build_windows` — beide Seiten rufen
`_window_features` mit denselben Argumenten) entdecken die Sache nicht.
Echter Parity-Test muesste eine bekannte Session durch beide Pipelines
schicken und Feature-Vektoren bit-vergleichen — das war der eigentliche
Diagnose-Schritt hier.

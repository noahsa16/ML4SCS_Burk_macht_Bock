# N=32-Retrain: RF, HMM und Deep auf der erweiterten Kohorte

**Datum:** 2026-08-25
**Lauf:** RunPod, 2026-08-24/25, abgeholt via `fetch_results.sh` →
`models/runs/pod_20260825/`
**Git-SHA der Läufe:** `fbbee13` (legacy), `84f15ad` (modern)
**Protokoll:** grouped-5-fold by person (`GroupKFold`, `random_state=42`),
Deep zusätzlich über 3 Seeds (42/43/44)

## 1. Kernaussage

Die Kohorte ist von 20 auf **32 Personen** gewachsen (Legacy-Pool, 50 Hz) bzw.
auf **23** (Modern-Pool, 100 Hz + Gravity). Das trennt zwei Dinge, die vorher
nicht zu trennen waren:

**Der Random Forest steht still, das Deep-Netz steigt.** Bei 60 % mehr Personen
bewegt sich der RF nicht (0.869 → 0.865), während `tcn_bigru` um knapp einen
Prozentpunkt zulegt (0.9114 → 0.9209). Die dokumentierte „Decke" ist damit
keine Eigenschaft des Signals, sondern eine Eigenschaft der **Modellklasse**:
der RF auf 88 Handbau-Features hat seine Kapazität ausgeschöpft, das
Sequenzmodell hat noch Luft.

**Der HMM-Gewinn repliziert exakt.** Alle vier gepaarten Vergleiche aus dem
N=15-Report kommen bei N=32 mit gleicher Richtung, gleicher Größenordnung und
p < 1e-5 wieder — inklusive der Filter-vs-Smoother-Lücke von 1,9 pp.

**P33 war kein Sensor-Floor, sondern ein Alignment-Artefakt.** Nach dem
δ-Guard-Fix liegt P33 bei 0.843 statt bei den vierfach replizierten ~0.68.

## 2. Kohorte

| Pool | Hz | Kanäle | Personen | Fenster |
|---|---:|---:|---:|---:|
| legacy | 50 | 6 | **32** | 81.938 |
| modern | 100 | 6 bzw. 9 | **23** | — |

Legacy-Personen: Noah, P01–P05, P07–P09, P12–P15, P17, P26, P27, P29, P31–P34,
P54, P57, P60, P61, P63, P64, P66, P71–P73, Taji.
Writing-Anteil im OOF: 44,4 % (σ 8,4 pp über die Personen).

**Datenstand-Verifikation.** Der Pod-Lauf lief auf den **δ-korrigierten** Daten:
P33/S062 hat im Pod-OOF 3.035 Fenster bei writing-Anteil 0,412 — bit-identisch
zur lokal nach dem Fix regenerierten `windows/50hz/S062_windows.csv`
(2026-08-08 16:52). Das ist relevant, weil `sweep_data.zip` auf R2 nach dem
δ-Audit als regenerations-pflichtig markiert war; die Prüfung zeigt, dass die
Regeneration vor dem Lauf erfolgt ist.

## 3. Random Forest

Grouped-5-fold, 1-s-Fenster, per-Session-Z-Score, `max_gap_ms=2500`:

| Entscheidungsfenster | acc | AUC |
|---|---:|---:|
| 1 s | **0.8659 ± 0.0196** | **0.9390 ± 0.0149** |
| 5 s (Burst, kausal) | 0.8647 ± 0.0226 | 0.9341 ± 0.0149 |
| 10 s | 0.8334 ± 0.0239 | — |
| 30 s | 0.7751 ± 0.0231 | — |

F1(writing) 0.8386 ± 0.0276.
Per-Person aus dem OOF gerechnet (32 Folds statt 5 Gruppen): acc
0.8654 ± 0.0351, AUC 0.9423 ± 0.0291 — die Gruppen-σ (1,96 pp) unterschätzt die
Personen-σ (3,51 pp) erwartungsgemäß, weil sie über je 6–7 Personen mittelt.

### Die Decke, quantifiziert

| Kohorte | acc | AUC |
|---|---:|---:|
| N=20 | 0.869 ± 0.032 | 0.946 |
| N=22 | 0.863 ± 0.051 | 0.937 |
| **N=32** | **0.865 ± 0.035** | **0.942** |

Zwölf zusätzliche Personen bewegen den RF um −0,4 pp — Rauschen. Das ist der
sauberste Beleg für die Kapazitätsgrenze, den das Projekt hat: die Achse „mehr
Daten" wurde tatsächlich beschritten, und der RF hat nicht reagiert.

## 4. HMM-Post-Processing

Leakage-freier Per-Person-Holdout über alle 32 Folds: Übergangsmatrix und
Klassen-Prior werden je Fold **nur** aus den übrigen 31 Personen geschätzt.
Emission ist `proba_cal`; das HMM lernt ausschließlich die Übergänge.

| Decoder | kausal? | acc | AUC | F1(w) |
|---|:--:|---:|---:|---:|
| RF 1 s roh | ja | 0.8654 ± 0.0351 | 0.9423 | — |
| Burst @5 s (kalibriert) | ja | 0.8610 ± 0.0367 | 0.9343 | — |
| **HMM Forward-Filter** | **ja** | **0.8981 ± 0.0345** | **0.9619 ± 0.0255** | 0.8838 |
| HMM Forward-Backward | nein | 0.9168 ± 0.0368 | 0.9731 | — |
| Viterbi | nein | 0.9153 ± 0.0380 | — | 0.9037 |

### Gepaarte Tests (Wilcoxon, 32 Folds)

| Vergleich | Δ acc | p | gewonnene Folds |
|---|---:|---:|---:|
| RF-1s → +HMM-Filter | **+0.0327** | < 1e-5 | **32 / 32** |
| Burst@5s → +HMM-Filter | +0.0371 | < 1e-5 | 32 / 32 |
| HMM-Filter → Smoother | +0.0187 | < 1e-5 | 31 / 32 |
| HMM-Filter → Viterbi | +0.0172 | < 1e-5 | 31 / 32 |
| RF-1s → +HMM-Filter (AUC) | +0.0196 | < 1e-5 | 32 / 32 |

**Negativkontrolle bestanden.** Per-Session geshuffelte Emission → acc 0.5163
± 0.0254; konstante Emission → 0.4436 (= Klassenprior). Ohne zeitlich
aligniertes Signal kollabiert der Filter auf Zufall, misst also nicht bloß die
Blockstruktur der Labels.

**Filter vs. Smoother, 1,9 pp.** Der nicht-kausale Decoder gewinnt in 31 von 32
Folds. Das bestätigt die bestehende Deployment-Trennung: der **Live**-Pfad muss
den Filter nehmen (er darf die Zukunft nicht sehen), ein **Tagestracker**, der
abends den Tag rekonstruiert, darf den Smoother nehmen und bekommt die 1,9 pp
geschenkt.

## 5. Deep-Modelle

Nativ-5-s-Fenster, kein Z-Score, grouped-5-fold, je 3 Seeds:

| Pool | Modell | Kanäle | acc | AUC | Seeds einzeln |
|---|---|---:|---:|---:|---|
| legacy (N=32) | **tcn_bigru** | 6 | **0.9209 ± 0.0057** | **0.9753** | 0.9250 / 0.9232 / 0.9144 |
| legacy (N=32) | tcn6 | 6 | 0.9154 ± 0.0071 | 0.9741 | 0.9080 / 0.9159 / 0.9222 |
| modern (N=23) | tcn6 | 9 | 0.9108 ± 0.0038 | 0.9716 | 0.9092 / 0.9081 / 0.9151 |
| modern (N=23) | tcn_bigru | 9 | 0.9099 ± 0.0020 | 0.9687 | 0.9107 / 0.9076 / 0.9114 |
| modern (N=23) | tcn_bigru | 6 | 0.9093 ± 0.0019 | 0.9690 | 0.9113 / 0.9078 / 0.9087 |
| modern (N=23) | tcn6 | 6 | 0.9022 ± 0.0067 | 0.9663 | 0.9081 / 0.8950 / 0.9036 |

### Deep skaliert mit Daten, der RF nicht

| Modell | N=22 (Vorlauf) | N=32 | Δ |
|---|---:|---:|---:|
| tcn_bigru | 0.9114 ± 0.005 | **0.9209 ± 0.006** | **+0.95 pp** |
| tcn6 | 0.9086 ± 0.003 | 0.9154 ± 0.007 | +0.68 pp |
| RF | 0.863 | 0.865 | +0.2 pp |

Beide Deep-Modelle steigen um mehr als ihre Seed-σ, der RF bleibt flach. Das ist
der inhaltlich wichtigste Befund des Laufs.

### Gravity-Verdikt revidiert

Der 6-vs-9-Kanal-Vergleich auf dem Modern-Pool dreht gegenüber N=7:

| Modell | 6 Kanäle | 9 Kanäle (+Gravity) | Δ |
|---|---:|---:|---:|
| tcn6 | 0.9022 | 0.9108 | **+0.86 pp** |
| tcn_bigru | 0.9093 | 0.9099 | +0.06 pp |

Bei N=7 war der Befund „Gravity schadet `tcn_bigru` um 2,7 pp und ist für
`tcn6` neutral" — bei N=23 hilft Gravity dem `tcn6` und ist für `tcn_bigru`
neutral. Die frühere Aussage war ein Kleine-Stichproben-Artefakt. Die
Orientierung des Handgelenks relativ zur Schwerkraft trägt cross-subject also
doch Information, aber nur für die Architektur ohne rekurrenten Kopf — plausibel
deutbar: der BiGRU rekonstruiert vergleichbare Lage-Information ohnehin aus dem
zeitlichen Verlauf.

## 6. RF gegen Deep bei gleicher Latenz

Der ehrliche Vergleich hält die Entscheidungslatenz fest:

| Pfad | Latenz | acc |
|---|---|---:|
| RF 1 s + Burst @5 s (kausal) | 5 s | 0.8610 |
| **`tcn_bigru` nativ 5 s** | 5 s | **0.9209** |
| RF 1 s + HMM-Filter (kausal) | ~16 s adaptiv | 0.8981 |

Bei identischem 5-s-Fenster liegt das Sequenzmodell **6,0 pp** über dem RF. Auch
gegen den HMM-gestützten Live-Pfad, der mehr Kontext verbraucht, bleiben 2,3 pp
Vorsprung. Das bestätigt den bestehenden Befund „natives Lang-Fenster-Training
schlägt Burst-Aggregation von 1-s-Fenstern" auf der größten Kohorte.

## 7. Fold-Ebene

**Stärkste Folds (RF 1 s):** P26 0.909, P13 0.908, P57 0.907, P66 0.906.

**Schwächste Folds:**

| Person | RF 1 s | + HMM-Filter | + Smoother |
|---|---:|---:|---:|
| P73 | 0.783 | 0.850 | 0.879 |
| P31 | 0.787 | 0.814 | 0.817 |
| P63 | 0.787 | 0.818 | 0.831 |
| P15 | 0.825 | 0.867 | 0.909 |
| P17 | 0.828 | 0.840 | 0.853 |
| P34 | 0.831 | 0.865 | 0.885 |

**P33 rehabilitiert.** P33 lag in vier früheren Läufen bei ~0.68 und war als
„Sensor-Floor" dokumentiert (Extrem-Soft-Writer, dessen Schreiben nur 1,36× über
seiner eigenen Ruhe liegt). Nach dem δ-Guard-Fix — S062 trug ein spurioses
Alignment-δ von ~16 s — liegt P33 bei **0.843** (RF) bzw. **0.853** (HMM) und ist
damit ein durchschnittlicher Fold. Der „Sensor-Floor"-Befund war substanziell ein
Zeitachsen-Artefakt. `reports/p33_analysis.md` ist entsprechend überholt.

**P17 bleibt strukturell schwach** und profitiert am wenigsten vom HMM
(+1,2 pp gegenüber im Mittel +3,3 pp). Das passt zum dokumentierten Mechanismus:
P17s Fehler ist keine zeitliche Instabilität, die ein Sequenzmodell glätten
könnte, sondern eine systematische Verwechslung von aggressivem Tastatur-Tippen
mit Schreiben. Ein Übergangsmodell kann eine falsche, aber *stabile* Emission
nicht korrigieren.

**Neue schwache Folds P31, P63, P73** stammen aus der v2-Erweiterung. P73
profitiert stark vom HMM (+6,7 pp) — das deutet auf hochfrequentes Rauschen,
also die P07-Klasse; P31 dagegen nur +2,7 pp — die P09-Klasse mit systematischem
Amplituden-Problem.

## 8. Was dieser Lauf NICHT belegt

Ehrlichkeitshalber die Grenzen:

- **`tcn_bigru` > `tcn6` ist nominal, nicht belegt.** Die Confirm-Läufe
  persistieren nur Seed-Aggregate (drei Zeilen je Config), keine Per-Fold-OOF.
  `src/evaluation/significance.py` ist darauf nicht rechenbar; ein Wilcoxon über
  drei Seed-Paare hat ein minimales p von 0,25. Legacy Δ = 0,55 pp bei σ von
  0,57–0,71 pp; auf dem Modern-Pool sind es 0,09 pp und die Rangfolge dreht.
  **Für eine belastbare Aussage müssten die Confirm-Läufe mit persistierter
  Per-Fold-OOF wiederholt werden.**
- **Deep vs. RF ist aus demselben Grund nicht gepaart getestet.** Der Abstand
  von 5–6 pp liegt allerdings um eine Größenordnung über jeder beobachteten
  Seed-Streuung, und derselbe Vergleich war bei N=20 gepaart signifikant.
- **GPU-Nichtdeterminismus.** Dokumentiert sind 1,6 pp Spread bei *identischem*
  Seed (cuDNN-Autotuning). Einzel-Seed-Rankings zwischen Architekturen sind
  Rauschen; nur Mehr-Seed-Mittel auf identischen Folds zählen.
- **Legacy und Modern sind verschiedene Kohorten** (32 vs. 23 Personen). Die
  Zahlen dürfen nicht gegeneinander gelesen werden; der Gravity-Vergleich
  innerhalb des Modern-Pools ist dagegen sauber gepaart.
- **5-Fold-Signifikanz bleibt strukturell unterpowert** (minimales p = 0,0625) —
  das gilt für alle Grid-Vergleiche, nicht nur für diesen Lauf.

## 9. Konsequenzen fürs Deployment

1. **Der Live-Pfad ist bei N=32 bestätigt.** RF-1s + kausaler HMM-Filter liefert
   0.898 — der Gewinn von 3,3 pp gegenüber der rohen Proba gilt in 32 von 32
   Folds.
2. **`models/hmm_live.json` sollte aus dem N=32-OOF neu exportiert werden**
   (`scripts/pipeline/export_hmm_live.py`). Die aktuell deployten Parameter
   stammen aus einem deutlich kleineren OOF.
3. **Der Tagestracker darf den Smoother nehmen.** Rückwirkende Aggregation ist
   nicht kausal gebunden; 1,9 pp liegen dort ungenutzt.
4. **Die kanonischen lokalen Artefakte sind veraltet.** `models/loso_cv_legacy.csv`
   und `models/loso_oof_legacy.csv` stehen lokal auf N=20; die N=32-Fassungen
   liegen unter `models/runs/pod_20260825/results/`. Eine Promotion in die
   kanonischen Pfade steht aus.
5. **Für ein On-Device-Deployment ist die Architekturwahl neu zu bewerten.**
   `tcn6` ist auf dem deployment-relevanten Modern-Pool nominal vorn (0.9108 vs.
   0.9099) *und* frei von bidirektionalen rekurrenten Layern, die die
   PyTorch→CoreML-Konvertierung erschweren. Der Vorsprung von `tcn_bigru` liegt
   im Legacy-Pool, den die Uhr nicht mehr streamt.

## 10. Reproduktion

```bash
# HMM auf dem N=32-OOF (dieser Report, Abschnitt 4)
python scripts/ml/hmm_postprocess_loso.py \
    --oof models/runs/pod_20260825/results/loso_oof_legacy.csv \
    --out models/hmm_postprocess_n32_cv.csv

# Deep-Confirm-Läufe (auf dem Pod gelaufen)
python scripts/ml/run_grid_wandb.py configs/hp/tcn_bigru_confirm.json
python scripts/ml/run_grid_wandb.py configs/hp/tcn6_confirm_modern_grav.json
```

Artefakte: `models/hmm_postprocess_n32_cv.csv`,
`models/hmm_postprocess_detail.csv`, `reports/hmm_postprocess.md` (vom Skript
auf N=32 überschrieben — die N=15-Fassung steht in der Git-Historie),
`models/runs/pod_20260825/` (216 Checkpoints, RF-Joblib, OOF).

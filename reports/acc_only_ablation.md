# Acc-only vs. Full-IMU — Machbarkeit eines passiven Ganztags-Trackers

**Frage.** Ein passiver, batteriesparender Ganztags-Tracker auf der Watch würde
idealerweise `CMSensorRecorder` nutzen: zeichnet im Hintergrund auf, auch wenn die
App nicht im Vordergrund läuft. Diese API liefert laut Apple-Dokumentation jedoch
**ausschließlich Accelerometer-Daten** — kein Gyroskop. Unser Headline-Modell zieht
41 seiner 88 Features (~47 %) aus den Gyro-Achsen. Die Architektur-Frage lautet
daher: *Wie viel Genauigkeit kostet es, das Gyroskop wegzulassen?*

**Abgrenzung der Sensor-Modi.** Der aktuelle Aufnahme-Stream ist *nicht* acc-only:
`MotionManager.swift` nutzt `CMMotionManager.startDeviceMotionUpdates` (volle IMU —
`userAcceleration` + `rotationRate` + `gravity` + `attitude`), gehalten durch eine
`HKWorkoutSession`. Die acc-only-Einschränkung gilt nur für den *alternativen
passiven Pfad*:

| Modus | Gyro | passiv / Batterie | Hardware |
|---|---|---|---|
| `CMDeviceMotion` + Workout-Session (aktuell) | ja | aktive Session, Akku-Kosten | Series 7 ✓ |
| `CMSensorRecorder` (Passiv-Vorschlag) | **nein** | wirklich passiv, sehr sparsam | Series 7 ✓ |
| `CMBatchedSensorManager` | ja | Batches, aber aktive Session | nur Series 9 / Ultra 2+ |

Apple-Doc-Beleg (`developer.apple.com/documentation/coremotion/cmsensorrecorder`):
die Klasse exponiert ausschließlich `recordAccelerometer(forDuration:)` /
`accelerometerData(from:to:)` → `CMRecordedAccelerometerData`; **kein** Symbol für
Gyroskop, `rotationRate` oder `deviceMotion`. watchOS 2.0+, weiterhin supported.

## Methode

Gepaarte Ablation nach dem Muster von `train_loso --drop-gravity`: **dieselben
Sessions, dieselben 15 Folds, dieselbe Per-Session-Z-Score-Normalisierung** — einziger
Unterschied ist, ob die 41 Gyro-Features (`rx/ry/rz`-Achsen + `gyro_mag*` +
Gyro-Korrelationen) im Feature-Set sind. Differenzen damit gepaart per Wilcoxon
testbar. Legacy-Pool, N=15, post-Capture-Clock-Fix, kausale Burst-Metriken.
Treiber: `scripts/ml/acc_only_loso.py`.

**Optimistische Obergrenze.** Die acc-only-Arm behält die `userAcceleration`-Features.
Der reale `CMSensorRecorder` liefert *rohe Gesamt-Beschleunigung* (inkl. Schwerkraft),
nicht die fusions-bereinigte `userAcceleration` — und die Schwerkraft-Trennung braucht
selbst das Gyroskop. Diese Zahl ist daher zunächst eine Obergrenze; der Roh-vs-Linear-
Accel-Abschlag wird unten separat rekonstruiert und gemessen (Ergebnis: ≈ 0).

## Ergebnis (N=15, gepaart)

| Skala | Full IMU (88) | Acc-only (47) | Δ (full−acc) | Wilcoxon |
|---|---|---|---|---|
| **@1s** acc | 0.874 ± 0.035 | 0.855 ± 0.043 | +0.019 (median +0.014) | p=0.0026 ✓ |
| @1s ROC-AUC | 0.950 | 0.932 | +0.017 | p=0.0001 ✓ (15/15) |
| @5s acc | 0.861 | 0.855 | +0.006 | — |
| @10s acc | 0.826 | 0.820 | +0.006 | — |
| **@30s** acc | 0.772 | 0.765 | +0.008 (median +0.005) | p=0.0103 ✓ |

Per-Fold @1s (größte Verlierer ohne Gyro zuerst): P17 −5.2 pp, P01 −4.8, P07 −4.4,
P08 −4.0, P14 −3.5; indifferent / leicht besser: P09 +0.3, P02 +0.2, P15 +0.1.
Output: `models/acc_only_full_imu_cv.csv`, `models/acc_only_cv.csv`.

## HMM-Filter-Stufe (der Live-Entscheidungspfad)

Der Live-Tracker entscheidet die Schreibzeit nicht auf der rohen 1-s-Proba, sondern
auf dem kausalen HMM-Forward-Filter (`OnlineForwardFilter`). Der relevante Vergleich
ist daher *unter dem HMM*: beide Arme durch denselben leakage-freien Per-Person-Filter
(Übergänge + Prior nur aus Train-Personen, `proba_cal` als Emission).

| | roh @1s | + HMM (Live-Pfad) | HMM-Gewinn |
|---|---|---|---|
| **full-IMU** | 0.874 | **0.902 ± 0.037** | +2.8 pp |
| **acc-only** | 0.855 | **0.893 ± 0.040** | +3.5 pp |
| Gyro-Lücke (full−acc) | +0.019 (p=0.003) | **+0.011 (p=0.008)** | schrumpft, bleibt sig. |

- **Der HMM schließt die Gyro-Lücke nicht ganz:** von ~1.9 pp roh auf ~1.1 pp unter
  HMM (acc p=0.008; AUC +0.0095, 15/15 Folds, p=0.0001). Die Lücke bleibt signifikant
  → das Gyro trägt **ein kleines echtes Signal**, nicht bloß 1-s-Rauschen (sonst hätte
  die Glättung es komplett gelöscht).
- **Aber acc-only + HMM (0.893) schlägt full-IMU roh@1s (0.874)** um +1.7 pp, 14/15
  Folds (p=0.0006). Der billige Post-Filter ist *mehr wert als das Gyro*: wer den HMM
  ohnehin deployt, landet mit Accelerometer-allein über dem vollen Roh-Modell.
Output: `models/acc_only_{hmm,full_imu_hmm}_cv.csv`.

## Roh-Accel-Rekonstruktion (der Obergrenze-Vorbehalt, gemessen)

Die obige Ablation behält `userAcceleration`-Features; `CMSensorRecorder` liefert aber
*rohe Gesamt-Beschleunigung* (inkl. Schwerkraft). Dieser Abschlag ist **ohne neue
Aufnahmen** messbar: die Modern-Sessions (P12–P15, P17) haben userAccel UND gravity
separat → `roh = userAccel + gravity` rekonstruierbar. Gepaart auf denselben N=5
Probanden, identisches 47-Feature-Set, einziger Unterschied ist die Accel-Quelle
(`scripts/ml/passive_raw_accel_loso.py`).

| acc-only (47 Features) | @1s | + HMM (Live) |
|---|---|---|
| linear (userAccel) | 0.820 | 0.850 |
| roh (total accel = echtes `CMSensorRecorder`-Signal) | 0.818 | 0.851 |
| Δ (linear − roh) | −0.002 (p=1.0 n.s.) | −0.015 (p=1.0 n.s.) |

**Der Abschlag ist nicht messbar — praktisch null** (am HMM-Pegel ist roh sogar marginal
höher, aber Rauschen). Grund: die Schwerkraft ist innerhalb eines 1-s-Fensters quasi
konstant, und die Features sind überwiegend dynamisch/mean-invariant (std, jerk, FFT mit
entferntem DC-Bin, ZCR, Korrelationen); die wenigen offset-sensitiven (mean/min/max/rms)
re-zentriert der Per-Session-Z-Score. Caveat: N=5, gepaarter Wilcoxon unterpowert
(min p=0.0625) → corroborating, nicht confirming — aber der *Punktschätzer* ist ~0, nicht
nur „nicht detektierbar". Damit ist die acc-only-Zahl **keine optimistische Obergrenze
mehr, sondern eine realistische Schätzung** des Passiv-Pfads. Output:
`models/passive_{raw_accel,raw_accel_hmm,linear_accel}_cv.csv`.

## Verdikt

Das Gyroskop trägt **messbar, aber nicht tragend** bei. Drei Punkte:

1. **Klein und skalen-schrumpfend.** @1s kostet acc-only ~1.9 pp; auf der für einen
   Schreib*zeit*-Tracker relevanten @30-s-Skala nur noch **+0.5 pp Median**. Das Gyro
   entrauscht primär das 1-s-Zappeln — genau das, was Burst-Aggregation / HMM-Glättung
   ohnehin erledigen. Auf Tracker-Ebene ist es nahezu redundant.
2. **0.855 acc-only ist ein brauchbares Modell** — identisch zur 14-Personen-Full-IMU-
   Headline vor dem Capture-Clock-Fix. Cross-subject, fremde Person, nur Accelerometer.
3. **Statistisch robust, praktisch klein.** Alle drei Skalen signifikant (real), aber
   die @30-s-Effektgröße ist <1 pp — kein Einbruch.

**Deployment-Konsequenz.** Ein passiver Ganztags-Tracker via `CMSensorRecorder` ist
**grundsätzlich tragbar**, sogar auf der vorhandenen Series-7-Hardware. Der ehrliche
Live-Preis ist nicht die rohe @1-s-Zahl, sondern der HMM-geglättete Entscheidungspfad:
**acc-only+HMM 0.893 vs. full+HMM 0.902 — ~1 pp.** Das Gyro trägt ein kleines, reales
Restsignal (die Lücke bleibt unter dem HMM signifikant), ist aber kein Generalisierungs-
Faktor: acc-only+HMM liegt sogar *über* dem vollen Roh-Modell. Der Roh-Accel-Abschlag
(das echte `CMSensorRecorder`-Signal vs. userAcceleration) wurde rekonstruiert gemessen
und ist **≈ 0** (s.o.) — die acc-only-Zahl ist damit eine realistische, keine optimistische
Schätzung des Passiv-Pfads. Der Gegenpol bleibt die aktive Workout-Session: volle IMU,
+1 pp, echter Akku-Preis.
Die Wahl ist damit ein bezifferter ~1-pp-Genauigkeit-gegen-Batterie-Tradeoff, keine
Architektur-Sackgasse.

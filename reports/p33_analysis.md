# P33 (S062): Warum der schwächste LOSO-Fold — Root-Cause-Analyse

**Ergebnis:** P33 ist ein **extremer Soft-Writer + Think-Pauser** (sekundär: Keyboard-
Confusion). Sein leichtes/pausiertes Schreiben erzeugt am 6-Kanal-Wrist-IMU genuin zu
wenig Bewegung, sodass das auf festeren Schreibern trainierte Modell es als *idle*
liest. **Kein Bug, kein Alignment-Fehler, kein Datenproblem** — die Signal-Decke,
personifiziert.

Kontext: P33/S062 ist der schwächste Fold der N=22-RF-LOSO-Headline (**acc 0.678**),
11 pp unter dem nächstschwächsten (P31 0.792). Analyse auf dem N=22-Legacy-OOF des
lokalen Refresh-Laufs + Markern `data/raw/markers/S062_markers.csv`.
**Quellen-Korrektur (2026-07-07):** das kanonische `models/loso_oof_legacy.csv` ist
weiterhin N=20 **ohne P33** — das hier analysierte N=22-OOF wurde nicht dauerhaft
gespeichert. Die Zahl ist unabhängig repliziert (§6); für exakte Reproduktion den
N=22-Legacy-LOSO neu rechnen (`--pool legacy --save-oof`).

## 1. Fehlerprofil (3035 Fenster, writing-Anteil 0.408)

- acc 0.676 | TP 717 · FP 463 · TN 1334 · FN 521
- **FPR (idle→writing) 0.258** UND **FNR (writing→idle) 0.421** — *beide* Richtungen
  kaputt.
- mean-proba bei echten Schreib-Fenstern nur **0.575** (kaum über der Schwelle).

Beide Richtungen kaputt + schwache Schreib-Proba wäre konsistent mit einem
Label-/Alignment-Versatz — deshalb der interne Kontrollversuch unten.

## 2. Per-Task-Aufschlüsselung (Marker-getaggt)

| Task | n | acc | meanP | Fehler |
|---|---|---|---|---|
| **free_writing** (fest) | 308 | **0.808** | 0.837 | FNR 0.12 |
| abschreiben | 365 | 0.622 | 0.730 | FNR 0.24 |
| think_pause_writing | 392 | 0.464 | 0.598 | FNR 0.45 |
| math (sparse) | 458 | 0.524 | 0.424 | FNR 0.57 |
| **soft_writing** (leicht) | 272 | **0.382** | 0.318 | **FNR 0.76** |
| keyboard_typing | 238 | 0.571 | 0.440 | FPR 0.43 |
| phone_typing / scrolling / gesturing / pause | | 0.95–1.0 | | FPR ~0 |

**Interner Kontrollversuch — Alignment falsifiziert:** `free_writing` wird sauber
erkannt (0.808), `soft_writing` zu 76 % verpasst — *dieselbe Session, dasselbe δ*. Ein
falsches δ würde free_writing genauso brechen. Also stimmen die Labels; der Unterschied
ist der **Schreibstil**, nicht das Alignment. (`alignment_sigma = -2.81` ist schwach,
aber hier irrelevant.)

## 3. Kohorten-Vergleich — P33 ist der Ausreißer

Per Writing-Task, FNR der übrigen Kohorte vs. P33:

| Task | Kohorte FNR | P33 FNR | Faktor |
|---|---|---|---|
| free_writing | 0.101 | 0.115 | **1.1× (normal)** |
| abschreiben | 0.159 | 0.239 | 1.5× |
| soft_writing | 0.250 | 0.760 | **3.0×** |
| math | 0.194 | 0.568 | 2.9× |
| think_pause_writing | 0.087 | 0.455 | **5.2×** |

Gepoolt über alle Schreib-Tasks hat P33 die **höchste Writing-FNR der Kohorte (0.390)**;
nächste: P15 0.257, P31 0.203, P03 0.201, P09 0.187.

P33 ist also auf *festem* Schreiben normal, aber auf *leichtem/pausiertem* Schreiben 3–5×
schlechter als alle anderen — die dokumentierten P09- (Soft-Writer) und P07-
(Think-Pauser) Failure-Modi in Extremform, plus P17-Keyboard-Confusion (FPR 0.43).

## 4. Ausgeschlossen

- **Alignment/δ** — interner Kontrollversuch (free_writing sauber).
- **Daten-Qualität** — keine `issue_codes`, watch_samples 151.800, Label-Balance normal,
  Pipeline funktioniert (free_writing 0.81).
- **Reine Keyboard-Confusion** — trägt bei (FPR 0.43), ist aber sekundär; Haupttreiber ist
  die Writing-FNR.

## 5. Aktionable Schlüsse

1. **Nicht code-fixbar** — die Info fehlt im Signal (leichtes Schreiben = kaum
   Wrist-Bewegung). Per-Subject-Threshold half schon P09 nicht (`reports/per_subject_threshold.md`).
2. **Hebel „native Rate + Gravity" — getestet, rettet nicht (2026-07-07):** der
   Modern-Pool-RF (N=13, nativ 100 Hz + 9ch, `models/loso_oof_modern_pooled.csv`)
   gibt P33 **acc 0.686** vs. 0.676 @50 Hz-6ch — +1 pp, nicht streng gepaart
   (N=13- statt N=21-Trainingskohorte). Die Information fehlt am Handgelenk,
   nicht in der Abtastrate.
3. **Sonst:** mehr extreme-Soft-Writer-Trainingsdaten — aber P33 als Ausreißer *unter* den
   Soft-Writern deutet auf den physischen Sensor-Floor.

## 6. Nachtrag 2026-07-07 — vierfache Replikation + modellfreie Kinematik

Die 0.678 ist über Modellfamilien, Sample-Raten und Merge-Pfade hinweg stabil —
in jedem Lauf ist S062 der (zweit-)schwächste Fold:

| Lauf | Basis | P33/S062 acc |
|---|---|---|
| RF Legacy N=22 (dieser Report) | 50-Hz-View, 88 Features | 0.676 |
| RF Modern N=13 (`loso_oof_modern_pooled.csv`) | nativ 100 Hz + Gravity, eigener Merge | 0.686 |
| tcn6 (`deep_deep_fusion_tcn6_tcn_gru_oof.csv`) | rohe Sequenzen | 0.676 |
| tcn_gru / Proba-Ensemble | rohe Sequenzen | 0.662 / 0.669 |

Der Modern-Lauf nutzt `S062_merged.csv` (nativer Merge-Pfad), nicht die decimierte
Legacy-View — ein View-Defekt ist damit als gemeinsame Ursache ausgeschlossen.

**Modellfreie Kinematik** (Median über label=1-Fenster, 9 v2-Sessions mit soft_writing):

| | P33 (S062) | Kohorte (übrige 8) |
|---|---|---|
| soft_writing `gyro_mag_std` | **0.090** (Minimum) | 0.17–0.30 |
| soft_writing `acc_mag_std` | **0.023** (Minimum) | 0.031–0.060 |
| soft_writing / eigene Pause | **1.36×** | z. B. P34 5.36×, P29 3.81× |
| free_writing `gyro_mag_std` | **0.240** (Minimum) | 0.31–0.47 |

P33s leichtes Schreiben liegt nur 36 % über seinem eigenen Pause-Level. Der
per-Session-Z-Score kann das nicht retten: er normiert die absolute Skala, aber der
fehlende *relative* Kontrast Schreiben↔Ruhe ist intrinsisch. Sein `keyboard_typing`
(gyro 0.225, Jerk 2.56) ist kinematisch von seinem `abschreiben` (0.164, 2.03) kaum
unterscheidbar → Keyboard-FPR 0.43. Nuance: P27 (S056) hat ähnlich schwaches
soft_writing (gyro 0.085), scored aber 0.871 — bei ihm ist nur diese eine Task
betroffen, bei P33 drei (soft, math, think_pause) plus die Keyboard-Verwechslung.

**Reproduktion:** `scripts/ml/marker_fpr.py`-Bausteine (`parse_task_blocks`/`assign_task`)
auf einem N=22-Legacy-OOF gefiltert auf `person_id == "P33"`; Modern-Vergleich auf
`models/loso_oof_modern_pooled.csv`; Kinematik direkt aus
`data/processed/windows/50hz/*_windows.csv` + Marker-CSVs.

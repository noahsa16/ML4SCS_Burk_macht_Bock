# P33 (S062): Warum der schwächste LOSO-Fold — Root-Cause-Analyse

**Ergebnis:** P33 ist ein **extremer Soft-Writer + Think-Pauser** (sekundär: Keyboard-
Confusion). Sein leichtes/pausiertes Schreiben erzeugt am 6-Kanal-Wrist-IMU genuin zu
wenig Bewegung, sodass das auf festeren Schreibern trainierte Modell es als *idle*
liest. **Kein Bug, kein Alignment-Fehler, kein Datenproblem** — die Signal-Decke,
personifiziert.

Kontext: P33/S062 ist der schwächste Fold der N=22-RF-LOSO-Headline (**acc 0.678**),
11 pp unter dem nächstschwächsten (P31 0.792). Analyse auf `models/loso_oof_legacy.csv`
(N=22) + Markern `data/raw/markers/S062_markers.csv`.

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
2. **Offener technischer Hebel:** P33 ist nativ **100 Hz + Gravity**, der RF lief aber auf
   der 50-Hz-Legacy-View (downgesampled → feine Soft-Writing-Bewegung könnte wegfallen).
   Der direkte Test ist **P33 @50 Hz-6ch vs. @100 Hz-9ch** (Modern-Gravity-Läufe) — ob
   native Rate + Schwerkraft das schwache Signal retten.
3. **Sonst:** mehr extreme-Soft-Writer-Trainingsdaten — aber P33 als Ausreißer *unter* den
   Soft-Writern deutet auf den physischen Sensor-Floor.

**Reproduktion:** `scripts/ml/marker_fpr.py`-Bausteine (`parse_task_blocks`/`assign_task`)
auf `models/loso_oof_legacy.csv` gefiltert auf `person_id == "P33"`.

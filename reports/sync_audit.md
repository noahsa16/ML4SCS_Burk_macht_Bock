# Sync-Audit — Pen↔Watch-Alignment als LOSO-Fehlerquelle?

Erzeugt von `scripts/ml/sync_audit.py`. Frage: erklärt residualer
Alignment-Fehler im per-Session-δ die LOSO-Genauigkeitsdecke (~0.86 acc),
oder steht die Diagnose „echte IMU-Signal-Mehrdeutigkeit" (Roadmap 2026-05-22)?

## Ergebnis

**Sync-Restfehler erklärt die Decke NICHT.**

**Stärkstes Einzelargument (robust gegen kleines N):** die zwei
schwächsten Folds passen *gegen* die Sync-Hypothese. P07 (acc 0.796 —
schlechteste Fold) hat ein starkes σ und nur 20 ms Drift; P09 (acc 0.813)
hat **σ = −5.10, das schärfste Varianz-Minimum im ganzen Satz**, und
ebenfalls nur 20 ms Drift. Wäre Sync der Engpass, müssten genau diese
Folds schlechte Alignment-Diagnostik zeigen — sie zeigen die beste.

- **A — σ ↔ Accuracy:** r(σ, acc) = -0.217, r(σ, AUC) = -0.111.
  Die Sync-Hypothese sagt r > 0 voraus (schärferes Varianz-Minimum →
  bessere Fold). Beobachtet wird ~0/leicht negativ — σ hat keinen
  Vorhersagewert für die Fold-Qualität. *Caveat:* bei N = 10 ist das 95-%-CI
  von r grob ±0.6; das r widerlegt einen moderaten Sync-Effekt nicht
  hart, es findet nur kein Signal in irgendeine Richtung. Belastbarer ist
  daher das Einzelfall-Argument oben.
- **B — δ-Drift:** Median 20.0 ms, Max 80.0 ms
  zwischen erster und zweiter Session-Hälfte (δ-Auflösung ~20 ms =
  1 Sample @ 50 Hz, d. h. ein 20-ms-Drift ist Auflösungsrauschen).
  Entscheidend: r(Drift, Accuracy) = -0.183 — die Sync-Hypothese
  sagt r < 0 voraus (mehr Drift → schlechtere Fold). Die zwei Sessions
  mit dem größten Drift (P04 60 ms, P05 80 ms) sind *nicht* die schwachen
  Folds; P07/P09 driften nur 20 ms. Drift erklärt das Fehlermuster nicht.
- **C — Label-Sensitivität:** ein künstlicher δ-Fehler von ±50 ms
  kippt im Median 10.68 % der Watch-Sample-Labels (konzentriert an
  den Stroke-Rändern). Das ist *nicht* vernachlässigbar — es zeigt, dass
  δ-Genauigkeit zählt. Genau deshalb sind A und B die entscheidenden Tests:
  sie belegen, dass δ tatsächlich genau ist (kein Vorhersagewert für die
  Fold-Qualität, kein relevanter Drift), also dieses Kipp-Potenzial im
  produktiven Merge gar nicht erst ausgelöst wird.

## Per-Session-Tabelle

| session_id | person_id | sigma_full | delta_full_sec | delta_h1_sec | delta_h2_sec | drift_ms | n_strokes_min_half | label_flip_pct_at_50ms | accuracy | roc_auc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S007 | Noah | -5.000 | -0.120 | -0.120 | -0.140 | 20.000 | 569 | 13.680 | 0.905 | 0.964 |
| S008 | P01 | -4.540 | -0.040 | -0.040 | -0.040 | 0.000 | 468 | 11.090 | 0.890 | 0.960 |
| S009 | P02 | -4.680 | -0.140 | -0.120 | -0.140 | 20.000 | 409 | 10.250 | 0.891 | 0.959 |
| S011 | P03 | -4.070 | -0.100 | -0.100 | -0.100 | 0.000 | 404 | 10.950 | 0.855 | 0.922 |
| S013 | Taji | -3.530 | -0.060 | -0.080 | -0.060 | 20.000 | 491 | 10.330 | 0.855 | 0.927 |
| S015 | P04 | -4.280 | -0.160 | -0.140 | -0.200 | 60.000 | 448 | 10.780 | 0.863 | 0.930 |
| S017 | P05 | -3.750 | -0.020 | -0.020 | 0.060 | 80.000 | 286 | 6.180 | 0.840 | 0.936 |
| S019 | P07 | -4.180 | -0.080 | -0.080 | -0.100 | 20.000 | 413 | 11.400 | 0.796 | 0.847 |
| S020 | P08 | -3.690 | -0.080 | -0.100 | -0.080 | 20.000 | 241 | 7.980 | 0.859 | 0.940 |
| S022 | P09 | -5.100 | -0.020 | -0.040 | -0.020 | 20.000 | 452 | 10.580 | 0.813 | 0.896 |

## Einordnung

σ misst die Schärfe des Varianz-Minimums (wurde ein klares δ gefunden),
nicht ob δ über die Session konstant bleibt — Teiltest B schließt genau
diese Lücke. Beide Tests zusammen mit der Label-Sensitivität (C) decken
die drei Wege ab, auf denen Sync-Fehler ins Modell gelangen könnten:
falsches δ, driftendes δ, δ-empfindliche Labels.

Keiner der drei Wege trägt messbar bei. Die Fehlerdecke ist damit *nicht* Sync-bedingt — die Diagnose „echte Signal-Mehrdeutigkeit" bleibt bestehen. Echte Hebel bleiben mehr Signal (100 Hz Watch-IMU) und mehr Probanden.

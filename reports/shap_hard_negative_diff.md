# SHAP-Diff: P17-Schreiben (TP) vs P17-Tippen (FP)

Held-out P17, RF trainiert auf allen anderen 19 Personen (legacy-Pool, identische 88 Features + Per-Session-Z-Score wie die Headline).

- Group A (P17 writing, korrekt erkannt): n=300
- Group B (P17 keyboard/phone, faelschlich 'writing', FP): n=292
- **Korrelation SHAP(A,B) ueber alle 88 Features: r=0.633**

## Top 15 Features (mean SHAP, Richtung writing)

| Feature | A: P17 writing | B: P17 typing-FP | Diff |
|---|---|---|---|
| ay_jerk_mean_abs | +0.0171 | +0.0200 | -0.0030 |
| rz_zcr | +0.0162 | +0.0200 | -0.0038 |
| rz_band_3_8 | +0.0194 | +0.0197 | -0.0003 |
| rz_spec_centroid | +0.0160 | +0.0187 | -0.0027 |
| rx_band_3_8 | +0.0175 | -0.0062 | +0.0237 |
| ay_jerk_std | +0.0157 | +0.0165 | -0.0008 |
| gyro_mag_jerk_mean_abs | +0.0127 | -0.0159 | +0.0286 |
| acc_mag_jerk_mean_abs | +0.0150 | +0.0140 | +0.0010 |
| ry_band_3_8 | +0.0144 | +0.0125 | +0.0019 |
| ay_std | +0.0131 | +0.0112 | +0.0019 |
| acc_mag_jerk_std | +0.0126 | +0.0086 | +0.0040 |
| rz_dom_freq | +0.0114 | +0.0101 | +0.0013 |
| ay_max | +0.0105 | +0.0080 | +0.0025 |
| az_mean | +0.0099 | +0.0059 | +0.0041 |
| ay_rms | +0.0096 | +0.0081 | +0.0016 |

## Lesart

Hohe Korrelation (r>0.7) + gleiche Top-Treiber = die 88 Features sehen P17s Tippen als *feature-aequivalent* zu P17s eigenem Schreiben — Stil-Hypothese, kein Feature-Fix, Hebel ist mehr Trainingsvielfalt. Niedrige Korrelation / abweichende Treiber = eher eine knappe Decision-Boundary, potenziell per Kalibrierung/mehr Daten schaerfbar.

Abbildung: `reports/figures/shap_hard_negative_diff_P17.png`

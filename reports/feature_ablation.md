# Feature-Ablation 2026-05-29

Hypothesen: #3 `gyro_acc_energy_ratio` (Rotation-Dominanz), #4 `tilt_*_std` (Orientierungs-Stabilität). Entscheidung: behalten nur bei acc/AUC↑ UND fold-σ nicht schlechter.

## #3 `gyro_acc_energy_ratio` — N=10 Legacy-LOSO

- ohne #3 (88 feat): : acc 0.863 ± 0.032 | AUC 0.935 ± 0.032 | F1w 0.875
    burst: @5s AUC 0.968  @10s AUC 0.957  @30s AUC 0.922
- mit  #3 (89 feat): : acc 0.863 ± 0.031 | AUC 0.935 ± 0.032 | F1w 0.875
    burst: @5s AUC 0.968  @10s AUC 0.957  @30s AUC 0.923
- **Δacc -0.0006 | ΔAUC +0.0000 | Δσ(acc) -0.0004**

## #4 `tilt_*_std` — within-S038 (vorläufig, eine Person)

- ohne #4 (93 feat): acc 0.787 | AUC 0.837 | F1w 0.602
- mit  #4 (96 feat): acc 0.776 | AUC 0.843 | F1w 0.582
- Δacc -0.0109 | ΔAUC +0.0064
- Kein LOSO (ein Subjekt, math-Holdout) — nicht beweiskräftig.
- Konsequenz: `tilt_*_std` **verworfen** — die Variabilität der
  Orientierung trägt nichts, das Signal sitzt im Mittel (siehe unten).

## Gravity-Block als Ganzes (88 vs 92) — within-S038, 2026-06-02

Frage des Auftrags: bringt die *neuste* Session (S038/P12, Modern-Pool,
100 Hz + Gravity) mit den 4 Gravity-Features `tilt_x/y/z_mean` +
`tilt_change` höhere Accuracy? Getestet als Block (nicht inkrementell),
within-S038, temporaler 80/20-Split, on-the-fly gebaut (kein Cache).

- 88 feat (ohne Gravity): acc 0.760 | AUC 0.813 | F1w 0.560
- 92 feat (mit Gravity) : acc 0.770 | AUC 0.836 | F1w 0.567
- **Δacc +0.011 | ΔAUC +0.023 | ΔF1w +0.007**

Seed-Robustheit (10 Seeds, gleicher Split):
- **ΔAUC +0.021 ± 0.006 — positiv in 10/10 Seeds** (kein Seed-Rauschen)
- Δacc +0.007 ± 0.007 — positiv in nur 7/10 Seeds (rauscht um 0)

**Lesart:** Der Gravity-Block hebt konsistent das *Ranking* (AUC), bewegt
aber die 0.5-Decision kaum. Signal sitzt in den Orientierungs-*Mitteln*
(`tilt_*_mean` = Wrist-Pose relativ zur Schwerkraft), nicht in der
Variabilität (`tilt_*_std`, siehe #4 oben — verworfen). Physikalisch
plausibel: die Hand-Pose beim Schreiben unterscheidet sich systematisch
von der Ruhepose; deren Jitter nicht.

**Caveat — N=1, nicht generalisierbar.** Within-Session, ein Proband
(P12). 10/10-Seed-Konsistenz schließt nur Seed-Rauschen aus, **nicht**
Probanden-Idiosynkrasie — der Gewinn könnte P12s spezifische Wrist-Pose
in dieser einen Session sein. Ein echter Cross-Subject-Modern-LOSO
braucht ≥2 Modern-Pool-Probanden; aktuell existiert nur S038 (S037 zu
kurz/low-sync, S032/S033 sind 100 Hz *ohne* Gravity). **Vor diesem
zweiten Modern-Probanden ist „Gravity hilft" eine Hypothese, kein
Befund.** 100 Hz selbst ist als Modell-Gain bereits widerlegt
(`reports/100hz_ablation.md`); offen ist allein Gravity.

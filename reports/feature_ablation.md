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

**Caveat — die Absolutzahlen sind durch den Split gedrückt, nicht durch
die Daten.** Die hier berichteten ~0.76–0.77 acc / ~0.56 F1w wirken weit
unter dem LOSO-Headline (0.863 / 0.875), sind aber ein Artefakt des
temporalen 80/20-Splits auf *dieser* Session — **kein** schlechter
Proband und **keine** schlechten Labels (Alignment σ = -4.37, verdict
`usable`). Ursache: P12s Latin-Square-Reihenfolge (subject_index 11) legt
die Tasks als Freies Schreiben → Pause → Abschreiben → Pause → **Mathe
(zuletzt)**. Der 80/20-Schnitt nimmt die letzten 20 % als Test — und die
bestehen zu **363 von 370 Fenstern (98 %) aus dem Mathe-Block**. Dreifacher
Worst Case:

1. **Distribution-Shift** — Train 50 % Writing, Test nur 28 %.
2. **Mathe ist die strukturell härteste Task** (kohortenweit ~40 %
   Writing, lange Denkpausen — vgl. P07s Failure-Mode).
3. **Das Modell sieht Mathe nie im Training** — es lernt auf den
   schreib-dichten Tasks und wird ausschließlich auf der einen
   Sparse-Task getestet. F1(writing) bricht ein, weil die Test-Writing-
   Fenster die mehrdeutigen Mathe-Striche zwischen Denkpausen sind.

Beleg, dass das Signal voll da ist: ein gemischter Stratified-5-Fold auf
derselben Session liefert **acc 0.859 / AUC 0.936 / F1w 0.845** — exakt
in der Liga des Headlines (leakt zwar über den 50 %-Fenster-Overlap, ist
als „ist das Signal da?"-Check aber eindeutig). Konsequenz für die
Gravity-Frage: der **relative** Δ bleibt gültig (beide Arme teilen den
math-lastigen Test), nur die Absolutzahlen sind nicht mit LOSO
vergleichbar. Sauber gemessen werden die Absolutwerte erst mit einem
zweiten Modern-Probanden via echtem Modern-LOSO.

## Gravity-Block cross-subject (92 vs 88) — Modern-LOSO N=4, 2026-06-10

Der oben angekündigte Test: gepaartes A/B auf dem Modern-Pool
(P12/S038, P13/S039, P14/S040, P15/S041), identische Sessions, Folds
und Seed (42), per-session Z-Score an. 92-Feature-Arm via
`--pool modern`, 88-Feature-Arm via neuem `--drop-gravity`-Flag
(Session-Auswahl unverändert, nur die 4 Gravity-Spalten gedroppt).
Artefakte: `models/loso_cv_modern.csv` vs.
`models/loso_cv_modern_nogravity.csv`.

| Fold | acc 92 | acc 88 | Δacc (Gravity-Effekt) | AUC 92 | AUC 88 | ΔAUC |
|:---|---:|---:|---:|---:|---:|---:|
| P12 | 0.814 | 0.800 | +0.014 | 0.871 | 0.869 | +0.002 |
| P13 | 0.888 | 0.885 | +0.003 | 0.949 | 0.948 | +0.001 |
| P14 | 0.802 | 0.840 | **−0.038** | 0.906 | 0.919 | **−0.013** |
| P15 | 0.810 | 0.806 | +0.004 | 0.892 | 0.890 | +0.002 |
| **Mean** | 0.828 ± 0.035 | 0.833 ± 0.034 | **−0.005** | 0.904 ± 0.028 | 0.907 ± 0.030 | **−0.003** |

Auf den Burst-Skalen dasselbe Bild: @5s acc 0.874 vs. 0.884,
@30s AUC 0.901 vs. 0.908 — der 88-Arm liegt überall gleichauf oder
vorn.

**Verdikt: die Within-Session-Hypothese überträgt sich nicht
cross-subject.** Der innerhalb von S038 robuste AUC-Gewinn (+0.021,
10/10 Seeds) schrumpft im LOSO auf ~+0.002 für 3 von 4 Folds — und
kippt für P14 in einen klaren Verlust (−3.8 pp acc, −1.3 pp AUC).
Genau das war das angekündigte Risiko: `tilt_*_mean` kodiert die
Wrist-Pose, und die ist **probanden-spezifisch**. Mit nur 3
Trainings-Probanden pro Fold lernt der RF Pose-Grenzen, die für einen
Probanden mit abweichender Schreibhaltung (P14) negativ transferieren.
Per-Session-Z-Score entfernt nur den absoluten Pose-Offset, nicht die
nicht-übertragbare relative Struktur.

Nach der Entscheidungsregel dieses Reports (behalten nur bei acc/AUC↑
UND σ nicht schlechter): **Gravity-Block nicht ins
Cross-Subject-Feature-Set.** Differenziertes Fazit fürs Projekt:

1. **Cross-subject (rf_all_modern-Linie):** kein Gewinn bei N=4, eher
   Schaden durch Pose-Idiosynkrasie. Re-Evaluation lohnt erst ab
   N≥6 Modern-Probanden.
2. **Within-subject (Personal-Modell-Linie, rf_noah):** der
   Within-Session-Befund bleibt gültig — Gravity ist ein
   *Personalisierungs*-Signal. Für ein persönliches Focus-Tracker-
   Modell auf 9-Kanal-Daten ist der Block weiterhin Kandidat.
3. **Capture unverändert weiterführen:** der Kanal kostet nichts,
   ist nicht retro-imputierbar, und Punkt 1 ist mit mehr Probanden
   revidierbar.

Damit ist der letzte offene Modell-Hebel der Roadmap getestet:
Sync ✗, 100 Hz ✗, Per-Subject-Threshold ✗, Deep ≈ RF, engineered
Features ✗, **Gravity cross-subject ✗ (within-subject ✓)**. Die
Decke bleibt Signal-Mehrdeutigkeit + Probandenzahl.

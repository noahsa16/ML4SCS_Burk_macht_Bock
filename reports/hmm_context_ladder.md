# HMM-Post-Processing — Kontext-Leiter & 2x2-Faktordesign

Frage: Der HMM-Gewinn auf dem RF (siehe `hmm_postprocess.md`) — haengt er an der **Modellfamilie** (RF schwach, Deep stark) oder am **Zeitkontext** (Fenstergroesse) des Basismodells? Test: derselbe kausale HMM-Forward-Filter ueber die per-window-OOF mehrerer Basismodelle, je gemessen gegen den **eigenen Floor** + Shuffle-Negativkontrolle. Alle Sprossen leakage-frei (Transition + Prior nur aus Train-Personen).

## Die Leiter (aufsteigender Zeitkontext)

| Basismodell | Familie | Fenster | Floor acc | HMM acc | Δacc | p | Neg.-Kontrolle |
|---|---|---|---|---|---|---|---|
| RF-1s | RF | 1s | 0.881 | 0.905 | **+0.0243** | 0.0001 (sig) | 0.500 |
| RF-5s | RF | 5s | 0.887 | 0.879 | **-0.0076** | 0.0131 (sig) | 0.518 |
| harnet-5s | Deep | 5s | 0.896 | 0.885 | **-0.0101** | 0.0735 (n.s.) | 0.508 |
| TCN-1s | Deep | 1s | 0.895 | 0.905 | **+0.0101** | 0.0054 (sig) | 0.524 |
| TCN-5s | Deep | 5s | 0.911 | 0.902 | **-0.0089** | 0.0004 (sig) | 0.517 |

(*harnet-5s ist N=14, pre-Capture-Clock-Fix — andere Daten-Aera, daher korroborierend, nicht Teil des sauberen 2x2.)

## 2x2-Faktordesign (Δacc HMM − Floor)

| | 1-s-Fenster | 5-s-Fenster |
|---|---|---|
| **RF** | +0.0243 (hilft) | -0.0076 (schadet) |
| **Deep / TCN** | +0.0101 (hilft) | -0.0089 (schadet) |

## Verdikt

**Die Fenstergroesse (= Zeitkontext) ist der kausale Faktor, nicht die Modellfamilie.** Beide Familien kippen helps->hurts allein mit der Fenstergroesse; das HMM hilft *ausschliesslich* den gedaechtnislosen 1-s-Modellen (RF-1s **und** TCN-1s). Sobald das Basismodell ~5 s Kontext traegt — ob durch breitere RF-Features, harnet oder den TCN —, ist nichts mehr nachzuruesten, und die ~16-21 s HMM-Klebrigkeit **ueberglaettet** echte Uebergaenge leicht (derselbe Mechanismus, der Burst@10/30s schaden laesst).

**Nuance:** Die Fenstergroesse bestimmt das *Vorzeichen*, die Modellqualitaet moduliert die *Magnitude* — TCN-1s gewinnt nur +1,0 pp vs. RF-1s +2,4 pp, weil sein hoeherer Floor schon weniger Flackern hat. Beide 1-s-Modelle konvergieren post-HMM auf ~0.905.

**Konsequenz (eine Decke, mehrere Strassen):** Den Zeit-Struktur-Gewinn kann man **post-hoc** (HMM auf 1-s-Modell) *oder* **nativ** (breites Fenster / Deep-5s) einsammeln — nie beides, weil es derselbe Gewinn ist (RF-1s+HMM 0.905, TCN-1s+HMM 0.905, nativer TCN-5s 0.911). Deployment: HMM gehoert auf den 1-s-RF, **nicht** auf den 5-s-RF oder den TCN.

**Negativkontrolle:** In jeder Sprosse kollabiert der Filter mit in-session geshuffelter Emission auf ~Zufall (0.50-0.52) — der Effekt ist ueberall signalgetrieben, keine Block-Erkennungs-Inflation.

## Reproduktion

Die fluechtigen OOFs (Deep + RF-5s) zuerst erzeugen, dann dieses Skript:

```bash
python -m src.training.train_loso --pool legacy --window-sec 5 --save-oof /tmp/rf5_oof.csv
python -m src.training.deep --model tcn --pool legacy --win 1 --run-dir /tmp/tcn1_oof
python -m src.training.deep --model tcn --pool legacy --win 5 --run-dir /tmp/tcn5_oof
# harnet-5s OOF: models/harnet_oof_harnet5.csv (aus scripts/ml/harnet_rf_fusion.py)
python scripts/ml/hmm_cross_model.py
```
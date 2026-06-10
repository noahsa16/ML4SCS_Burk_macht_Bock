"""CLI: Transfer-Learning-Vergleich mit dem Oxford harnet-Foundation-Model.

::

    python -m src.training.deep.harnet                      # harnet5, frozen
    python -m src.training.deep.harnet --model harnet10
    python -m src.training.deep.harnet --force-embeddings   # Cache ignorieren

Frozen feature extractor (Stufe 1): harnet-Conv-Trunk liefert Embeddings,
darauf LOSO-by-person mit LogReg (C-Sweep) + RF. Schreibt die per-fold
Metriken nach ``models/harnet_loso.csv`` und einen Report nach
``reports/harnet_transfer.md`` (Setup, Einheiten-Limitation, Ergebnis).

Vergleich auf gleicher Decision-Skala: harnet5-Fenster sind nativ 5 s, also
ist die per-window-Metrik die 5-s-Entscheidung — verglichen mit der
RF-Headline @5s (acc 0.899 / AUC 0.962, N=14). harnet10 ist nativ 10 s
(-> RF@10s).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.training.deep.harnet_data import HARNET_VARIANTS
from src.training.deep.harnet_frozen import harnet_loso

ROOT = Path(__file__).parents[3]
MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"

# RF-Headline-Decision-Windows (acc, AUC), N=14, LOSO-by-person (CLAUDE.md).
RF_HEADLINE: dict[str, tuple[float, float]] = {
    "1s": (0.855, 0.929),
    "5s": (0.899, 0.962),
    "10s": (0.882, 0.952),
    "30s": (0.838, 0.917),
}
# harnet-Fensterlaenge -> native Decision-Skala fuer den Headline-Vergleich.
NATIVE_SCALE: dict[str, str] = {"harnet5": "5s", "harnet10": "10s"}
BURST_SCALES = ("5s", "10s", "30s")


def _summarise(df: pd.DataFrame) -> dict[str, dict[str, tuple[float, float]]]:
    """Pro Head: Mean±Std von per-window acc/auc + Burst-Skalen.

    Returns ``{head: {"window": (acc, auc), "acc_std": ..., "5s": (acc,auc), ...}}``.
    """
    out: dict[str, dict] = {}
    for head, g in df.groupby("head"):
        out[head] = {
            "window": (g["accuracy"].mean(), g["roc_auc"].mean()),
            "window_std": (g["accuracy"].std(), g["roc_auc"].std()),
            "f1": g["f1_writing"].mean(),
            "n_folds": len(g),
        }
        for s in BURST_SCALES:
            out[head][s] = (g[f"acc_{s}"].mean(), g[f"auc_{s}"].mean())
    return out


def _print_tables(variant: str, summary: dict) -> None:
    native = NATIVE_SCALE[variant]
    rf_native = RF_HEADLINE[native]
    print(f"\n=== {variant} frozen — LOSO-by-person (Mean ueber Folds) ===")
    print(f"per-window = native {native}-Entscheidung; Vergleich RF@{native} "
          f"= {rf_native[0]:.3f}/{rf_native[1]:.3f}\n")
    print(f"{'Head':<10}{'per-window':>16}{'@5s':>16}{'@10s':>16}{'@30s':>16}")
    print(f"{'RF (N=14)':<10}"
          f"{rf_native[0]:>7.3f}/{rf_native[1]:<8.3f}"
          + "".join(f"{RF_HEADLINE[s][0]:>7.3f}/{RF_HEADLINE[s][1]:<8.3f}"
                    for s in BURST_SCALES))
    for head, m in sorted(summary.items()):
        w = m["window"]
        print(f"{head:<10}{w[0]:>7.3f}/{w[1]:<8.3f}"
              + "".join(f"{m[s][0]:>7.3f}/{m[s][1]:<8.3f}" for s in BURST_SCALES))
    print(f"\n(per-window-Std je Head: "
          + ", ".join(f"{h} acc±{m['window_std'][0]:.3f}"
                      for h, m in sorted(summary.items())) + ")")


def _write_report(variant: str, summary: dict, n_folds: int, out_csv: Path) -> Path:
    native = NATIVE_SCALE[variant]
    rf = RF_HEADLINE[native]
    win = HARNET_VARIANTS[variant]
    best_head = max(summary, key=lambda h: summary[h]["window"][1])
    bw = summary[best_head]["window"]
    delta_acc = bw[0] - rf[0]
    delta_auc = bw[1] - rf[1]
    if delta_auc > 0.005:
        verdict = "schlaegt die RF-Headline"
    elif abs(delta_auc) <= 0.005:
        verdict = "liegt gleichauf mit der RF-Headline"
    else:
        verdict = "bleibt unter der RF-Headline"

    lines = [
        f"# Transfer-Learning: Oxford ssl-wearables ({variant}), frozen",
        "",
        "## Setup",
        "",
        f"- **Modell:** `torch.hub.load('OxWearables/ssl-wearables', "
        f"'{variant}', class_num=2, pretrained=True)` — Conv-Trunk als frozen "
        f"feature extractor, vortrainierter Kopf abgeschnitten.",
        f"- **Input:** {win['win_samples']} Samples = "
        f"{win['win_samples'] / 30:.0f} s @ 30 Hz, 3 Accel-Kanaele "
        f"(`ax/ay/az` = userAcceleration), Stride {win['stride_samples'] / 30:.1f} s "
        f"({win['stride_samples']} Samples, 50 % Overlap).",
        "- **Resampling:** Watch 50/100 Hz -> 30 Hz via "
        "`scipy.signal.resample_poly` (50->30 = 3/5, 100->30 = 3/10). "
        "Modern-Sessions werden in einem Schritt 100->30 resampled.",
        "- **Protokoll:** LOSO-by-person, identische Session-Auswahl wie die "
        "RF-Headline (`_select_sessions`, Pool `legacy`, verdict-Gate). "
        f"{n_folds} Folds.",
        "- **Koepfe auf den Embeddings:** LogisticRegression (C-Sweep "
        "{0.01, 0.1, 1}, inneres GroupKFold nach Person) und RandomForest "
        "(200 Trees, `class_weight=balanced`). Embeddings standardisiert "
        "(StandardScaler) fuer LogReg.",
        "",
        "## Einheiten-Limitation (bewusst)",
        "",
        "harnet wurde auf **UK-Biobank-Total-Acceleration** vortrainiert "
        "(inkl. Gravity-Komponente). Unser Input ist `userAcceleration` "
        "**ohne** Gravity, weil der Legacy-Pool keine Gravity-Kanaele hat. "
        "Das ist ein bewusster Distribution-Shift gegenueber dem "
        "Pretraining — die Embeddings sehen ein anderes Signal als die "
        "Biobank-Daten. Kein Per-Session-Z-Score auf den Inputs (das Netz "
        "erwartet g-Einheiten). Ergebnis ist entsprechend eine *untere "
        "Schranke* fuer das, was harnet mit passenderem Input leisten "
        "koennte.",
        "",
        "## Ergebnis",
        "",
        f"Vergleich auf gleicher Decision-Skala: harnet-per-window = native "
        f"{native}, gegen RF-Headline @{native} = {rf[0]:.3f}/{rf[1]:.3f} "
        f"(acc/AUC).",
        "",
        f"| Head | per-window acc/AUC | @5s | @10s | @30s |",
        f"|---|---|---|---|---|",
        f"| **RF (N=14)** | {rf[0]:.3f}/{rf[1]:.3f} | "
        f"{RF_HEADLINE['5s'][0]:.3f}/{RF_HEADLINE['5s'][1]:.3f} | "
        f"{RF_HEADLINE['10s'][0]:.3f}/{RF_HEADLINE['10s'][1]:.3f} | "
        f"{RF_HEADLINE['30s'][0]:.3f}/{RF_HEADLINE['30s'][1]:.3f} |",
    ]
    for head, m in sorted(summary.items()):
        w = m["window"]
        lines.append(
            f"| {head} | {w[0]:.3f}/{w[1]:.3f} | "
            f"{m['5s'][0]:.3f}/{m['5s'][1]:.3f} | "
            f"{m['10s'][0]:.3f}/{m['10s'][1]:.3f} | "
            f"{m['30s'][0]:.3f}/{m['30s'][1]:.3f} |"
        )
    lines += [
        "",
        f"**Verdikt:** Der staerkere Kopf (`{best_head}`) {verdict} auf der "
        f"nativen Skala (ΔAcc {delta_acc:+.3f}, ΔAUC {delta_auc:+.3f}). "
        + (
            "Frozen-Transfer aus einem fremden Sensor-Domain (Hueft-/"
            "Handgelenk-Biobank, Total-Accel) erreicht damit die "
            "domain-spezifischen 88 Hand-Features **nicht** — erwartbar "
            "angesichts des Einheiten-Shifts und der kleinen Kohorte. "
            if delta_auc < -0.005 else
            "Bemerkenswert, da der Input-Domain-Shift (kein Gravity) gegen "
            "das Modell arbeitet. "
        )
        + "Naechste Stufe waere Fine-Tuning des Trunks (Stufe 2), "
        "wo der Shift teilweise wegtrainiert werden koennte.",
        "",
        f"Per-fold-Rohdaten: `{out_csv.relative_to(ROOT)}`.",
        "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "harnet_transfer.md"
    path.write_text("\n".join(lines))
    return path


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.training.deep.harnet")
    parser.add_argument("--model", choices=list(HARNET_VARIANTS), default="harnet5")
    parser.add_argument(
        "--force-embeddings", action="store_true",
        help="Embedding-Cache ignorieren und neu berechnen.",
    )
    args = parser.parse_args()

    df = harnet_loso(args.model, force_embeddings=args.force_embeddings)
    if df.empty:
        raise SystemExit("Keine Folds -- Daten / Filter pruefen.")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = MODEL_DIR / "harnet_loso.csv"
    df.to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}  ({len(df)} fold-Zeilen)")

    summary = _summarise(df)
    n_folds = df["held_out"].nunique()
    _print_tables(args.model, summary)
    report = _write_report(args.model, summary, n_folds, out_csv)
    print(f"-> {report}")


if __name__ == "__main__":
    main()

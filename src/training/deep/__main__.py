"""CLI fuer den Deep-Sequenz-Modell-Vergleich.

::

    python -m src.training.deep                       # alle Modelle, beide Fenster
    python -m src.training.deep --model cnn --win 1   # nur 1D-CNN, 1-s-Fenster
    python -m src.training.deep --model lstm --win 5

Schreibt die per-fold Metriken nach ``models/deep_loso.csv`` und druckt
zwei Vergleichstabellen.

WICHTIG -- Input-Fenster vs. Decision-Window. ``--win`` steuert das
*Input-Fenster* (wie viel roher Kontext das Modell pro Vorhersage sieht).
Das ist NICHT dasselbe wie das *Decision-Window*, auf dem man Accuracy
reportet. Ein 1-s-Input-Modell liefert per-1-s-Vorhersagen, die per Burst-
Aggregation auf 5/10/30-s-Decision-Windows geglaettet werden -- exakt wie
beim RF. Ein 5-s-Input-Modell trifft dagegen direkt eine groebere
Entscheidung. Fair vergleichbar ist nur *gleiches Decision-Window*:
Tabelle 1 stellt die 1-s-Input-Modelle bei matched Decision-Windows gegen
RF; die 5-s-Input-Modelle stehen separat in Tabelle 2, weil ihr per-window-
Wert schon eine ~5-s-Entscheidung ist (Referenz: RF-Burst@5s).
"""
from __future__ import annotations

import argparse

import pandas as pd

from src.training.deep.train_loso import MODEL_DIR, train_deep_loso

# RF-Headline aus CLAUDE.md (LOSO-by-person, N=10, gap=2500). RF nutzt
# 1-s-Input und reportet Decision-Windows per Burst-Aggregation.
# (acc, AUC) je Decision-Window -- die faire Vergleichsachse.
RF_DECISION: dict[str, tuple[float, float]] = {
    "1s": (0.856, 0.928),
    "5s": (0.887, 0.960),
    "10s": (0.870, 0.944),
    "30s": (0.831, 0.909),
}


def _decision_metrics(df: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Mean (acc, AUC) je Decision-Window fuer eine (model, window)-Gruppe.

    ``accuracy``/``roc_auc`` = per-Input-Window; ``acc_Ns``/``auc_Ns`` =
    Burst-aggregiert. Bei 1-s-Input ist per-window = Decision-Window 1s.
    """
    return {
        "1s": (df["accuracy"].mean(), df["roc_auc"].mean()),
        "5s": (df["acc_5s"].mean(), df["auc_5s"].mean()),
        "10s": (df["acc_10s"].mean(), df["auc_10s"].mean()),
        "30s": (df["acc_30s"].mean(), df["auc_30s"].mean()),
    }


def _print_matched_table(by_group: dict[tuple[str, int], pd.DataFrame]) -> None:
    """Tabelle 1: 1-s-Input-Modelle vs. RF bei gleichem Decision-Window."""
    scales = ["1s", "5s", "10s", "30s"]
    print("\n=== Tabelle 1: 1-s-Input -- matched Decision-Window-Vergleich ===")
    print("(Spalten = Decision-Window; acc/AUC. Alle Zeilen 1-s-Input.)")
    print(f"{'Modell':<14}" + "".join(f"{s:>16}" for s in scales))
    print(f"{'RF (Baseline)':<14}" + "".join(
        f"{RF_DECISION[s][0]:>7.3f}/{RF_DECISION[s][1]:<8.3f}" for s in scales
    ))
    for (model, win), df in sorted(by_group.items()):
        if win != 1:
            continue
        m = _decision_metrics(df)
        print(f"{model:<14}" + "".join(
            f"{m[s][0]:>7.3f}/{m[s][1]:<8.3f}" for s in scales
        ))


def _print_long_input_table(by_group: dict[tuple[str, int], pd.DataFrame]) -> None:
    """Tabelle 2: 5-s-Input-Modelle (per-window-Wert ist schon ~5-s-Entscheidung)."""
    rows = {(m, w): df for (m, w), df in by_group.items() if w == 5}
    if not rows:
        return
    print("\n=== Tabelle 2: 5-s-Input-Modelle ===")
    print("(per-window = ~5-s-Entscheidung; Referenz: RF-Burst@5s = "
          f"{RF_DECISION['5s'][0]:.3f}/{RF_DECISION['5s'][1]:.3f})")
    print(f"{'Modell':<14}{'per-window':>16}{'acc-sigma':>11}{'@30s':>16}")
    for (model, _), df in sorted(rows.items()):
        acc, auc = df["accuracy"].mean(), df["roc_auc"].mean()
        a30, u30 = df["acc_30s"].mean(), df["auc_30s"].mean()
        print(f"{model:<14}{acc:>7.3f}/{auc:<8.3f}{df['accuracy'].std():>11.3f}"
              f"{a30:>7.3f}/{u30:<8.3f}")


def _print_gap_table(by_group: dict[tuple[str, int], pd.DataFrame]) -> None:
    """Tabelle 3: Train/Val/Test-Gap -- Under-/Overfit-Diagnose.

    train = Fit auf die 8 Trainings-Personen, val = rotierende Holdout-
    Person, test = Test-Person (per-Input-Window-Accuracy). Lese-Hilfe:
    train ~ val ~ test  -> underfit (Modell zu klein);
    train >> val ~ test  -> data-limited (cross-subject-Gap, Tuning hilft kaum);
    train >> val >> test -> Overfit auf die Trainings-Personen.
    """
    print("\n=== Tabelle 3: Train/Val/Test-Gap (Under-/Overfit-Diagnose) ===")
    print(f"{'Modell':<8}{'Input':>7}{'train':>9}{'val':>9}{'test':>9}"
          f"{'train-test':>12}{'best_ep':>9}")
    for (model, win), df in sorted(by_group.items()):
        tr, va, te = df["train_acc"].mean(), df["val_acc"].mean(), df["accuracy"].mean()
        print(f"{model:<8}{str(win) + 's':>7}{tr:>9.3f}{va:>9.3f}{te:>9.3f}"
              f"{tr - te:>12.3f}{df['best_epoch'].mean():>9.1f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.training.deep")
    parser.add_argument(
        "--model", choices=["cnn", "lstm", "gru", "all"], default="all"
    )
    parser.add_argument(
        "--win", choices=["1", "5", "both"], default="both",
        help="Input-Fenster in Sekunden (NICHT das Decision-Window).",
    )
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--max-gap-ms", type=float, default=2500.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    models = ["cnn", "lstm", "gru"] if args.model == "all" else [args.model]
    windows = [1, 5] if args.win == "both" else [int(args.win)]

    all_folds: list[pd.DataFrame] = []
    by_group: dict[tuple[str, int], pd.DataFrame] = {}
    for win in windows:
        for model_name in models:
            df = train_deep_loso(
                model_name, win,
                include_all=args.include_all,
                max_gap_ms=args.max_gap_ms,
                seed=args.seed,
            )
            if df.empty:
                print(f"[warn] {model_name}/{win}s: keine Folds.")
                continue
            all_folds.append(df)
            by_group[(model_name, win)] = df

    if not all_folds:
        raise SystemExit("Keine Ergebnisse -- Daten / Filter pruefen.")

    folds_table = pd.concat(all_folds, ignore_index=True)
    out_csv = MODEL_DIR / "deep_loso.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    folds_table.to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}  ({len(folds_table)} fold-Zeilen)")

    _print_matched_table(by_group)
    _print_long_input_table(by_group)
    _print_gap_table(by_group)


if __name__ == "__main__":
    main()

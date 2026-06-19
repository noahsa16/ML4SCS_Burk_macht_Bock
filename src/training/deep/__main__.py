"""CLI fuer den Single-Model-Deep-LOSO-Lauf.

Ein Aufruf trainiert genau **ein** Modell auf genau **einem** Pool:

::

    python -m src.training.deep --model cnn                  # legacy-Pool, 1-s-Fenster
    python -m src.training.deep --model gru --pool legacy    # N=14-Kohorte (50 Hz)
    python -m src.training.deep --model tcn --pool legacy    # dilatierte Kausal-Convs
    python -m src.training.deep --model cnn --pool modern    # native 100hz_grav (N=4)
    python -m src.training.deep --model lstm --win both      # 1-s- + 5-s-Input

Schreibt die per-fold Metriken nach ``models/deep_loso_{pool}.csv`` und
druckt drei Vergleichstabellen. Der ``legacy``-Pool zieht Modern-Sessions
ueber ihre 50-Hz-Downsample-Views mit (kein Mischen von Sample-Raten);
der ``modern``-Pool nimmt nur native ``100hz_grav``-Sessions.

Per-Session-Z-Score ist **standardmaessig aus** (fuers CNN empirisch
neutral, gepaartes A/B N=14: Δacc −0.002, p=0.65; ohne ist das Modell
direkt deploybar ohne Kalibrierphase). ``--zscore`` schaltet ihn ein und
schreibt nach ``deep_loso_{pool}_zscore.csv``.

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
from pathlib import Path

import pandas as pd

from src.training import events as _events
from src.training.deep.train_loso import MODEL_DIR, train_deep_loso

# RF-Headline-Decision-Windows je Pool (acc, AUC) -- die faire Vergleichs-
# achse fuer 1-s-Input-Modelle (RF nutzt 1-s-Input + Burst-Aggregation).
# legacy = N=15-LOSO-Headline, post Capture-Clock-Fix, KAUSALE Burst-Agg
# (CLAUDE.md, 2026-06-13). Frueher standen hier die N=14-Pre-Fix-Zahlen mit
# center=True-Burst (5/10/30 s ~5-6 pp inflationiert) -- nicht mit den
# kausalen Deep-Burst-Zahlen vergleichbar. modern hat keine vorzeigbare
# RF-Zeile (N=4 ist zu klein) -> Tabellen ohne Baseline.
RF_DECISION_BY_POOL: dict[str, dict[str, tuple[float, float]] | None] = {
    "legacy": {
        "1s": (0.872, 0.947),
        "5s": (0.860, 0.933),
        "10s": (0.825, 0.906),
        "30s": (0.771, 0.856),
    },
    "modern": None,
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


def _print_matched_table(
    by_group: dict[tuple[str, int], pd.DataFrame],
    rf: dict[str, tuple[float, float]] | None,
) -> None:
    """Tabelle 1: 1-s-Input-Modelle vs. RF bei gleichem Decision-Window.

    ``rf`` ist die Pool-Baseline (acc, AUC) je Decision-Window oder
    ``None`` (kein vergleichbares RF, z. B. Modern-Pool) -> RF-Zeile faellt weg.
    """
    scales = ["1s", "5s", "10s", "30s"]
    print("\n=== Tabelle 1: 1-s-Input -- matched Decision-Window-Vergleich ===")
    print("(Spalten = Decision-Window; acc/AUC. Alle Zeilen 1-s-Input.)")
    print(f"{'Modell':<14}" + "".join(f"{s:>16}" for s in scales))
    if rf is not None:
        print(f"{'RF (Baseline)':<14}" + "".join(
            f"{rf[s][0]:>7.3f}/{rf[s][1]:<8.3f}" for s in scales
        ))
    for (model, win), df in sorted(by_group.items()):
        if win != 1:
            continue
        m = _decision_metrics(df)
        print(f"{model:<14}" + "".join(
            f"{m[s][0]:>7.3f}/{m[s][1]:<8.3f}" for s in scales
        ))


def _print_long_input_table(
    by_group: dict[tuple[str, int], pd.DataFrame],
    rf: dict[str, tuple[float, float]] | None,
) -> None:
    """Tabelle 2: 5-s-Input-Modelle (per-window-Wert ist schon ~5-s-Entscheidung)."""
    rows = {(m, w): df for (m, w), df in by_group.items() if w == 5}
    if not rows:
        return
    ref = (
        f"RF-Burst@5s = {rf['5s'][0]:.3f}/{rf['5s'][1]:.3f}"
        if rf is not None else "keine RF-Baseline fuer diesen Pool"
    )
    print("\n=== Tabelle 2: 5-s-Input-Modelle ===")
    print(f"(per-window = ~5-s-Entscheidung; Referenz: {ref})")
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
        "--model", choices=["cnn", "lstm", "gru", "tcn"], required=True,
        help="Genau ein Sequenz-Modell pro Lauf.",
    )
    parser.add_argument(
        "--pool", choices=["legacy", "modern"], default="legacy",
        help="legacy = N=14-Kohorte (50 Hz, inkl. Downsample-Views); "
             "modern = native 100hz_grav-Sessions. Kein 'auto' -- rohe "
             "Sequenzen koennen keine Sample-Raten mischen.",
    )
    parser.add_argument(
        "--win", choices=["1", "5", "both"], default="1",
        help="Input-Fenster in Sekunden (NICHT das Decision-Window).",
    )
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--max-gap-ms", type=float, default=2500.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--zscore", action="store_true",
        help="Per-Session-Z-Score einschalten (Default aus -- fuers CNN "
             "empirisch neutral, ohne ist direkt deploybar ohne "
             "Kalibrierphase). Schreibt nach deep_loso_{pool}_zscore.csv.",
    )
    parser.add_argument(
        "--exclude-boundary", action="store_true",
        help="Mehrdeutige Uebergangs-Fenster (writing-Anteil 0.4-0.6) "
             "ausschliessen -- fuer das Label-Qualitaets-Experiment.",
    )
    parser.add_argument(
        "--emit-json", action="store_true",
        help="Eine JSON-Zeile pro Event auf stdout (Web-Training-Cockpit).",
    )
    parser.add_argument(
        "--run-dir", default=None,
        help="Run-Verzeichnis fuer cv.csv/oof.csv (Cockpit). Eval-only -- "
             "kein model.joblib. Mit --win both wird nur das letzte Fenster "
             "abgelegt (das Cockpit nutzt immer ein Einzelfenster).",
    )
    args = parser.parse_args()

    exclude_boundary = (0.4, 0.6) if args.exclude_boundary else None
    zscore = args.zscore
    rf = RF_DECISION_BY_POOL[args.pool]
    windows = [1, 5] if args.win == "both" else [int(args.win)]

    on_event = _events.json_line_emitter() if args.emit_json else None
    run_dir = Path(args.run_dir) if args.run_dir else None

    all_folds: list[pd.DataFrame] = []
    by_group: dict[tuple[str, int], pd.DataFrame] = {}
    for win in windows:
        df = train_deep_loso(
            args.model, win,
            pool=args.pool,
            include_all=args.include_all,
            max_gap_ms=args.max_gap_ms,
            seed=args.seed,
            exclude_boundary=exclude_boundary,
            zscore=zscore,
            on_event=on_event,
            run_dir=run_dir,
        )
        if df.empty:
            print(f"[warn] {args.model}/{win}s: keine Folds.")
            continue
        all_folds.append(df)
        by_group[(args.model, win)] = df

    if not all_folds:
        raise SystemExit("Keine Ergebnisse -- Daten / Filter pruefen.")

    folds_table = pd.concat(all_folds, ignore_index=True)
    norm_suffix = "_zscore" if zscore else ""
    out_csv = MODEL_DIR / f"deep_loso_{args.pool}{norm_suffix}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    folds_table.to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}  ({len(folds_table)} fold-Zeilen)")

    _print_matched_table(by_group, rf)
    _print_long_input_table(by_group, rf)
    _print_gap_table(by_group)


if __name__ == "__main__":
    main()

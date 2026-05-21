"""Random-Forest Feature-Importance auf allen verfügbaren Sessions.

Trainiert ein RF auf allen Fenstern (gleiche Filter wie ``train_loso``)
und gibt zwei Importance-Rankings aus:

* **Impurity-based** (``rf.feature_importances_``) — frei aus dem
  Training, aber biased zugunsten von Features mit vielen unique values
  (continuous > kategorisch). Schnell, gut für ersten Überblick.
* **Permutation-Importance** auf einem 20%-Hold-out-Split — misst den
  Genauigkeits-Drop, wenn das Feature gepermutiert wird. Unbiased,
  vergleicht Features fair, aber langsamer (n_repeats × n_features Fits).

Beide werden auch als Gruppen-Summen ausgegeben (z. B. „alle
Frequenz-Features", „alle Jerk-Features") — der direkte Quervergleich
ob die neuen Frequenz-Features Mehrwert bringen.

CLI
---
::

    python scripts/ml/feature_importance.py
    python scripts/ml/feature_importance.py --top 20 --n-repeats 5
    python scripts/ml/feature_importance.py --plot models/feature_importance.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from src.training.train_loso import _load_windows, _select_sessions  # noqa: E402


def _group_of(feature_name: str) -> str:
    """Bucket ein Feature in eine Engineering-Gruppe für die Gruppen-Summe."""
    n = feature_name
    if n.startswith("corr_"):
        return "correlation"
    if "_jerk_" in n:
        return "jerk"
    if n.endswith("_zcr"):
        return "zcr"
    if n.endswith(("_dom_freq", "_spec_centroid", "_spec_entropy", "_band_3_8")):
        return "spectral"
    if n.startswith(("acc_mag_", "gyro_mag_")):
        return "magnitude"
    return "time_stats"


def _print_ranking(name: str, scores: np.ndarray, cols: list[str], top: int) -> None:
    order = np.argsort(scores)[::-1]
    print(f"\n=== {name} — Top {top} ===")
    width = max(len(cols[i]) for i in order[:top])
    for rank, i in enumerate(order[:top], 1):
        print(f"  {rank:2d}. {cols[i]:<{width}}  {scores[i]:.4f}")


def _group_sums(scores: np.ndarray, cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame({"feature": cols, "score": scores})
    df["group"] = df["feature"].apply(_group_of)
    agg = (
        df.groupby("group")
        .agg(total=("score", "sum"), n_features=("score", "size"), mean=("score", "mean"))
        .sort_values("total", ascending=False)
    )
    return agg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=15, help="Top-N pro Ranking (default: 15)")
    parser.add_argument(
        "--n-repeats",
        type=int,
        default=5,
        help="Permutation-Importance Wiederholungen (default: 5)",
    )
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--include-all", action="store_true", help="verdict-Gate übergehen")
    parser.add_argument("--min-windows", type=int, default=0)
    parser.add_argument(
        "--skip-permutation",
        action="store_true",
        help="Nur impurity-based importance (deutlich schneller).",
    )
    parser.add_argument(
        "--save-csv",
        type=Path,
        default=None,
        help="Komplettes Ranking als CSV nach PATH schreiben.",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        default=None,
        help="Top-N Bar-Chart als PNG nach PATH speichern.",
    )
    args = parser.parse_args()

    sessions = _select_sessions(include_all=args.include_all, min_windows=args.min_windows)
    if sessions.empty:
        raise SystemExit("Keine Sessions passen zum Filter. Versuche --include-all.")
    print(f"Lade {len(sessions)} Sessions: {sessions['session_id'].tolist()}")

    windows = pd.concat(
        [_load_windows(s) for s in sessions["session_id"].tolist()],
        ignore_index=True,
    )
    feature_cols = [
        c
        for c in windows.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id", "task_id", "task_category"}
    ]
    X = windows[feature_cols].to_numpy()
    y = windows["label"].to_numpy()
    print(f"Insgesamt {len(windows)} Fenster, {len(feature_cols)} Features. "
          f"Klassen: {np.bincount(y).tolist()}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=args.random_state, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=args.n_estimators,
        random_state=args.random_state,
        class_weight="balanced",
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)
    print(f"Hold-out accuracy (20% random split, nicht LOSO!): "
          f"{clf.score(X_test, y_test):.3f}")

    impurity = clf.feature_importances_
    _print_ranking("Impurity-based", impurity, feature_cols, args.top)

    print("\n--- Gruppen-Summen (impurity) ---")
    print(_group_sums(impurity, feature_cols).to_string(float_format=lambda v: f"{v:.4f}"))

    perm = None
    if not args.skip_permutation:
        print(f"\nBerechne Permutation-Importance (n_repeats={args.n_repeats}) …")
        result = permutation_importance(
            clf,
            X_test,
            y_test,
            n_repeats=args.n_repeats,
            random_state=args.random_state,
            n_jobs=-1,
        )
        perm = result.importances_mean
        _print_ranking("Permutation", perm, feature_cols, args.top)
        print("\n--- Gruppen-Summen (permutation) ---")
        print(_group_sums(perm, feature_cols).to_string(float_format=lambda v: f"{v:.4f}"))

    if args.save_csv:
        out = pd.DataFrame({
            "feature": feature_cols,
            "group": [_group_of(c) for c in feature_cols],
            "impurity": impurity,
        })
        if perm is not None:
            out["permutation"] = perm
        out = out.sort_values("impurity", ascending=False)
        args.save_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.save_csv, index=False)
        print(f"\n→ {args.save_csv}")

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        score = perm if perm is not None else impurity
        order = np.argsort(score)[::-1][: args.top]
        fig, ax = plt.subplots(figsize=(8, max(4, 0.3 * args.top)))
        ax.barh(range(len(order)), score[order][::-1])
        ax.set_yticks(range(len(order)))
        ax.set_yticklabels([feature_cols[i] for i in order][::-1])
        ax.set_xlabel("permutation importance" if perm is not None else "impurity importance")
        ax.set_title(f"Top {args.top} Features")
        fig.tight_layout()
        args.plot.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.plot, dpi=120)
        print(f"→ {args.plot}")


if __name__ == "__main__":
    main()

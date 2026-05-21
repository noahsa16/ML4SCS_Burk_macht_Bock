"""Reliability Diagramm + Brier / ECE für die Präsentation.

Zeigt, ob die vom Modell ausgegebenen Wahrscheinlichkeiten der
Realität entsprechen. Wenn das Modell sagt "70 % writing", sollte das
im Schnitt auch in 70 % der Fälle stimmen — perfekte Calibration =
Diagonale.

Aufbau:
  - Oben: Reliability-Kurve mit Per-Fold-Overlay, Mean-Linie, Diagonale,
    Annotationen für "overconfident" / "underconfident"-Regionen.
  - Unten: Histogramm der vorhergesagten Wahrscheinlichkeiten — zeigt
    in welchen Bins überhaupt Predictions liegen (Kontext für die Bin-
    Größen oben).
  - Footer: Brier Score + Expected Calibration Error (ECE) global.

CLI
---
    python scripts/plots/plot_reliability_diagram.py
    python scripts/plots/plot_reliability_diagram.py --bins 15
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.training.train_loso import (  # noqa: E402
    _load_windows,
    _select_sessions,
    _zscore_per_session,
)


MODELS = {
    "rf": ("Random Forest", lambda: RandomForestClassifier(
        n_estimators=200, class_weight="balanced",
        n_jobs=-1, random_state=42,
    )),
    "rf_platt": ("Random Forest + Platt Scaling", lambda: CalibratedClassifierCV(
        RandomForestClassifier(
            n_estimators=200, class_weight="balanced",
            n_jobs=-1, random_state=42,
        ),
        method="sigmoid", cv=5,
    )),
    "rf_isotonic": ("Random Forest + Isotonic Regression", lambda: CalibratedClassifierCV(
        RandomForestClassifier(
            n_estimators=200, class_weight="balanced",
            n_jobs=-1, random_state=42,
        ),
        method="isotonic", cv=5,
    )),
    "mlp": ("MLP (64, 32)", lambda: MLPClassifier(
        hidden_layer_sizes=(64, 32), max_iter=400,
        random_state=42, early_stopping=True,
    )),
    "histgb": ("HistGradBoost", lambda: HistGradientBoostingClassifier(
        max_iter=300, random_state=42,
    )),
    "logreg": ("Logistic Regression", lambda: LogisticRegression(
        max_iter=1000, class_weight="balanced",
    )),
    "svm": ("SVM-RBF", lambda: SVC(
        kernel="rbf", probability=True, class_weight="balanced",
        random_state=42,
    )),
}


def _reliability_curve(
    y_true: np.ndarray, proba: np.ndarray, n_bins: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pro Bin: mean predicted proba, fraction positives, count.

    Leere Bins → nan (werden im Plot übersprungen).
    """
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    mean_p = np.full(n_bins, np.nan)
    frac_pos = np.full(n_bins, np.nan)
    counts = np.zeros(n_bins, dtype=int)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # Letzter Bin inklusive; sonst exklusive rechte Grenze.
        mask = (proba >= lo) & (proba < hi) if i < n_bins - 1 \
            else (proba >= lo) & (proba <= hi)
        n = int(mask.sum())
        counts[i] = n
        if n > 0:
            mean_p[i] = proba[mask].mean()
            frac_pos[i] = y_true[mask].mean()
    return mean_p, frac_pos, counts


def _ece(y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error: Σ (bin_size / n) × |bin_acc − bin_conf|."""
    mean_p, frac_pos, counts = _reliability_curve(y_true, proba, n_bins)
    n_total = counts.sum()
    if n_total == 0:
        return float("nan")
    ece = 0.0
    for i in range(n_bins):
        if counts[i] == 0:
            continue
        ece += (counts[i] / n_total) * abs(frac_pos[i] - mean_p[i])
    return float(ece)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-all", action="store_true")
    ap.add_argument("--no-zscore", action="store_true")
    ap.add_argument("--bins", type=int, default=10,
                    help="Anzahl Bins für das Reliability-Diagramm")
    ap.add_argument("--model", choices=list(MODELS.keys()), default="rf",
                    help="Modellfamilie (default: rf)")
    args = ap.parse_args()
    model_name, model_factory = MODELS[args.model]
    out_path = ROOT / "reports" / "figures" / f"reliability_diagram_{args.model}.png"

    sessions = _select_sessions(args.include_all, 0)
    if sessions.empty:
        raise SystemExit("Keine trainierbaren Sessions gefunden.")

    frames = []
    for _, row in sessions.iterrows():
        df = _load_windows(row["session_id"])
        df["session_id"] = row["session_id"]
        df["person_id"] = row["person_id"]
        frames.append(df)
    all_windows = pd.concat(frames, ignore_index=True)

    feature_cols = [
        c for c in all_windows.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    if not args.no_zscore:
        all_windows = _zscore_per_session(all_windows, feature_cols)

    persons = sorted(sessions["person_id"].dropna().unique())
    print(f"Probanden: {len(persons)}   Sessions: {len(sessions)}   "
          f"Windows: {len(all_windows)}   Bins: {args.bins}")

    # Pro Fold: train + collect (proba, y_true)
    # Why: MLP / SVM brauchen vor-skalierte Features (z-score je Fold-Train);
    # bei Trees ist es unschädlich, also einheitlich anwenden.
    per_fold: list[tuple[str, np.ndarray, np.ndarray]] = []
    print(f"Modell: {model_name}")
    for held in persons:
        test_mask = all_windows["person_id"] == held
        train = all_windows.loc[~test_mask]
        test = all_windows.loc[test_mask]
        scaler = StandardScaler()
        X_train = scaler.fit_transform(train[feature_cols])
        X_test = scaler.transform(test[feature_cols])
        clf = model_factory()
        clf.fit(X_train, train["label"])
        proba = clf.predict_proba(X_test)[:, 1]
        per_fold.append((held, test["label"].to_numpy(), proba))
        print(f"  fold {held:6s}  n={len(proba):5d}")

    y_all = np.concatenate([f[1] for f in per_fold])
    p_all = np.concatenate([f[2] for f in per_fold])

    brier = float(brier_score_loss(y_all, p_all))
    ece = _ece(y_all, p_all, n_bins=args.bins)
    mean_p_all, frac_pos_all, counts_all = _reliability_curve(
        y_all, p_all, args.bins
    )

    print(f"\n=== Calibration ===")
    print(f"Brier Score = {brier:.4f}   ECE = {ece:.4f}")

    # === Figure ===
    fig = plt.figure(figsize=(11, 8.5))
    gs = fig.add_gridspec(
        2, 1, height_ratios=[3.4, 1], hspace=0.08,
    )
    ax_top = fig.add_subplot(gs[0])
    ax_bot = fig.add_subplot(gs[1], sharex=ax_top)

    # === Top: Reliability Curve ===
    # Shaded "good calibration" zone (±0.05 around diagonal)
    xs = np.linspace(0, 1, 200)
    ax_top.fill_between(
        xs, np.clip(xs - 0.05, 0, 1), np.clip(xs + 0.05, 0, 1),
        color="#22c55e", alpha=0.10, zorder=1,
        label="gut kalibriert (±5 %)",
    )

    # Diagonal = perfect calibration
    ax_top.plot(
        [0, 1], [0, 1], color="#0f172a", linewidth=2.5, linestyle="--",
        zorder=2, label="perfekte Kalibrierung",
    )

    # Per-fold thin lines
    for held, y_f, p_f in per_fold:
        mp, fp, _ = _reliability_curve(y_f, p_f, args.bins)
        mask = ~np.isnan(mp)
        ax_top.plot(
            mp[mask], fp[mask], color="#94a3b8", linewidth=1.0,
            alpha=0.55, zorder=3,
        )

    # Mean (pooled) line — bold
    mask = ~np.isnan(mean_p_all)
    ax_top.plot(
        mean_p_all[mask], frac_pos_all[mask],
        color="#1d4ed8", linewidth=3.0, marker="o", markersize=8,
        zorder=5, label=f"unser Modell (alle {len(persons)} Folds)",
    )

    # Region annotations — in den freien Ecken platziert (below-right für
    # overconfident, above-left für underconfident), Pfeile zeigen auf
    # konzeptionelle Beispiel-Positionen in der jeweiligen Region.
    ax_top.annotate(
        "OVERCONFIDENT\n(Modell sagt 90 %,\nRealität nur 70 %)",
        xy=(0.78, 0.55), xytext=(0.98, 0.16),
        fontsize=10, color="#b91c1c", ha="right", va="bottom",
        arrowprops=dict(arrowstyle="->", color="#b91c1c", lw=1.5,
                        connectionstyle="arc3,rad=-0.25"),
        bbox=dict(boxstyle="round,pad=0.4", fc="white",
                  ec="#b91c1c", alpha=0.95),
    )
    ax_top.annotate(
        "UNDERCONFIDENT\n(Modell sagt 30 %,\nRealität schon 50 %)",
        xy=(0.22, 0.50), xytext=(0.02, 0.98),
        fontsize=10, color="#1d4ed8", ha="left", va="top",
        arrowprops=dict(arrowstyle="->", color="#1d4ed8", lw=1.5,
                        connectionstyle="arc3,rad=0.25"),
        bbox=dict(boxstyle="round,pad=0.4", fc="white",
                  ec="#1d4ed8", alpha=0.95),
    )

    ax_top.set_xlim(-0.02, 1.02)
    ax_top.set_ylim(-0.02, 1.02)
    ax_top.set_xticks(np.arange(0, 1.01, 0.1))
    ax_top.set_yticks(np.arange(0, 1.01, 0.1))
    ax_top.set_ylabel(
        "Tatsächlicher Anteil 'writing'\n(was wirklich passiert ist)",
        fontsize=11, fontweight="bold",
    )
    ax_top.set_title(
        f"Reliability Diagramm — sind die Wahrscheinlichkeiten ehrlich?\n"
        f"{model_name}, LOSO-by-person, N={len(persons)} Probanden, "
        f"{len(y_all):,} Predictions",
        fontsize=13, fontweight="bold", pad=14,
    )
    ax_top.legend(loc="lower right", framealpha=0.95, fontsize=10)
    ax_top.grid(True, alpha=0.25)
    ax_top.set_aspect("equal", adjustable="box")

    # === Bottom: Prediction-count histogram per bin ===
    edges = np.linspace(0.0, 1.0, args.bins + 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    width = (edges[1] - edges[0]) * 0.92
    ax_bot.bar(
        centers, counts_all, width=width,
        color="#1d4ed8", alpha=0.65, edgecolor="#1e3a8a", linewidth=0.5,
    )
    ax_bot.set_xlabel(
        "Vorhergesagte Wahrscheinlichkeit P(writing)  "
        "[was das Modell glaubt]",
        fontsize=11, fontweight="bold",
    )
    ax_bot.set_ylabel("Anzahl\nPredictions", fontsize=10)
    ax_bot.grid(True, alpha=0.25, axis="y")
    ax_bot.set_xlim(-0.02, 1.02)

    # Footer: metrics
    fig.text(
        0.5, 0.005,
        f"Brier Score = {brier:.4f}  (niedriger = besser; 0 = perfekt, "
        f"0.25 = random)    "
        f"ECE = {ece:.4f}  (Schwelle für 'gut kalibriert': < 0.05)",
        ha="center", fontsize=11, fontweight="bold", color="#0f172a",
        bbox=dict(boxstyle="round,pad=0.5", fc="#f1f5f9", ec="#475569"),
    )

    fig.tight_layout(rect=[0, 0.05, 1, 1])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    print(f"→ {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

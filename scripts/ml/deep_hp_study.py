"""Playbook-faire Per-Architektur-HP-Studie fuer die Deep-Netze.

Pro Architektur: Sobol-Suche ueber lr/dropout/batch/weight_decay (@1 Seed),
Sieger waehlen, Sieger @3 Seeds (Varianz), significance-kompatible
Winner-Per-Fold-CVs emittieren + Suchraum-Rand-Warnungen + Infeasible-Zaehlung.
Fix: legacy @5 s, Adam, max_epochs=120 (damit Early-Stopping die Laenge
bestimmt, nicht die Decke -> fairer batch-Vergleich).

Winner-CVs: fuer best-vs-best-Vergleich via significance.py CLI:
  python -m src.evaluation.significance \
    models/deep_hp_winner_<A>_<pool>_cv.csv \
    models/deep_hp_winner_<B>_<pool>_cv.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
from src.training.deep.hp_search import is_at_boundary, sobol_configs  # noqa: E402
from src.training.deep.train_loso import train_deep_loso  # noqa: E402

MODELS = ("cnn", "tcn", "tcn6", "lstm", "gru", "transformer")
MODEL_DIR = ROOT / "models"
REPORT = ROOT / "reports" / "deep_hp_study.md"
MAX_EPOCHS = 120


def winners(trials: pd.DataFrame) -> pd.DataFrame:
    """Beste Config je model nach accuracy."""
    idx = trials.dropna(subset=["accuracy"]).groupby("model")["accuracy"].idxmax()
    cols = ["model", "lr", "dropout", "batch_size", "weight_decay",
            "accuracy", "roc_auc", "best_epoch"]
    return trials.loc[idx, [c for c in cols if c in trials.columns]].reset_index(drop=True)


def boundary_warnings(win: pd.DataFrame) -> list[str]:
    msgs: list[str] = []
    for r in win.itertuples():
        if is_at_boundary(r.lr, 1e-4, 1e-2, log=True):
            msgs.append(f"{r.model}: bester lr={r.lr:g} am Rand — Bereich erweitern")
        if is_at_boundary(r.weight_decay, 1e-6, 1e-2, log=True):
            msgs.append(f"{r.model}: bester weight_decay={r.weight_decay:g} am Rand")
        if r.dropout in (0.0, 0.5):
            msgs.append(f"{r.model}: bester dropout={r.dropout} am Rand")
        if r.batch_size in (32, 128):
            msgs.append(f"{r.model}: bester batch_size={r.batch_size} am Rand")
        if getattr(r, "best_epoch", 0) >= MAX_EPOCHS - 1:
            msgs.append(f"{r.model}: best_epoch an max_epochs — Decke anheben "
                        f"(batch↔updates-Fairness)")
    return msgs


def infeasible_count(trials: pd.DataFrame) -> int:
    return int(trials["accuracy"].isna().sum())


def winner_fold_cv(seed_dfs: list) -> "pd.DataFrame":
    """Seed-average per-fold metrics -> significance.py-compatible CV.

    seed_dfs: list of per-fold DataFrames (one per seed), each with columns
    held_out, accuracy, roc_auc. Returns one row per held_out with accuracy
    and roc_auc averaged across seeds.
    """
    allrows = pd.concat(seed_dfs, ignore_index=True)
    return (allrows.groupby("held_out", as_index=False)[["accuracy", "roc_auc"]]
            .mean())


def _mean_row(model: str, cfg: dict, seed: int, df: pd.DataFrame) -> dict:
    """Aggregiere einen per-fold LOSO-Lauf zur Metrik-Zeile."""
    return {
        "model": model, **cfg, "seed": seed,
        "accuracy": float(df["accuracy"].mean()) if not df.empty else float("nan"),
        "roc_auc": float(df["roc_auc"].mean()) if not df.empty else float("nan"),
        "best_epoch": float(df["best_epoch"].mean()) if "best_epoch" in df else 0.0,
    }


def _train_trial(model: str, cfg: dict, seed: int, pool: str, win: int) -> pd.DataFrame:
    """Ein LOSO-Lauf fuer eine Config -> per-fold DataFrame."""
    return train_deep_loso(
        model, win, pool=pool, seed=seed,
        lr=cfg["lr"], dropout=cfg["dropout"], batch_size=cfg["batch_size"],
        weight_decay=cfg["weight_decay"], max_epochs=MAX_EPOCHS,
    )


def _run_trial(model: str, cfg: dict, seed: int, pool: str, win: int) -> dict:
    """Ein LOSO-Lauf fuer eine Config -> aggregierte Metrik-Zeile."""
    return _mean_row(model, cfg, seed, _train_trial(model, cfg, seed, pool, win))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pool", default="legacy", choices=["legacy", "modern"])
    ap.add_argument("--win", type=int, default=5)
    ap.add_argument("--n-trials", type=int, default=16)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    args = ap.parse_args()

    rows = []
    for model in args.models:
        for cfg in sobol_configs(args.n_trials, seed=0):
            rows.append(_run_trial(model, cfg, args.seeds[0], args.pool, args.win))
    trials = pd.DataFrame(rows)
    win = winners(trials)

    # Sieger @ weitere Seeds (Varianz) — ein Trainingslauf, zwei Outputs:
    # per-seed MEAN fuer die win_var-Zusammenfassung + seed-gemittelte
    # per-fold CV (significance.py-kompatibel) je Sieger.
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    var_rows = []
    for w in win.itertuples():
        cfg = {"lr": w.lr, "dropout": w.dropout, "batch_size": w.batch_size,
               "weight_decay": w.weight_decay}
        seed_dfs = []
        for seed in args.seeds:
            df = _train_trial(w.model, cfg, seed, args.pool, args.win)
            seed_dfs.append(df)
            var_rows.append(_mean_row(w.model, cfg, seed, df))
        winner_cv = winner_fold_cv(seed_dfs)
        winner_cv.to_csv(
            MODEL_DIR / f"deep_hp_winner_{w.model}_{args.pool}_cv.csv", index=False)
    var = pd.DataFrame(var_rows)
    win_var = (var.groupby("model")[["accuracy", "roc_auc"]]
               .agg(["mean", "std"]).reset_index())

    trials.to_csv(MODEL_DIR / f"deep_hp_study_{args.pool}.csv", index=False)
    win.to_csv(MODEL_DIR / f"deep_hp_winners_{args.pool}.csv", index=False)

    lines = ["# Deep-HP-Studie — playbook-fairer Architektur-Vergleich", "",
             f"Pool={args.pool} @ {args.win}s | n_trials={args.n_trials} | "
             f"Seeds={args.seeds} | infeasible={infeasible_count(trials)}", "",
             "## Sieger je Architektur (@1 Seed Suche)",
             win.to_markdown(index=False), "",
             "## Sieger @ Seeds (Varianz)", win_var.to_markdown(index=False), "",
             "## Best-vs-best (significance.py-kompatibel)",
             "Winner-CVs sind significance.py-kompatibel — Top-Architekturen "
             "vergleichen mit: python -m src.evaluation.significance "
             f"models/deep_hp_winner_<A>_{args.pool}_cv.csv "
             f"models/deep_hp_winner_<B>_{args.pool}_cv.csv", "",
             "## Suchraum-Rand-Warnungen"]
    _warn = boundary_warnings(win)
    lines += [f"- {m}" for m in _warn] if _warn else ["- keine"]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

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


def _finish(trials: pd.DataFrame, pool: str, win_sec: int,
            n_trials: int, seeds: list) -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    win = winners(trials)
    var_rows = []
    for w in win.itertuples():
        cfg = {"lr": w.lr, "dropout": w.dropout, "batch_size": w.batch_size,
               "weight_decay": w.weight_decay}
        seed_dfs = []
        for seed in seeds:
            df = _train_trial(w.model, cfg, seed, pool, win_sec)
            seed_dfs.append(df)
            var_rows.append(_mean_row(w.model, cfg, seed, df))
        winner_cv = winner_fold_cv(seed_dfs)
        winner_cv.to_csv(
            MODEL_DIR / f"deep_hp_winner_{w.model}_{pool}_cv.csv", index=False)
    var = pd.DataFrame(var_rows)
    win_var = (var.groupby("model")[["accuracy", "roc_auc"]]
               .agg(["mean", "std"]).reset_index())
    trials.to_csv(MODEL_DIR / f"deep_hp_study_{pool}.csv", index=False)
    win.to_csv(MODEL_DIR / f"deep_hp_winners_{pool}.csv", index=False)
    lines = ["# Deep-HP-Studie — playbook-fairer Architektur-Vergleich", "",
             f"Pool={pool} @ {win_sec}s | n_trials={n_trials} | "
             f"Seeds={seeds} | infeasible={infeasible_count(trials)}", "",
             "## Sieger je Architektur (@1 Seed Suche)",
             win.to_markdown(index=False), "",
             "## Sieger @ Seeds (Varianz)", win_var.to_markdown(index=False), "",
             "## Best-vs-best (significance.py-kompatibel)",
             "Winner-CVs sind significance.py-kompatibel — Top-Architekturen "
             "vergleichen mit: python -m src.evaluation.significance "
             f"models/deep_hp_winner_<A>_{pool}_cv.csv "
             f"models/deep_hp_winner_<B>_{pool}_cv.csv", "",
             "## Suchraum-Rand-Warnungen"]
    _warn = boundary_warnings(win)
    lines += [f"- {m}" for m in _warn] if _warn else ["- keine"]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def run_full(pool: str, win_sec: int, n_trials: int,
             seeds: list, models: list) -> None:
    rows = []
    for model in models:
        for cfg in sobol_configs(n_trials, seed=0):
            rows.append(_run_trial(model, cfg, seeds[0], pool, win_sec))
    _finish(pd.DataFrame(rows), pool, win_sec, n_trials, seeds)


def run_trial(model: str, cfg: dict, seed: int, pool: str,
              win_sec: int, name: str, out_dir: str) -> None:
    df = _train_trial(model, cfg, seed, pool, win_sec)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_mean_row(model, cfg, seed, df)]).to_csv(
        out / f"trial_{name}.csv", index=False)
    print(f"trial {name}: written to {out / f'trial_{name}.csv'}")


def run_collect(hp_dir: str, pool: str, win_sec: int, seeds: list) -> None:
    files = sorted(Path(hp_dir).glob("trial_*.csv"))
    if not files:
        raise SystemExit(f"keine trial_*.csv in {hp_dir}")
    trials = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    n_trials = int(trials.groupby("model").size().max())
    _finish(trials, pool, win_sec, n_trials, seeds)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", default="full", choices=["full", "trial", "collect"])
    ap.add_argument("--pool", default="legacy", choices=["legacy", "modern"])
    ap.add_argument("--win", type=int, default=5)
    ap.add_argument("--n-trials", type=int, default=16)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    ap.add_argument("--hp-dir", default=str(MODEL_DIR / "hp"))
    # trial-Modus
    ap.add_argument("--model")
    ap.add_argument("--name")
    ap.add_argument("--lr", type=float)
    ap.add_argument("--dropout", type=float)
    ap.add_argument("--batch-size", type=int)
    ap.add_argument("--weight-decay", type=float)
    ap.add_argument("--seed", type=int, default=42)
    # Why: der Matrix-Trial-Runner-Befehl traegt --max-epochs 120 explizit
    # (batch<->updates-Fairness-Dokumentation im Kommando); MAX_EPOCHS bleibt
    # die tatsaechlich wirksame Konstante in _train_trial, dieses Flag wird nur
    # entgegengenommen damit argparse den generierten Befehl nicht ablehnt.
    ap.add_argument("--max-epochs", type=int, default=MAX_EPOCHS)
    args = ap.parse_args()
    if args.mode == "trial":
        cfg = {"lr": args.lr, "dropout": args.dropout,
               "batch_size": args.batch_size, "weight_decay": args.weight_decay}
        run_trial(args.model, cfg, args.seed, args.pool, args.win,
                  args.name, args.hp_dir)
    elif args.mode == "collect":
        run_collect(args.hp_dir, args.pool, args.win, args.seeds)
    else:
        run_full(args.pool, args.win, args.n_trials, args.seeds, args.models)


if __name__ == "__main__":
    main()

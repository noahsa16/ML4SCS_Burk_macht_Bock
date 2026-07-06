"""RF hyperparameter + window-size sweep, dispatched via train_loso.py.

Combines two axes:
1. Classic RF hyperparameters (max_depth, min_samples_leaf, max_features) at
   the default 1s feature window.
2. Feature-window size (window-sec) at baseline RF params, isolating the
   pipeline-level effect independent of RF tuning (see sweep_window_size.py
   for the analogous causal-burst-aware sweep this mirrors).

Each config is a separate `train_loso.py` subprocess (full LOSO-by-person),
resumable (skips configs whose CV CSV already exists). Results land under
models/rf_sweep/ as one CSV per run plus an aggregated summary.csv.
"""
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

try:
    import wandb
except ImportError:
    wandb = None

ROOT = Path(__file__).resolve().parents[2]
OUTDIR = ROOT / "models" / "rf_sweep"
WANDB_PROJECT = "ML4SCS_HP_Grid"
WANDB_GROUP = "rf_sweep"

RF_MAX_DEPTH = [None, 10, 20]
RF_MIN_SAMPLES_LEAF = [1, 2, 4]
RF_MAX_FEATURES = ["sqrt", 0.5]
WINDOW_SECS = [3, 5]

# Cap RF's own core usage instead of n_jobs=-1 (all cores) — this pod also
# runs GPU training jobs concurrently whose CPU-side loop overhead needs
# headroom; RF hogging every core starves them even though it never touches
# the GPU itself.
RF_N_JOBS = 8


def _label(max_depth, min_samples_leaf, max_features, window_sec):
    d = "None" if max_depth is None else str(max_depth)
    return f"d{d}_msl{min_samples_leaf}_mf{max_features}_w{window_sec}"


def build_runs():
    runs = []
    for max_depth, min_samples_leaf, max_features in itertools.product(
        RF_MAX_DEPTH, RF_MIN_SAMPLES_LEAF, RF_MAX_FEATURES
    ):
        params = {
            "max_depth": max_depth,
            "min_samples_leaf": min_samples_leaf,
            "max_features": max_features,
            "n_jobs": RF_N_JOBS,
        }
        runs.append({
            "label": _label(max_depth, min_samples_leaf, max_features, 1),
            "max_depth": max_depth, "min_samples_leaf": min_samples_leaf,
            "max_features": max_features, "window_sec": 1,
            "model_params": params,
        })
    for window_sec in WINDOW_SECS:
        runs.append({
            "label": _label(None, 1, "sqrt", window_sec),
            "max_depth": None, "min_samples_leaf": 1,
            "max_features": "sqrt", "window_sec": window_sec,
            "model_params": {"n_jobs": RF_N_JOBS},
        })
    return runs


def run_one(run: dict) -> Path:
    cv_path = OUTDIR / f"{run['label']}_cv.csv"
    cmd = [
        sys.executable, "-m", "src.training.train_loso",
        "--model", "rf",
        "--model-params", json.dumps(run["model_params"]),
        "--save-cv-csv", str(cv_path),
    ]
    if run["window_sec"] != 1:
        cmd += ["--window-sec", str(run["window_sec"])]

    print(f"\n>>> {run['label']}  ({' '.join(cmd)})")
    subprocess.run(cmd, cwd=ROOT, check=True)
    return cv_path


def summarize(run: dict, cv_path: Path) -> dict:
    df = pd.read_csv(cv_path)
    numeric_cols = [c for c in df.columns if c not in ("held_out", "n_test", "test_pct_writing")]
    row = {
        "label": run["label"], "max_depth": run["max_depth"],
        "min_samples_leaf": run["min_samples_leaf"],
        "max_features": run["max_features"], "window_sec": run["window_sec"],
        "n_folds": len(df),
    }
    for col in numeric_cols:
        row[f"mean_{col}"] = df[col].mean()
        row[f"std_{col}"] = df[col].std()
    return row


def _wandb_config(run: dict) -> dict:
    return {
        "model": "rf", "max_depth": run["max_depth"],
        "min_samples_leaf": run["min_samples_leaf"],
        "max_features": run["max_features"],
        "window_sec": run["window_sec"], "n_jobs": RF_N_JOBS,
    }


def start_wandb_run(run: dict):
    """Create the wandb run *before* training starts.

    train_loso.py has no epoch-level event hook (only run_grid_wandb.py's
    train_deep_loso does), so there is no live metric stream to attach to —
    but starting the run now still makes it show up immediately as
    "running" in the dashboard instead of only appearing once the full
    20-fold LOSO (several minutes) has finished.
    """
    if wandb is None:
        print("  (wandb not installed — skipping wandb logging)")
        return None
    try:
        return wandb.init(
            project=WANDB_PROJECT, group=WANDB_GROUP, name=run["label"],
            config=_wandb_config(run), reinit=True,
        )
    except Exception as e:
        print(f"  (wandb init failed, continuing without it: {e})")
        return None


def finish_wandb_run(wb_run, row: dict | None) -> None:
    if wb_run is None:
        return
    try:
        if row is not None:
            for k, v in row.items():
                if k.startswith("mean_") or k.startswith("std_"):
                    wb_run.summary[k] = v
            wb_run.finish()
        else:
            wb_run.finish(exit_code=1)
    except Exception as e:
        print(f"  (wandb finish failed: {e})")


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTDIR / "summary.csv"
    runs = build_runs()
    print(f"Sweep: {len(runs)} runs total ({len(RF_MAX_DEPTH) * len(RF_MIN_SAMPLES_LEAF) * len(RF_MAX_FEATURES)} RF-param x {len(WINDOW_SECS)} window-sec)")

    rows = []
    if summary_path.exists():
        rows = pd.read_csv(summary_path).to_dict("records")
    done_labels = {r["label"] for r in rows}

    for run in runs:
        if run["label"] in done_labels:
            print(f"skip (in summary): {run['label']}")
            continue
        cv_path = OUTDIR / f"{run['label']}_cv.csv"
        if cv_path.exists():
            print(f"skip (done): {run['label']}")
            row = summarize(run, cv_path)
            rows.append(row)
            continue

        wb_run = start_wandb_run(run)
        try:
            cv_path = run_one(run)
        except Exception:
            finish_wandb_run(wb_run, None)
            raise
        row = summarize(run, cv_path)
        finish_wandb_run(wb_run, row)
        rows.append(row)
        pd.DataFrame(rows).to_csv(summary_path, index=False)
        print(f"--> {run['label']}: acc={row['mean_accuracy']:.3f} auc={row['mean_roc_auc']:.3f}")

    print(f"\nDone. Summary: {summary_path}")


if __name__ == "__main__":
    main()

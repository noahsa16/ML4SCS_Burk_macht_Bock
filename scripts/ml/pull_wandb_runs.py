"""Pull HP-Grid-Runs von Weights & Biases in eine lokale Leaderboard-CSV.

Das Training selbst laeuft auf RunPod (Nachfolger von
notebooks/hp_grid_colab.ipynb) und loggt dort direkt nach wandb. Dieses
Script ist die Read-Seite: zieht alle Runs eines Projekts ueber die
wandb-API, flacht Config + Summary in Spalten ab und speichert sie im Repo
-- damit Ergebnisse auch ohne wandb-Dashboard versioniert/diffbar sind.

CLI: ``python scripts/ml/pull_wandb_runs.py [--project entity/project]
[--out models/hp_grid/wandb_runs.csv]``.
Benoetigt ``wandb login`` (interaktiv) oder ``WANDB_API_KEY`` env var.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import wandb

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT = "noah-samel-leuphana-universit-t-l-neburg/ML4SCS_HP_Grid"
DEFAULT_OUT = ROOT / "models" / "hp_grid" / "wandb_runs.csv"

# Why: wandb-Summaries mischen Top-Level-Metriken mit internen Buchhaltungs-
# Keys (_step, _wandb, ...) und Per-Fold-Breakdowns ("Person+.../final_acc")
# -- beide gehoeren nicht in ein flaches Leaderboard.
_SKIP_SUMMARY_PREFIX = "_"


def _is_leaderboard_metric(key: str) -> bool:
    return not key.startswith(_SKIP_SUMMARY_PREFIX) and "/" not in key


def fetch_runs(project: str) -> pd.DataFrame:
    api = wandb.Api()
    rows = []
    for run in api.runs(project):
        row = {"name": run.name, "state": run.state, "run_id": run.id}
        row.update(run.config)
        row.update({k: v for k, v in run.summary._json_dict.items()
                    if _is_leaderboard_metric(k)})
        rows.append(row)
    if not rows:
        raise SystemExit(f"keine Runs in Projekt {project!r} gefunden")
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    df = fetch_runs(args.project)
    if "cv_mean_acc" in df.columns:
        df = df.sort_values("cv_mean_acc", ascending=False)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"{len(df)} Runs -> {args.out}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()

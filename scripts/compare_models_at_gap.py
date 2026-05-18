"""Model-Vergleichs-Panel bei beliebigem ``max_gap_ms``.

Pendant zu :file:`compare_models.py`, aber baut die Window-Features
on-the-fly aus den ``data/processed/*_merged.csv`` neu — kein
Re-Generate der ``_windows.csv``-Cache-Dateien nötig. Lädt das Modell-
Set (LogReg / RF / ExtraTrees / HistGradBoost / MLP / SVM-RBF) und
die Burst-Aggregation aus :file:`compare_models.py`.

Usage::

    python scripts/compare_models_at_gap.py --gap 2000
    python scripts/compare_models_at_gap.py --gap 2000 --gap 300  # mehrere
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.features.windows import build_windows  # noqa: E402
from scripts.compare_models import _models, _eval_fold  # noqa: E402


def _zscore_per_session(df: pd.DataFrame, fcols: list[str]) -> pd.DataFrame:
    out = df.copy()
    grp = out.groupby("session_id", sort=False)[fcols]
    mu = grp.transform("mean")
    sd = grp.transform("std").replace(0.0, 1.0).fillna(1.0)
    out[fcols] = (out[fcols] - mu) / sd
    return out


def run_gap(gap: int, merged_cache: dict, sessions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for sid, m in merged_cache.items():
        w = build_windows(m, max_gap_ms=gap, max_spike_ms=0.0)
        w["session_id"] = sid
        frames.append(w)
    all_w = pd.concat(frames, ignore_index=True).merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left",
    )
    fcols = [
        c for c in all_w.select_dtypes("number").columns
        if c not in ("label", "t_center_ms")
    ]
    all_w = _zscore_per_session(all_w, fcols)

    persons = sorted(all_w.person_id.unique())
    print(f"\n=== gap={gap} ms — features={len(fcols)} — folds={len(persons)} ===")

    rows = []
    for held in persons:
        tr = all_w[all_w.person_id != held]
        te = all_w[all_w.person_id == held]
        if te.label.nunique() < 2:
            continue
        for name, model_factory in _models().items():
            # Models are stateful — get a fresh instance per fold.
            import copy
            model = copy.deepcopy(model_factory)
            m = _eval_fold(model, tr, te, fcols)
            rows.append({
                "gap": gap, "model": name, "fold": held,
                "n_test": len(te),
                **m,
            })
            print(
                f"  {name:>22s} | {held:>5s} | "
                f"acc={m['accuracy']:.3f}  AUC={m['roc_auc']:.3f}  "
                f"F1={m['f1_writing']:.3f}  acc10s={m['acc_10s']:.3f}  "
                f"AUC10s={m['auc_10s']:.3f}  fit={m['fit_s']:5.1f}s"
            )
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> None:
    print("\n=== Summary (mean ± std across folds) ===")
    print(
        f"{'gap':>4} {'model':>22} "
        f"{'acc':>14} {'AUC':>14} {'F1w':>6} {'acc10s':>7} {'AUC10s':>7} {'fit_s':>6}"
    )
    for (gap, name), g in df.groupby(["gap", "model"]):
        print(
            f"{int(gap):>4d} {name:>22s} "
            f"{g.accuracy.mean():.3f}±{g.accuracy.std():.3f}  "
            f"{g.roc_auc.mean():.3f}±{g.roc_auc.std():.3f}  "
            f"{g.f1_writing.mean():>6.3f} "
            f"{g.acc_10s.mean():>7.3f} {g.auc_10s.mean():>7.3f} "
            f"{g.fit_s.mean():>6.1f}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=int, action="append", required=False,
                    help="kann mehrfach angegeben werden")
    args = ap.parse_args()
    gaps = args.gap or [2000]

    sessions = pd.read_csv(ROOT / "data/sessions.csv")
    sessions = sessions[sessions.verdict.isin({"trainable", "usable"})]
    merged_cache = {
        sid: pd.read_csv(ROOT / f"data/processed/{sid}_merged.csv")
        for sid in sessions.session_id
    }
    print(f"Eligible sessions: {len(sessions)}  persons: "
          f"{sorted(sessions.person_id.unique())}")

    dfs = [run_gap(g, merged_cache, sessions) for g in gaps]
    summarize(pd.concat(dfs, ignore_index=True))


if __name__ == "__main__":
    main()

"""Ehrliche Live-Zahl: per-Session-Z-Score vs. leak-frei pooled, gepaart.

Reviewer-Befund: die Headline (0.855) nutzt per-Session-Z-Score — die
Test-Session wird mit ihrer eigenen (auch zukünftigen) Statistik normiert,
nicht-kausal und nicht live-deploybar. Dieses Skript misst dieselben LOSO-Folds
zweimal:

  * **per_session** — die Headline-Normalisierung (nicht-kausal, Offline-
    Obergrenze).
  * **pooled** — μ/σ auf den Trainings-Folds gefittet, auf den Held-out
    angewandt (leak-frei, entspricht einem deploybaren Modell mit
    eingebackenem μ/σ wie ``rf_all_live``).

Beide Arme teilen Folds und RF-Seed, daher ist die Differenz gepaart per
Wilcoxon (``src/evaluation/significance.py``) testbar. Ausgabe: beide
Summaries + p-Wert der Acc/AUC-Inflation. Burst-Aggregation ist seit dem
Causal-Fix trailing (live-ehrlich).

CLI: ``python scripts/ml/honest_live_loso.py [--pool legacy]``
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.significance import paired_fold_test  # noqa: E402
from src.training.train_loso import (  # noqa: E402
    _burst_metrics,
    _fit_eval_fold,
    _filter_pool,
    _load_windows,
    _profile_for_pool,
    _select_sessions,
    _zscore_per_session,
    _zscore_train_pooled,
)

NON_FEATURE = {"label", "t_center_ms", "session_id", "person_id",
               "task_id", "task_category"}
N_TREES = 200
SEED = 42


def _load(pool: str) -> tuple[pd.DataFrame, list[str]]:
    profile = _profile_for_pool(pool)
    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    aw = pd.concat(
        [_load_windows(s, profile) for s in sessions["session_id"].tolist()],
        ignore_index=True,
    ).merge(sessions[["session_id", "person_id"]], on="session_id", how="left")
    aw = _filter_pool(aw, pool)
    fcols = [c for c in aw.columns if c not in NON_FEATURE]
    return aw, fcols


def _run_arm(raw: pd.DataFrame, fcols: list[str], mode: str) -> list[dict]:
    persons = sorted(raw["person_id"].dropna().unique())
    pre = _zscore_per_session(raw, fcols) if mode == "per_session" else None
    rows = []
    for held in persons:
        if mode == "per_session":
            te = pre["person_id"] == held
            train, test = pre[~te], pre[te]
        else:  # pooled: split RAW, fit μ/σ on train only
            te = raw["person_id"] == held
            train, test = _zscore_train_pooled(raw[~te], raw[te], fcols)
        res = _fit_eval_fold(train, test, fcols, N_TREES, SEED)
        if res is None:
            continue
        res["held_out"] = held
        rows.append(res)
    return rows


def _summary(rows: list[dict]) -> dict:
    acc = np.array([r["accuracy"] for r in rows])
    auc = np.array([r["roc_auc"] for r in rows])
    f1 = np.array([r["f1_writing"] for r in rows])
    out = {"acc": acc, "auc": auc, "f1": f1,
           "acc_m": acc.mean(), "acc_s": acc.std(),
           "auc_m": auc.mean(), "auc_s": auc.std(), "f1_m": f1.mean()}
    for scale in ("5s", "10s", "30s"):
        sa = np.array([r["bursts"][scale]["accuracy"] for r in rows])
        su = np.array([r["bursts"][scale]["roc_auc"] for r in rows])
        out[f"acc_{scale}"] = sa.mean()
        out[f"auc_{scale}"] = su.mean()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pool", default="legacy", choices=["legacy", "modern"])
    args = ap.parse_args()

    raw, fcols = _load(args.pool)
    print(f"{raw['person_id'].nunique()} Folds | {len(raw)} Fenster | {len(fcols)} Features\n")

    ps_rows = _run_arm(raw, fcols, "per_session")
    pl_rows = _run_arm(raw, fcols, "pooled")
    ps, pl = _summary(ps_rows), _summary(pl_rows)

    print(f"{'Norm':<14}{'acc(1s)':>10}{'AUC(1s)':>10}{'F1w':>8}"
          f"{'acc@5s':>9}{'acc@10s':>9}{'acc@30s':>9}")
    for name, s in (("per_session", ps), ("pooled (live)", pl)):
        print(f"{name:<14}{s['acc_m']:>9.3f}±{s['acc_s']:.3f}"[:24].ljust(24)
              + f"{s['auc_m']:>9.3f}{s['f1_m']:>8.3f}"
              + f"{s['acc_5s']:>9.3f}{s['acc_10s']:>9.3f}{s['acc_30s']:>9.3f}")

    # Gepaarter Test der Inflation (per-Session minus pooled), gemeinsame Folds.
    acc_p = paired_fold_test(ps["acc"], pl["acc"])
    auc_p = paired_fold_test(ps["auc"], pl["auc"])
    d_acc = ps["acc_m"] - pl["acc_m"]
    d_auc = ps["auc_m"] - pl["auc_m"]
    print(f"\nInflation per-Session vs. pooled (Window-Level, {len(ps_rows)} Folds):")
    print(f"  Δacc = {d_acc:+.3f}  Wilcoxon p = {acc_p['p_value']:.4f}"
          f"  → {'signifikant' if acc_p['significant'] else 'n.s.'}")
    print(f"  ΔAUC = {d_auc:+.3f}  Wilcoxon p = {auc_p['p_value']:.4f}"
          f"  → {'signifikant' if auc_p['significant'] else 'n.s.'}")
    print(f"\n→ Ehrliche Live-Zahl (pooled, kausale Burst): "
          f"acc {pl['acc_m']:.3f} / AUC {pl['auc_m']:.3f} / "
          f"@5s {pl['acc_5s']:.3f} / @30s {pl['acc_30s']:.3f}")


if __name__ == "__main__":
    main()

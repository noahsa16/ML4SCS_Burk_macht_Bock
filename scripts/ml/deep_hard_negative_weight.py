"""Deep Hard-Negative-Reweighting: tcn6 baseline vs. 3x-Loss-Gewicht auf
keyboard/phone-Trainingsfenstern.

Testet am Deep-Netz (end-to-end gelernte Repraesentation), was am RF bereits
falsifiziert ist (``scripts/ml/hard_negative_feature_test.py`` +
``reports/hard_negative_feature.md``): hebt ein hoeheres Loss-Gewicht auf den
dokumentierten Tipp-Confound-Fenstern (``keyboard_typing`` / ``phone_typing``)
die Tipp-Ablehnung? RF-Befund: **nein** -- phone-FPR 0.243 -> 0.286 (schlechter),
keyboard flach, LOSO n.s. Der Deep-Fall war der einzige nicht-getestete Riss der
Argumentation (das RF re-gewichtet feste Features, ein Netz koennte theoretisch
seine Repraesentation umformen).

Sauber gepaart: identische Folds (grouped-K-fold, ``random_state=42``), identischer
Fold-Seed und identische HP fuer beide Arme -- die EINZIGE Variable ist
``sample_weight``. Nutzt die Deployment-Trainingsmaschinerie (``train_one_model``
mit dem neuen optionalen ``sample_weight``), damit das Reweighting nicht durch
einen divergenten Trainings-Loop konfundiert wird.

    python scripts/ml/deep_hard_negative_weight.py [--weight 3.0] [--folds 5]
                                                    [--window-sec 5] [--seed 42]

Output: reports/deep_hard_negative_weight.md + models/deep_hard_neg_weight_{oof,cv}.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from sklearn.metrics import roc_auc_score

# Why: run as `python scripts/ml/deep_hard_negative_weight.py` from repo root —
# add the project root to sys.path BEFORE the src imports below.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.deep.train_loso import (
    DEVICE, POOL_FS, _POOL_NATIVE_PROFILE, _fold_splits, _load_all_sessions,
    _pool_plan, _set_seed, _stack_persons, predict_proba, train_one_model,
)
from src.training.deep.models import MODELS
from src.training.train_loso import _burst_metrics, _select_sessions
MARKER_DIR = ROOT / "data" / "raw" / "markers"
REPORT = ROOT / "reports" / "deep_hard_negative_weight.md"
OOF_CSV = ROOT / "models" / "deep_hard_neg_weight_oof.csv"
CV_CSV = ROOT / "models" / "deep_hard_neg_weight_cv.csv"

# Die zwei dokumentierten Tipp-Confounds (identisch zum RF-Reweighting-Test).
WEIGHTED_TASKS = ("keyboard_typing", "phone_typing")


def _parse_task_blocks(markers: pd.DataFrame) -> pd.DataFrame:
    """Marker-Events -> Task-Bloecke (task_start/task_end je task_index gepaart).

    Reimplementiert die reine Logik aus ``scripts/ml/marker_fpr.py`` inline, um
    keinen Cross-Script-Import einzugehen."""
    ev = markers[markers["event"].isin(["task_start", "task_end"])]
    rows = []
    for _, g in ev.groupby("task_index"):
        starts = g[g["event"] == "task_start"]
        ends = g[g["event"] == "task_end"]
        if starts.empty or ends.empty:
            continue
        rows.append({
            "task_id": starts.iloc[0]["task_id"],
            "start_ms": float(starts["timestamp_ms"].min()),
            "end_ms": float(ends["timestamp_ms"].max()),
        })
    return pd.DataFrame(rows, columns=["task_id", "start_ms", "end_ms"])


def _window_tasks(t_center_ms: np.ndarray, blocks: pd.DataFrame) -> np.ndarray:
    """task_id-String je Fenster; '' fuer Fenster ausserhalb aller Bloecke.

    Behaelt ALLE Fenster (anders als ``assign_task``, das droppt) -- der
    Gewichtsvektor muss zu ``X`` laengen-aligned bleiben."""
    tasks = np.full(len(t_center_ms), "", dtype=object)
    if blocks.empty:
        return tasks
    intervals = pd.IntervalIndex.from_arrays(
        blocks["start_ms"], blocks["end_ms"], closed="left")
    idx = intervals.get_indexer(np.asarray(t_center_ms))
    ids = blocks["task_id"].to_numpy()
    inb = idx >= 0
    tasks[inb] = ids[idx[inb]]
    return tasks


def _tag_hard_negatives(data: dict, weight: float) -> None:
    """Haengt pro Session ``task`` (str-Array) + ``w`` (float32-Gewicht) an das
    data-Dict -- laengen-aligned zu ``X``/``y``/``t``. So stackt
    ``_stack_persons(..., 'w', ...)`` das Gewicht in derselben Reihenfolge wie X."""
    for sid, d in data.items():
        mfile = MARKER_DIR / f"{sid}_markers.csv"
        if mfile.exists():
            blocks = _parse_task_blocks(pd.read_csv(mfile))
            tasks = _window_tasks(d["t"], blocks)
        else:
            tasks = np.full(len(d["t"]), "", dtype=object)
        d["task"] = tasks
        d["w"] = np.where(np.isin(tasks, WEIGHTED_TASKS),
                          float(weight), 1.0).astype(np.float32)


def _fpr(pred: np.ndarray, y: np.ndarray, task: np.ndarray, name: str) -> float:
    """False-Positive-Rate auf den echten Negativ-Fenstern (y==0) einer Task."""
    mask = (task == name) & (y == 0)
    if mask.sum() == 0:
        return float("nan")
    return float((pred[mask] == 1).mean())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--weight", type=float, default=3.0,
                    help="Loss-Gewicht auf keyboard/phone-Trainingsfenstern (RF-Test: 3.0)")
    ap.add_argument("--folds", type=int, default=5,
                    help="grouped-K-fold (Suchprotokoll); None-Aequivalent nicht angeboten")
    ap.add_argument("--window-sec", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--weight-decay", type=float, default=1e-5)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-epochs", type=int, default=120)
    ap.add_argument("--patience", type=int, default=8)
    args = ap.parse_args()

    pool = "legacy"
    fs = POOL_FS[pool]
    seq_len = args.window_sec * fs
    stride = fs // 2

    sessions = _select_sessions(
        include_all=False, min_windows=0, profile=_POOL_NATIVE_PROFILE[pool])
    plan = _pool_plan(sessions, pool)
    data = _load_all_sessions(sessions, seq_len, stride, plan, 2500.0, None,
                              zscore=False)
    _tag_hard_negatives(data, args.weight)

    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)

    n_hard = sum(int((d["w"] > 1.0).sum()) for d in data.values())
    n_tot = sum(len(d["y"]) for d in data.values())
    print(f"=== Deep Hard-Negative-Reweighting | tcn6 | {args.window_sec}s | "
          f"{len(person_ids)} Personen | {args.folds}-fold | device={DEVICE} ===")
    print(f"Gewichtete Fenster (keyboard/phone, {args.weight}x): "
          f"{n_hard}/{n_tot} ({100*n_hard/max(n_tot,1):.1f} %)")

    splits = _fold_splits(person_ids, args.folds)
    oof_rows: list[pd.DataFrame] = []
    per_fold: list[dict] = []

    for i, (test_group, val_p, train_ps) in enumerate(splits):
        train_X = _stack_persons(train_ps, "X", data, persons)
        train_y = _stack_persons(train_ps, "y", data, persons)
        train_w = _stack_persons(train_ps, "w", data, persons)
        val_X = _stack_persons([val_p], "X", data, persons)
        val_y = _stack_persons([val_p], "y", data, persons)
        test_X = _stack_persons(test_group, "X", data, persons)
        test_y = _stack_persons(test_group, "y", data, persons)
        test_t = _stack_persons(test_group, "t", data, persons)
        test_task = _stack_persons(test_group, "task", data, persons)
        test_sids = [s for p in test_group for s in persons[p]]
        test_sess = np.concatenate(
            [np.full(len(data[s]["y"]), s, dtype=object) for s in test_sids])
        if len(np.unique(test_y)) < 2:
            continue

        held = "+".join(sorted(test_group))
        fold_seed = args.seed + i
        common = dict(max_epochs=args.max_epochs, patience=args.patience,
                      batch_size=args.batch_size, lr=args.lr,
                      weight_decay=args.weight_decay)

        # Arm A: baseline (kein sample_weight). Seed vor Konstruktion -> identische
        # Init + Shuffle-Sequenz wie der weighted Arm (maximal gepaart).
        _set_seed(fold_seed)
        m_base = MODELS["tcn6"](dropout=args.dropout)
        m_base, _ = train_one_model(m_base, train_X, train_y, val_X, val_y,
                                    sample_weight=None, **common)
        pb = predict_proba(m_base, test_X)

        # Arm B: 3x-Gewicht auf keyboard/phone-Trainingsfenstern.
        _set_seed(fold_seed)
        m_wt = MODELS["tcn6"](dropout=args.dropout)
        m_wt, _ = train_one_model(m_wt, train_X, train_y, val_X, val_y,
                                  sample_weight=train_w, **common)
        pw = predict_proba(m_wt, test_X)

        acc_b = float(((pb >= 0.5).astype(int) == test_y).mean())
        acc_w = float(((pw >= 0.5).astype(int) == test_y).mean())
        try:
            auc_b, auc_w = roc_auc_score(test_y, pb), roc_auc_score(test_y, pw)
        except ValueError:
            auc_b = auc_w = float("nan")
        per_fold.append({"held_out": held, "acc_base": acc_b, "acc_weighted": acc_w,
                         "auc_base": auc_b, "auc_weighted": auc_w})
        print(f"  fold {i} [{held:>10}]  base {acc_b:.3f}/{auc_b:.3f}  "
              f"weighted {acc_w:.3f}/{auc_w:.3f}")

        oof_rows.append(pd.DataFrame({
            "session_id": test_sess, "t_center_ms": test_t, "task": test_task,
            "label": test_y, "proba_base": pb, "proba_weighted": pw,
        }))

    oof = pd.concat(oof_rows, ignore_index=True)
    cv = pd.DataFrame(per_fold)
    OOF_CSV.parent.mkdir(parents=True, exist_ok=True)
    oof.to_csv(OOF_CSV, index=False)
    cv.to_csv(CV_CSV, index=False)

    # --- pooled Metriken (window + burst @5s + keyboard/phone-FPR) ---
    def _win(col: str) -> tuple[float, float]:
        pred = (oof[col] >= 0.5).astype(int)
        return (float((pred == oof["label"]).mean()),
                float(roc_auc_score(oof["label"], oof[col])))
    wacc_b, wauc_b = _win("proba_base")
    wacc_w, wauc_w = _win("proba_weighted")

    tdf = oof[["session_id", "t_center_ms"]]
    b5_b = _burst_metrics(oof["proba_base"].to_numpy(), oof["label"].to_numpy(), tdf)["5s"]
    b5_w = _burst_metrics(oof["proba_weighted"].to_numpy(), oof["label"].to_numpy(), tdf)["5s"]

    task = oof["task"].to_numpy()
    y = oof["label"].to_numpy()
    pred_b = (oof["proba_base"].to_numpy() >= 0.5).astype(int)
    pred_w = (oof["proba_weighted"].to_numpy() >= 0.5).astype(int)
    fpr = {t: (_fpr(pred_b, y, task, t), _fpr(pred_w, y, task, t)) for t in WEIGHTED_TASKS}

    # gepaarter Wilcoxon auf per-Fold window-acc
    d_acc = cv["acc_weighted"].to_numpy() - cv["acc_base"].to_numpy()
    try:
        p_acc = float(wilcoxon(cv["acc_weighted"], cv["acc_base"]).pvalue)
    except ValueError:
        p_acc = float("nan")

    lines = [
        "# Deep Hard-Negative-Reweighting: tcn6 baseline vs. keyboard/phone-Gewicht",
        "",
        f"Pool legacy, tcn6, {args.window_sec}s-Fenster, {len(cv)} grouped-Folds, "
        f"Gewicht **{args.weight}x** auf keyboard/phone-Trainingsfenstern "
        f"({n_hard}/{n_tot} = {100*n_hard/max(n_tot,1):.1f} %). Gepaart pro Fold "
        "(gleicher Seed/Init/HP, einzige Variable = sample_weight).",
        "",
        "## Window-Level (1 Fenster = 1 Entscheidung)",
        "",
        "| Metrik | base | weighted | Δ |",
        "|---|---|---|---|",
        f"| acc | {wacc_b:.4f} | {wacc_w:.4f} | {wacc_w-wacc_b:+.4f} |",
        f"| AUC | {wauc_b:.4f} | {wauc_w:.4f} | {wauc_w-wauc_b:+.4f} |",
        "",
        "## Burst @5s (kausal)",
        "",
        "| Metrik | base | weighted | Δ |",
        "|---|---|---|---|",
        f"| acc | {b5_b['acc']:.4f} | {b5_w['acc']:.4f} | {b5_w['acc']-b5_b['acc']:+.4f} |",
        f"| AUC | {b5_b['auc']:.4f} | {b5_w['auc']:.4f} | {b5_w['auc']-b5_b['auc']:+.4f} |",
        "",
        "## ZIELCHECK: keyboard/phone-FPR (Anteil Tipp-Fenster faelschlich 'writing')",
        "",
        "| Task | base | weighted | Δ |",
        "|---|---|---|---|",
    ]
    for t in WEIGHTED_TASKS:
        fb, fw = fpr[t]
        lines.append(f"| {t} | {fb:.3f} | {fw:.3f} | {fw-fb:+.3f} |")
    lines += [
        "",
        "## Signifikanz (gepaarter Wilcoxon, per-Fold window-acc)",
        "",
        f"- Δacc (weighted − base): median {float(np.median(d_acc)):+.4f}, "
        f"p={p_acc:.4f} {'(n.s.)' if not (p_acc < 0.05) else '(sig)'}",
        "",
        "## Lesart",
        "",
        "Erfolg = keyboard/phone-FPR **sinkt** UND LOSO-acc nicht signifikant "
        "schlechter. Der RF-Test (`reports/hard_negative_feature.md`) zeigte hier "
        "phone-FPR 0.243 -> 0.286 (schlechter). Bestaetigt der Deep-Fall das (FPR "
        "flach/schlechter, acc n.s.), ist die Feature-/Emphasis-Achse fuer den "
        "Tipp-Confound auch end-to-end erschoepft -- verbleibender Hebel = mehr "
        "Trainingsdaten mit aggressivem Tippstil.",
        "",
        f"Rohdaten: `{OOF_CSV.relative_to(ROOT)}`, `{CV_CSV.relative_to(ROOT)}`.",
    ]
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

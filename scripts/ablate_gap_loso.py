"""Label-Smoothing Ablation über alle LOSO-Folds.

Vergleicht mehrere ``max_gap_ms``-Werte am vollen Leave-One-Subject-Out-Setup.
Pro Fold wird auf den anderen Probanden trainiert und auf dem Hold-out
ausgewertet; reportiert werden Per-Fold-Metriken plus Mean ± Std.

Achtung: ``max_gap_ms`` verändert das Label sowohl im Trainings- als auch
im Test-Set — Verbesserungen können daher Modell- *oder* Label-Drift-Effekt
sein. Siehe :file:`CLAUDE.md` (Label smoothing).

Usage::

    python scripts/ablate_gap_loso.py
    python scripts/ablate_gap_loso.py --gaps 300 600 1000 2000 4000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.features.windows import build_windows  # noqa: E402


def _zscore_per_session(df: pd.DataFrame, fcols: list[str]) -> pd.DataFrame:
    out = df.copy()
    grp = out.groupby("session_id", sort=False)[fcols]
    mu = grp.transform("mean")
    sd = grp.transform("std").replace(0, 1.0).fillna(1.0)
    out[fcols] = (out[fcols] - mu) / sd
    return out


def main(gaps: list[int]) -> None:
    sessions = pd.read_csv(ROOT / "data/sessions.csv")
    sessions = sessions[sessions.verdict.isin({"trainable", "usable"})]
    if "study_mode" in sessions.columns:
        sessions = sessions[sessions["study_mode"].fillna("") != "test"]
    merged_cache = {
        sid: pd.read_csv(ROOT / f"data/processed/{sid}_merged.csv")
        for sid in sessions.session_id
    }
    person = dict(zip(sessions.session_id, sessions.person_id))
    persons = sorted(sessions.person_id.unique())
    print(f"Eligible sessions: {len(sessions)}, persons: {persons}")

    header = (
        f"{'gap':>4} {'fold':>6} {'%w-Tr':>6} {'%w-Te':>6} "
        f"{'acc':>5} {'AUC':>5} {'F1w':>5} {'prec':>5} {'rec':>5} "
        f"{'FP':>5} {'FN':>4}"
    )
    print("\n" + header)
    print("-" * len(header))

    summary_rows = []
    for gap in gaps:
        frames = []
        for sid, m in merged_cache.items():
            w = build_windows(m, max_gap_ms=gap, max_spike_ms=0.0)
            w["session_id"] = sid
            w["person_id"] = person[sid]
            frames.append(w)
        all_w = pd.concat(frames, ignore_index=True)
        fcols = [
            c for c in all_w.select_dtypes("number").columns
            if c not in ("label", "t_center_ms")
        ]
        all_w = _zscore_per_session(all_w, fcols)

        fold_metrics = []
        for held in persons:
            tr = all_w[all_w.person_id != held]
            te = all_w[all_w.person_id == held]
            if te.label.nunique() < 2:
                print(f"{gap:>4d} {held:>6s}  skipped (single-class test)")
                continue
            clf = RandomForestClassifier(
                n_estimators=200, random_state=42,
                class_weight="balanced", n_jobs=-1,
            )
            clf.fit(tr[fcols].to_numpy(), tr.label.to_numpy())
            yp = clf.predict(te[fcols].to_numpy())
            pp = clf.predict_proba(te[fcols].to_numpy())[:, 1]
            yt = te.label.to_numpy()
            tn, fp, fn, tp = confusion_matrix(yt, yp).ravel()
            prec = tp / (tp + fp) if tp + fp else float("nan")
            rec = tp / (tp + fn) if tp + fn else float("nan")
            acc = (tp + tn) / len(yt)
            auc = roc_auc_score(yt, pp)
            f1 = f1_score(yt, yp)
            fold_metrics.append({
                "gap": gap, "fold": held, "n_test": len(yt),
                "pct_w_tr": tr.label.mean(), "pct_w_te": te.label.mean(),
                "acc": acc, "auc": auc, "f1w": f1,
                "prec": prec, "rec": rec, "FP": fp, "FN": fn,
            })
            print(
                f"{gap:>4d} {held:>6s} {tr.label.mean():>6.3f} {te.label.mean():>6.3f} "
                f"{acc:>5.3f} {auc:>5.3f} {f1:>5.3f} {prec:>5.3f} {rec:>5.3f} "
                f"{fp:>5d} {fn:>4d}"
            )
        if fold_metrics:
            df = pd.DataFrame(fold_metrics)
            summary_rows.append({
                "gap": gap,
                "acc_mean": df.acc.mean(), "acc_std": df.acc.std(),
                "auc_mean": df.auc.mean(), "auc_std": df.auc.std(),
                "f1w_mean": df.f1w.mean(),
                "prec_mean": df.prec.mean(),
                "rec_mean": df.rec.mean(),
                "FP_total": int(df.FP.sum()),
                "FN_total": int(df.FN.sum()),
            })
            print(
                f"     mean.            {df.pct_w_tr.mean():>6.3f} {df.pct_w_te.mean():>6.3f} "
                f"{df.acc.mean():>5.3f} {df.auc.mean():>5.3f} {df.f1w.mean():>5.3f} "
                f"{df.prec.mean():>5.3f} {df.rec.mean():>5.3f} "
                f"{int(df.FP.sum()):>5d} {int(df.FN.sum()):>4d}"
            )

    print("\n=== LOSO-Summary (mean ± std across folds) ===")
    s = pd.DataFrame(summary_rows)
    print(f"{'gap':>4} {'acc':>14} {'AUC':>14} {'F1w':>6} {'prec':>6} {'rec':>6} {'FP':>5} {'FN':>5}")
    for _, r in s.iterrows():
        print(
            f"{int(r.gap):>4d} {r.acc_mean:.3f}±{r.acc_std:.3f}  "
            f"{r.auc_mean:.3f}±{r.auc_std:.3f}  "
            f"{r.f1w_mean:>6.3f} {r.prec_mean:>6.3f} {r.rec_mean:>6.3f} "
            f"{int(r.FP_total):>5d} {int(r.FN_total):>5d}"
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gaps", type=int, nargs="+",
                    default=[300, 600, 1000, 2000])
    args = ap.parse_args()
    main(args.gaps)

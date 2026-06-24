"""Acc-only vs. full-IMU LOSO — beantwortet die Deployment-Gate-Frage.

**Warum dieses Skript existiert.** Ein passiver Ganztags-Tracker auf der Watch
will im Idealfall ``CMSensorRecorder`` nutzen: batterieschonend, läuft auch wenn
die App nicht im Vordergrund ist — aber er liefert **nur das Accelerometer, kein
Gyroskop**. Unser Headline-Modell zieht ~47 % seines 88-Feature-Vektors aus den
Gyro-Achsen (rx/ry/rz + gyro_mag + Gyro-Korrelationen). Die Architektur-Frage ist
also: *Wie viel Genauigkeit kostet es, das Gyroskop wegzulassen?* Ist der Verlust
klein, wird der echte Passiv-Pfad (acc-only) tragbar; ist er groß, braucht der
Tracker eine aktive Motion-Session (Workout/Extended-Runtime) mit Batterie-Kosten.

Methodik = das gepaarte ``--drop-gravity``-Muster aus ``train_loso``, nur auf der
Gyro-Achse: **dieselben Sessions, dieselben Folds, dieselbe Per-Session-Z-Score-
Normalisierung** — der einzige Unterschied ist, ob die 41 Gyro-Features im
Feature-Set sind. Damit ist die Differenz gepaart per Wilcoxon testbar (kein
Kohorten-Confound). Reuse der kausalen Burst-Metriken → die Tracker-relevanten
5/10/30-s-Skalen kommen gratis mit.

CLI::

    python scripts/ml/acc_only_loso.py            # legacy pool, N=15
    python scripts/ml/acc_only_loso.py --pool legacy
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sklearn.metrics import roc_auc_score  # noqa: E402

from src.evaluation.significance import paired_fold_test  # noqa: E402
from src.evaluation.hmm import (  # noqa: E402
    class_priors,
    estimate_transition_matrix,
    forward_filter,
    scaled_likelihoods,
)
from src.training.train_loso import (  # noqa: E402
    _exclude_drawing_windows,
    _fit_eval_fold,
    _filter_pool,
    _load_windows,
    _profile_for_pool,
    _select_sessions,
    _zscore_per_session,
    BURST_SCALES_SEC,
)

MODELS = ROOT / "models"


def _is_gyro_feature(name: str) -> bool:
    """True iff a feature column is derived from the gyroscope axes.

    Gyro-derived = the three rotation-rate axes (rx/ry/rz: stats, spectral,
    ZCR), the gyro-magnitude block, and the gyro cross-axis correlations.
    Everything else (ax/ay/az, acc_mag, accel jerk, accel correlations) is
    available from a passive accelerometer-only recording.
    """
    return (
        name.startswith(("rx_", "ry_", "rz_"))
        or name.startswith("gyro_")
        or name in {"corr_rx_ry", "corr_rx_rz", "corr_ry_rz"}
    )


def _run_arm(
    all_windows: pd.DataFrame,
    feature_cols: list[str],
    groups: list,
    group_col: str,
    sessions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run LOSO for one feature set.

    Returns ``(per_fold_metrics, oof)`` — the OOF table (per-window proba_cal /
    proba_raw + label + session/person/t_center) feeds the HMM-Filter stage.
    """
    rows: list[dict] = []
    oof_chunks: list[pd.DataFrame] = []
    for held_out in groups:
        test_mask = all_windows[group_col] == held_out
        res = _fit_eval_fold(
            all_windows[~test_mask], all_windows[test_mask],
            feature_cols, n_estimators=200, random_state=42,
        )
        if res is None:
            continue
        row = {
            "held_out": held_out,
            "n_test": res["n_test"],
            "accuracy": res["accuracy"],
            "f1_writing": res["f1_writing"],
            "roc_auc": res["roc_auc"],
        }
        for scale, m in res["bursts"].items():
            row[f"acc_{scale}"] = m["accuracy"]
            row[f"auc_{scale}"] = m["roc_auc"]
        rows.append(row)
        oof_chunks.append(res["oof"])
    return pd.DataFrame(rows), pd.concat(oof_chunks, ignore_index=True)


def _hmm_filter_per_fold(oof: pd.DataFrame, smoothing: float = 1.0) -> pd.DataFrame:
    """Leakage-freier kausaler HMM-Forward-Filter pro Held-out-Person.

    Übergangsmatrix + Prior werden NUR aus den Labels der Train-Personen
    geschätzt (per Session, keine Phantom-Übergänge), dann Hs Sessions kausal
    dekodiert — Emission = ``proba_cal`` als Scaled-Likelihood. Spiegelt
    ``hmm_postprocess_loso._decode_person`` + dessen Leakage-Gate; eigenständig
    hier, damit der acc-only-OOF identisch verarbeitet wird wie der full-OOF.
    """
    persons = list(dict.fromkeys(oof["person_id"]))
    rows: list[dict] = []
    for held in persons:
        train = oof[oof["person_id"] != held]
        test = (oof[oof["person_id"] == held]
                .sort_values(["session_id", "t_center_ms"]).reset_index(drop=True))
        seqs = [g.sort_values("t_center_ms")["label"].to_numpy()
                for _, g in train.groupby("session_id", sort=False)]
        A = estimate_transition_matrix(seqs, smoothing=smoothing)
        priors = class_priors(train["label"].to_numpy())
        y = test["label"].to_numpy()
        filt = np.empty(len(test))
        for _, g in test.groupby("session_id", sort=False):
            idx = g.index.to_numpy()
            b = scaled_likelihoods(g["proba_cal"].to_numpy(), priors)
            filt[idx] = forward_filter(b, A, priors)[:, 1]
        pred = (filt >= 0.5).astype(int)
        try:
            auc = float(roc_auc_score(y, filt))
        except ValueError:
            auc = float("nan")
        rows.append({"held_out": held, "hmm_acc": float((pred == y).mean()),
                     "hmm_auc": auc})
    return pd.DataFrame(rows)


def _summary(tbl: pd.DataFrame, label: str) -> None:
    print(
        f"  {label:14s} @1s  acc={tbl['accuracy'].mean():.3f}±{tbl['accuracy'].std():.3f}"
        f"  AUC={tbl['roc_auc'].mean():.3f}  F1={tbl['f1_writing'].mean():.3f}"
    )
    for scale in (f"{int(s)}s" for s in BURST_SCALES_SEC):
        if f"acc_{scale}" in tbl:
            print(
                f"  {'':14s} @{scale:3s} acc={tbl[f'acc_{scale}'].mean():.3f}"
                f"  AUC={tbl[f'auc_{scale}'].mean():.3f}"
            )


def _test(full: pd.DataFrame, acc: pd.DataFrame, metric: str) -> None:
    m = full[["held_out", metric]].merge(
        acc[["held_out", metric]], on="held_out", suffixes=("_full", "_acc")
    )
    t = paired_fold_test(m[f"{metric}_full"].to_numpy(), m[f"{metric}_acc"].to_numpy())
    verdict = "SIGNIFIKANT" if t["significant"] else "n.s."
    n_worse = int((m[f"{metric}_acc"] < m[f"{metric}_full"]).sum())
    print(
        f"  {metric:12s}  full−acc: median {t['median_diff']:+.4f} "
        f"mean {t['mean_diff']:+.4f}  p={t['p_value']:.4f} → {verdict}"
        f"   ({n_worse}/{len(m)} Folds schlechter ohne Gyro)"
    )


def run(pool: str = "legacy") -> None:
    profile = _profile_for_pool(pool)
    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    frames = [_load_windows(s, profile) for s in sessions["session_id"]]
    all_windows = pd.concat(frames, ignore_index=True)
    all_windows = all_windows.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )
    all_windows = _exclude_drawing_windows(all_windows)
    all_windows = _filter_pool(all_windows, pool)

    feature_cols = [
        c for c in all_windows.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]
    acc_only_cols = [c for c in feature_cols if not _is_gyro_feature(c)]
    gyro_cols = [c for c in feature_cols if _is_gyro_feature(c)]

    # Per-session z-score once on the full set; column-wise → subset == subset-of-zscore.
    all_windows = _zscore_per_session(all_windows, feature_cols)

    group_col = "person_id"
    groups = sessions[group_col].dropna().unique().tolist()
    print(
        f"pool={pool}: {len(groups)} folds, {len(all_windows)} windows\n"
        f"features: full={len(feature_cols)}  acc-only={len(acc_only_cols)}  "
        f"(dropped {len(gyro_cols)} gyro features)\n"
    )

    full_tbl, full_oof = _run_arm(all_windows, feature_cols, groups, group_col, sessions)
    acc_tbl, acc_oof = _run_arm(all_windows, acc_only_cols, groups, group_col, sessions)

    print("=== Full IMU (accel + gyro, 88 features) ===")
    _summary(full_tbl, "full-IMU")
    print("\n=== Accelerometer only (47 features, CMSensorRecorder-kompatibel) ===")
    _summary(acc_tbl, "acc-only")

    print("\n=== Gepaarter Wilcoxon (full − acc-only, gleiche Folds) ===")
    for metric in ("accuracy", "roc_auc", "acc_30s"):
        if metric in full_tbl and metric in acc_tbl:
            _test(full_tbl, acc_tbl, metric)

    # --- HMM-Filter-Stufe: der Live-Entscheidungspfad. Schließt der kausale
    #     HMM die acc-only-Lücke? (Gyro entrauscht 1-s-Zappeln — der HMM auch.)
    full_hmm = _hmm_filter_per_fold(full_oof).rename(
        columns={"hmm_acc": "accuracy", "hmm_auc": "roc_auc"})
    acc_hmm = _hmm_filter_per_fold(acc_oof).rename(
        columns={"hmm_acc": "accuracy", "hmm_auc": "roc_auc"})

    print("\n=== HMM-Filter (kausal, leakage-frei) — der Live-Entscheidungspfad ===")
    print(f"  full-IMU + HMM   acc={full_hmm['accuracy'].mean():.3f}"
          f"±{full_hmm['accuracy'].std():.3f}  AUC={full_hmm['roc_auc'].mean():.3f}")
    print(f"  acc-only + HMM   acc={acc_hmm['accuracy'].mean():.3f}"
          f"±{acc_hmm['accuracy'].std():.3f}  AUC={acc_hmm['roc_auc'].mean():.3f}")
    print("\n  Gepaarter Wilcoxon (full+HMM − acc-only+HMM):")
    for metric in ("accuracy", "roc_auc"):
        _test(full_hmm, acc_hmm, metric)
    # Schließt der HMM die rohe Gyro-Lücke? acc-only+HMM vs. full-IMU roh@1s.
    m = acc_hmm[["held_out", "accuracy"]].merge(
        full_tbl[["held_out", "accuracy"]], on="held_out", suffixes=("_accHMM", "_fullRaw"))
    t = paired_fold_test(m["accuracy_accHMM"].to_numpy(), m["accuracy_fullRaw"].to_numpy())
    n_above = int((m["accuracy_accHMM"] >= m["accuracy_fullRaw"]).sum())
    print(f"\n  Kontext: schließt der HMM die rohe Gyro-Lücke?"
          f"\n  acc-only+HMM ({acc_hmm['accuracy'].mean():.3f}) vs. full-IMU roh@1s "
          f"({full_tbl['accuracy'].mean():.3f}): median Δ {t['median_diff']:+.4f}, "
          f"p={t['p_value']:.4f}  ({n_above}/{len(m)} Folds ≥ full-roh)")

    print("\nPer-Fold accuracy@1s:")
    cmp = full_tbl[["held_out", "accuracy"]].merge(
        acc_tbl[["held_out", "accuracy"]], on="held_out", suffixes=("_full", "_acc")
    )
    cmp["delta"] = cmp["accuracy_full"] - cmp["accuracy_acc"]
    print(cmp.sort_values("delta", ascending=False).to_string(
        index=False, float_format=lambda v: f"{v:.3f}"))

    MODELS.mkdir(exist_ok=True)
    full_tbl.to_csv(MODELS / "acc_only_full_imu_cv.csv", index=False)
    acc_tbl.to_csv(MODELS / "acc_only_cv.csv", index=False)
    full_hmm.to_csv(MODELS / "acc_only_full_imu_hmm_cv.csv", index=False)
    acc_hmm.to_csv(MODELS / "acc_only_hmm_cv.csv", index=False)
    print(f"\n→ {MODELS / 'acc_only_full_imu_cv.csv'}\n→ {MODELS / 'acc_only_cv.csv'}"
          f"\n→ {MODELS / 'acc_only_full_imu_hmm_cv.csv'}\n→ {MODELS / 'acc_only_hmm_cv.csv'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pool", choices=["legacy", "modern"], default="legacy")
    run(ap.parse_args().pool)

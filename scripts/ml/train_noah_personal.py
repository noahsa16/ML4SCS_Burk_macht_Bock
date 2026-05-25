"""Trainiert das Personal-Noah-Modell fuer die Focus-Tracker-Live-App.

Personal-Setting: nur Noahs eigene 100-Hz-Sessions (S032, S033). Same wrist,
same watch, same person, same rate wie die spaetere Live-Inference. Damit
faellt das Cross-Subject-Problem (Wrist-Baseline-Varianz) per Definition
weg und der Per-Session-Z-Score koennte ueberfluessig sein.

Ablauf:
  1) Sanity-Check via Leave-One-Session-Out (S032->S033, S033->S032) jeweils
     mit und ohne Z-Score. Datenbasierte Entscheidung, kein Bauchgefuehl.
  2) Final-Training auf beiden Sessions kombiniert.
  3) Dump zu models/rf_noah.joblib mit eingebackenem mu/sigma (falls Z-Score
     gewinnt) - damit die Live-Inference keinen User-facing Calibration-Schritt
     braucht: das Modell kennt seine eigenen Statistiken.

Output-Schema des Joblib bewahrt train_loso._train_final_model()-Struktur,
plus zusaetzlich:
  - person_id: "Noah"
  - zscore_mu / zscore_sigma: dict[feature_name -> float] oder None
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.training.train_loso import _burst_metrics  # noqa: E402

PROC = ROOT / "data" / "processed"
MODELS = ROOT / "models"
NOAH_SESSIONS_100HZ = ("S032", "S033")


def load(session_id: str) -> pd.DataFrame:
    df = pd.read_csv(PROC / f"{session_id}_windows.csv")
    df["session_id"] = session_id
    return df


def feature_cols(df: pd.DataFrame) -> list[str]:
    return [
        c for c in df.columns
        if c not in {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}
    ]


def train_and_score(
    train_df: pd.DataFrame, test_df: pd.DataFrame,
    fcols: list[str], use_zscore: bool,
) -> dict:
    if use_zscore:
        # Why: Z-Score auf TRAIN-mu/sigma anwenden (auch auf Test), nicht
        # per-session getrennt. So testen wir, ob ein eingebackenes mu/sigma
        # (das im Deployment fix ist) ueberhaupt etwas bringt.
        mu = train_df[fcols].mean()
        sigma = train_df[fcols].std().replace(0.0, 1.0).fillna(1.0)
        X_tr = ((train_df[fcols] - mu) / sigma).to_numpy()
        X_te = ((test_df[fcols] - mu) / sigma).to_numpy()
    else:
        X_tr = train_df[fcols].to_numpy()
        X_te = test_df[fcols].to_numpy()

    y_tr = train_df["label"].to_numpy()
    y_te = test_df["label"].to_numpy()

    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    clf.fit(X_tr, y_tr)
    proba = clf.predict_proba(X_te)[:, 1]
    pred = (proba >= 0.5).astype(int)
    burst = _burst_metrics(proba, y_te, test_df, scales_sec=(5.0, 10.0, 30.0))
    return {
        "acc": float(accuracy_score(y_te, pred)),
        "f1": float(f1_score(y_te, pred, zero_division=0)),
        "auc": float(roc_auc_score(y_te, proba)),
        "burst": burst,
    }


def main() -> None:
    print(f"Loading Noah's 100Hz sessions: {NOAH_SESSIONS_100HZ}")
    dfs = {s: load(s) for s in NOAH_SESSIONS_100HZ}
    fcols = feature_cols(next(iter(dfs.values())))
    print(f"Features: {len(fcols)}")
    for s, df in dfs.items():
        print(f"  {s}: {len(df)} windows   {100*df.label.mean():.1f}% writing")

    print("\n" + "=" * 70)
    print("A/B Sanity Check: Leave-One-Session-Out")
    print("=" * 70)
    print(f"{'fold':<14} {'zscore':<8} {'acc':>6} {'f1':>6} {'auc':>6}  "
          f"{'@5s_auc':>8} {'@30s_auc':>9}")

    results: dict[str, dict] = {}
    for zscore in (False, True):
        accs, f1s, aucs = [], [], []
        for held_out in NOAH_SESSIONS_100HZ:
            train = pd.concat(
                [dfs[s] for s in NOAH_SESSIONS_100HZ if s != held_out],
                ignore_index=True,
            )
            test = dfs[held_out]
            r = train_and_score(train, test, fcols, use_zscore=zscore)
            accs.append(r["acc"]); f1s.append(r["f1"]); aucs.append(r["auc"])
            print(f"{'->'+held_out:<14} {str(zscore):<8} "
                  f"{r['acc']:>6.3f} {r['f1']:>6.3f} {r['auc']:>6.3f}  "
                  f"{r['burst']['5s']['roc_auc']:>8.3f} "
                  f"{r['burst']['30s']['roc_auc']:>9.3f}")
        results[f"zscore={zscore}"] = {
            "acc_mean": float(np.mean(accs)),
            "f1_mean": float(np.mean(f1s)),
            "auc_mean": float(np.mean(aucs)),
        }
        print(f"{'mean':<14} {str(zscore):<8} "
              f"{results[f'zscore={zscore}']['acc_mean']:>6.3f} "
              f"{results[f'zscore={zscore}']['f1_mean']:>6.3f} "
              f"{results[f'zscore={zscore}']['auc_mean']:>6.3f}")
        print()

    delta_auc = results["zscore=True"]["auc_mean"] - results["zscore=False"]["auc_mean"]
    use_zscore_final = delta_auc > 0.005
    print(f"Z-Score-Effekt: AUC {delta_auc:+.3f}  ->  "
          f"final {'WITH' if use_zscore_final else 'WITHOUT'} z-score")

    print("\n" + "=" * 70)
    print("Final Training on Both Sessions")
    print("=" * 70)
    all_df = pd.concat([dfs[s] for s in NOAH_SESSIONS_100HZ], ignore_index=True)

    if use_zscore_final:
        mu = all_df[fcols].mean()
        sigma = all_df[fcols].std().replace(0.0, 1.0).fillna(1.0)
        X = ((all_df[fcols] - mu) / sigma).to_numpy()
        zscore_mu = mu.to_dict()
        zscore_sigma = sigma.to_dict()
    else:
        X = all_df[fcols].to_numpy()
        zscore_mu = None
        zscore_sigma = None

    y = all_df["label"].to_numpy()
    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced",
        random_state=42, n_jobs=-1,
    )
    clf.fit(X, y)
    print(f"Trained on {len(all_df)} windows  ({100*y.mean():.1f}% writing)")

    out = MODELS / "rf_noah.joblib"
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": clf,
        "feature_cols": fcols,
        "trained_on": list(NOAH_SESSIONS_100HZ),
        "n_windows": len(all_df),
        "person_id": "Noah",
        "sample_rate_hz": 100,
        "zscore_mu": zscore_mu,
        "zscore_sigma": zscore_sigma,
    }, out)
    print(f"-> {out}")
    print(f"   person_id=Noah  sample_rate_hz=100  "
          f"zscore={'baked-in' if use_zscore_final else 'none'}")


if __name__ == "__main__":
    main()

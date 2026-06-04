"""Feature-Ablation der 2026-05-29-Zusätze bei konstantem Probanden-Pool.

Testet zwei Feature-Hypothesen einzeln gegen den jeweils stärksten
verfügbaren Holdout:

* **#3 ``gyro_acc_energy_ratio``** (Schreiben = rotationsdominiert) ist
  pool-agnostisch → **echter N=10-Legacy-LOSO** (by person).
* **#4 ``tilt_*_std``** (Orientierungs-Stabilität) braucht Gravity →
  nur **within-S038** (eine Person, math-Holdout, *vorläufig* — bis ein
  Modern-Cohort existiert ist kein LOSO möglich).

Entscheidungskriterium (vorab fixiert, catch22-Lektion): ein Feature
nur behalten, wenn acc/AUC steigt UND die fold-σ **nicht** schlechter
wird. Eine σ-Verdopplung bei marginalem Mittelwert-Gewinn = Overfitting.

Baut Windows on-the-fly über ``load_session_windows`` (umgeht den
windows.csv-Cache), damit immer der aktuelle Feature-Code gemessen wird.

::

    python -m scripts.ml.ablate_features_loso
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, roc_auc_score

from src.features.windows import load_session_windows
from src.training.train_loso import (
    BURST_SCALES_SEC,
    _fit_eval_fold,
    _filter_pool,
    _select_sessions,
    _zscore_per_session,
)

ROOT = Path(__file__).parents[2]
REPORT = ROOT / "reports" / "feature_ablation.md"

# Die 2026-05-29-Kandidaten, getrennt nach Pool-Verfügbarkeit.
RATIO_FEATURE = "gyro_acc_energy_ratio"          # #3 — Legacy + Modern
TILT_STD_FEATURES = ["tilt_x_std", "tilt_y_std", "tilt_z_std"]  # #4 — Modern only


def _build_all_windows(sessions: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for sid in sessions["session_id"].tolist():
        df = load_session_windows(sid)
        df["session_id"] = sid
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.merge(
        sessions[["session_id", "person_id"]], on="session_id", how="left"
    )


def _feature_cols(df: pd.DataFrame) -> list[str]:
    meta = {"label", "t_center_ms", "session_id", "person_id",
            "task_id", "task_category"}
    return [c for c in df.columns if c not in meta]


def _run_loso(all_windows: pd.DataFrame, feature_cols: list[str]) -> dict:
    groups = all_windows["person_id"].dropna().unique().tolist()
    accs, aucs, f1s = [], [], []
    burst = {f"{int(s)}s": {"accuracy": [], "roc_auc": []} for s in BURST_SCALES_SEC}
    for g in groups:
        mask = all_windows["person_id"] == g
        res = _fit_eval_fold(
            all_windows[~mask], all_windows[mask], feature_cols, 200, 42
        )
        if res is None:
            continue
        accs.append(res["accuracy"])
        aucs.append(res["roc_auc"])
        f1s.append(res["f1_writing"])
        for k in burst:
            burst[k]["accuracy"].append(res["bursts"][k]["accuracy"])
            burst[k]["roc_auc"].append(res["bursts"][k]["roc_auc"])
    return {"acc": accs, "auc": aucs, "f1": f1s, "burst": burst}


def _within_session(df: pd.DataFrame, feature_cols: list[str]) -> dict:
    """Temporaler 80/20-Split mit 4-Window-Gap (wie within_session.train_rf)."""
    d = df.sort_values("t_center_ms").reset_index(drop=True)
    cut = int(len(d) * 0.8)
    tr, te = d.iloc[:cut], d.iloc[cut + 4:]
    clf = RandomForestClassifier(
        n_estimators=200, class_weight="balanced", random_state=42, n_jobs=-1
    )
    clf.fit(tr[feature_cols], tr["label"].to_numpy())
    p = clf.predict_proba(te[feature_cols])[:, 1]
    y = te["label"].to_numpy()
    return {
        "acc": float(((p >= 0.5).astype(int) == y).mean()),
        "auc": float(roc_auc_score(y, p)),
        "f1": float(f1_score(y, (p >= 0.5).astype(int), pos_label=1, zero_division=0)),
        "n_test": len(te),
        "n_writing": int(y.sum()),
    }


def _fmt_loso(tag: str, r: dict) -> str:
    acc, auc, f1 = r["acc"], r["auc"], r["f1"]
    line = (
        f"{tag}: acc {np.mean(acc):.3f} ± {np.std(acc):.3f} | "
        f"AUC {np.mean(auc):.3f} ± {np.std(auc):.3f} | F1w {np.mean(f1):.3f}"
    )
    bl = "  ".join(
        f"@{k} AUC {np.nanmean(v['roc_auc']):.3f}"
        for k, v in r["burst"].items()
    )
    return line + "\n    burst: " + bl


def main() -> None:
    sessions = _select_sessions(include_all=False, min_windows=0)
    all_windows = _build_all_windows(sessions)

    lines: list[str] = ["# Feature-Ablation 2026-05-29\n"]
    lines.append(
        "Hypothesen: #3 `gyro_acc_energy_ratio` (Rotation-Dominanz), "
        "#4 `tilt_*_std` (Orientierungs-Stabilität). Entscheidung: behalten "
        "nur bei acc/AUC↑ UND fold-σ nicht schlechter.\n"
    )

    # === #3: N=10-Legacy-LOSO (pool-agnostisches Feature) ===
    legacy = _filter_pool(all_windows.copy(), "legacy")
    full_cols = _feature_cols(legacy)
    legacy_z = _zscore_per_session(legacy, full_cols)
    base_cols = [c for c in full_cols if c != RATIO_FEATURE]

    print("=== #3 gyro_acc_energy_ratio — N=10 Legacy-LOSO (by person) ===")
    print(f"sessions={legacy['session_id'].nunique()}  "
          f"persons={legacy['person_id'].nunique()}  features={len(full_cols)}")
    r_base = _run_loso(legacy_z, base_cols)
    r_full = _run_loso(legacy_z, full_cols)
    print(_fmt_loso("  ohne #3", r_base))
    print(_fmt_loso("  mit  #3", r_full))
    d_acc = np.mean(r_full["acc"]) - np.mean(r_base["acc"])
    d_auc = np.mean(r_full["auc"]) - np.mean(r_base["auc"])
    d_sig = np.std(r_full["acc"]) - np.std(r_base["acc"])
    print(f"  Δacc={d_acc:+.4f}  ΔAUC={d_auc:+.4f}  Δσ(acc)={d_sig:+.4f}")

    lines.append("## #3 `gyro_acc_energy_ratio` — N=10 Legacy-LOSO\n")
    lines.append(f"- ohne #3 ({len(base_cols)} feat): {_fmt_loso('', r_base).strip()}")
    lines.append(f"- mit  #3 ({len(full_cols)} feat): {_fmt_loso('', r_full).strip()}")
    lines.append(f"- **Δacc {d_acc:+.4f} | ΔAUC {d_auc:+.4f} | Δσ(acc) {d_sig:+.4f}**\n")

    # === #4: within-S038 (Modern, gravity) — vorläufig, eine Person ===
    s038 = load_session_windows("S038")
    s038["session_id"] = "S038"
    s038_full = _feature_cols(s038)
    s038_base = [c for c in s038_full if c not in TILT_STD_FEATURES]

    print("\n=== #4 tilt_*_std — within-S038 (Modern, eine Person, math-Holdout) ===")
    w_base = _within_session(s038, s038_base)
    w_full = _within_session(s038, s038_full)
    print(f"  Test-Block: {w_full['n_test']} windows ({w_full['n_writing']} writing)")
    print(f"  ohne #4 ({len(s038_base)} feat): acc {w_base['acc']:.3f}  AUC {w_base['auc']:.3f}  F1w {w_base['f1']:.3f}")
    print(f"  mit  #4 ({len(s038_full)} feat): acc {w_full['acc']:.3f}  AUC {w_full['auc']:.3f}  F1w {w_full['f1']:.3f}")
    print(f"  Δacc={w_full['acc']-w_base['acc']:+.4f}  ΔAUC={w_full['auc']-w_base['auc']:+.4f}")
    print("  (vorläufig — kein LOSO, ein Subjekt, schwerster Task als Holdout)")

    lines.append("## #4 `tilt_*_std` — within-S038 (vorläufig, eine Person)\n")
    lines.append(f"- ohne #4 ({len(s038_base)} feat): acc {w_base['acc']:.3f} | AUC {w_base['auc']:.3f} | F1w {w_base['f1']:.3f}")
    lines.append(f"- mit  #4 ({len(s038_full)} feat): acc {w_full['acc']:.3f} | AUC {w_full['auc']:.3f} | F1w {w_full['f1']:.3f}")
    lines.append(f"- Δacc {w_full['acc']-w_base['acc']:+.4f} | ΔAUC {w_full['auc']-w_base['auc']:+.4f}")
    lines.append("- Kein LOSO (ein Subjekt, math-Holdout) — nicht beweiskräftig.\n")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print(f"\nReport: {REPORT}")


if __name__ == "__main__":
    main()

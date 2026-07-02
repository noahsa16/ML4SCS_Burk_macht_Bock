"""Hard-Negative-Feature-Test: senkt Gyro-Achsen-Jerk + Accel-rx-Korrelation +
Ratio-Feature (+ optional Sample-Weighting) die keyboard/phone-FPR?

Folgt dem SHAP-Diff-Befund (reports/shap_hard_negative_diff.md): rx_band_3_8 und
gyro_mag_jerk_mean_abs trennen P17s Tippen von Schreiben schon korrekt, werden
aber von lauteren Features ueberstimmt. Baut den N=20-legacy-Pool mit den 10
neuen Features (``build_windows(hard_negative_feats=True)``) und vergleicht
DREI Varianten auf denselben Fenstern:

  - base:            88 Features, kein Sample-Weight
  - hard_neg:         98 Features, kein Sample-Weight
  - hard_neg_weighted: 98 Features, keyboard/phone-Trainingsfenster 3x gewichtet

Gepaarter Wilcoxon (window + kausaler Burst@5s) je Variante gegen base.
**Zielcheck:** keyboard/phone-FPR (via `marker_fpr`) je Variante.

CLI: ``python scripts/ml/hard_negative_feature_test.py``. Output:
``reports/hard_negative_feature.md`` + ``models/hard_neg_oof_{base,hard_neg,hard_neg_weighted}.csv``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.significance import paired_fold_test  # noqa: E402
from src.features.windows import build_windows  # noqa: E402
from src.training.train_loso import _burst_metrics, _zscore_per_session  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
META = {"label", "t_center_ms", "session_id", "person_id", "task_id", "task_category"}
N_TREES, SEED = 200, 42
HARD_NEG_TASKS = ("keyboard_typing", "phone_typing")
SAMPLE_WEIGHT = 3.0

_mf_spec = importlib.util.spec_from_file_location(
    "marker_fpr", ROOT / "scripts" / "ml" / "marker_fpr.py")
marker_fpr = importlib.util.module_from_spec(_mf_spec)
_mf_spec.loader.exec_module(marker_fpr)


def _merged_source(sid: str) -> Path:
    legacy = DATA_PROC / f"{sid}_merged_legacy.csv"
    return legacy if legacy.exists() else DATA_PROC / f"{sid}_merged.csv"


def _build_pool() -> pd.DataFrame:
    """N=20-legacy-Sessions (aus loso_oof_legacy.csv) mit hard_negative_feats=True."""
    oof = pd.read_csv(MODEL_DIR / "loso_oof_legacy.csv")
    sess_person = oof[["session_id", "person_id"]].drop_duplicates()
    frames = []
    for sid, person in sess_person.itertuples(index=False):
        src = _merged_source(sid)
        if not src.exists():
            print(f"  skip {sid} (kein merged)")
            continue
        w = build_windows(pd.read_csv(src), hard_negative_feats=True)
        if w.empty:
            continue
        w["session_id"], w["person_id"] = sid, person
        frames.append(w)
        print(f"  {sid}/{person}: {len(w)} Fenster")
    return pd.concat(frames, ignore_index=True)


def _fold_row(proba, y, test_df) -> dict:
    pred = (proba >= 0.5).astype(int)
    try:
        auc = float(roc_auc_score(y, proba)) if len(np.unique(y)) > 1 else float("nan")
    except ValueError:
        auc = float("nan")
    b = _burst_metrics(proba, y, test_df)["5s"]
    return {"accuracy": float((pred == y).mean()), "roc_auc": auc,
            "acc_5s": b["accuracy"], "auc_5s": b["roc_auc"]}


def main() -> None:
    print("=== Baue N=20-legacy-Pool mit Hard-Negative-Features ===")
    allw = _build_pool()
    hard_neg_cols = [
        "rx_jerk_std", "rx_jerk_mean_abs", "ry_jerk_std", "ry_jerk_mean_abs",
        "rz_jerk_std", "rz_jerk_mean_abs", "corr_ax_rx", "corr_ay_rx",
        "corr_az_rx", "rx_ay_ratio",
    ]
    feats_all = [c for c in allw.columns if c not in META]
    feats_base = [c for c in feats_all if c not in hard_neg_cols]
    allw = _zscore_per_session(allw, feats_all)
    persons = sorted(allw["person_id"].dropna().unique())
    print(f"{len(persons)} Personen | {len(allw)} Fenster | "
          f"{len(feats_base)} baseline + {len(hard_neg_cols)} hard-negative")

    variants = {
        "base": dict(cols=feats_base, weighted=False),
        "hard_neg": dict(cols=feats_all, weighted=False),
        "hard_neg_weighted": dict(cols=feats_all, weighted=True),
    }
    rows = {k: [] for k in variants}
    oof = {k: [] for k in variants}
    for held in persons:
        tr, te = allw[allw.person_id != held], allw[allw.person_id == held]
        if te["label"].nunique() < 2:
            print(f"  Fold {held}: uebersprungen (einklassig)")
            continue
        ytr, yte = tr["label"].to_numpy(), te["label"].to_numpy()
        sw_hard = np.where(tr["task_id"].isin(HARD_NEG_TASKS), SAMPLE_WEIGHT, 1.0)
        accs = {}
        for key, cfg in variants.items():
            cols = cfg["cols"]
            sw = sw_hard if cfg["weighted"] else None
            rf = RandomForestClassifier(n_estimators=N_TREES, class_weight="balanced",
                                        random_state=SEED, n_jobs=-1)
            rf.fit(tr[cols].to_numpy(), ytr, sample_weight=sw)
            proba = rf.predict_proba(te[cols].to_numpy())[:, 1]
            rows[key].append({"held_out": held, **_fold_row(proba, yte, te)})
            oof[key].append(pd.DataFrame({
                "session_id": te["session_id"].to_numpy(), "person_id": held,
                "t_center_ms": te["t_center_ms"].to_numpy(), "label": yte,
                "proba_cal": proba}))
            accs[key] = rows[key][-1]["accuracy"]
        print(f"  Fold {held}: " + " | ".join(f"{k} {v:.3f}" for k, v in accs.items()))

    cv = {k: pd.DataFrame(v) for k, v in rows.items()}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    hard = {}
    for key in variants:
        p = MODEL_DIR / f"hard_neg_oof_{key}.csv"
        pd.concat(oof[key], ignore_index=True).to_csv(p, index=False)
        tbl = marker_fpr.build_fpr_table(pd.read_csv(p))
        kb = tbl[tbl.task_id == "keyboard_typing"]
        ph = tbl[tbl.task_id == "phone_typing"]
        hard[key] = {
            "keyboard": float(kb.n_fp.sum() / kb.n.sum()) if kb.n.sum() else float("nan"),
            "phone": float(ph.n_fp.sum() / ph.n.sum()) if ph.n.sum() else float("nan"),
        }

    _report(cv, hard)


def _sig(a, b, metric):
    m = a[["held_out", metric]].merge(b[["held_out", metric]], on="held_out",
                                      suffixes=("_a", "_b")).dropna()
    return paired_fold_test(m[f"{metric}_a"].to_numpy(), m[f"{metric}_b"].to_numpy())


def _ms(cv, m):
    return f"{cv[m].mean():.3f}±{cv[m].std(ddof=0):.3f}"


def _report(cv, hard) -> None:
    base = cv["base"]
    lines = [
        "# Hard-Negative-Feature-Test: Gyro-Achsen-Jerk + Accel-rx-Korrelation + Ratio",
        "",
        f"N=20 legacy, LOSO-by-person, {len(base)} Folds. Drei Varianten auf denselben "
        "Fenstern (base=88, hard_neg=98, hard_neg_weighted=98+3x-Sample-Weight auf "
        f"keyboard/phone-Trainingsfenstern).", "",
        "## LOSO (acc±σ / AUC)", "",
        "| Metrik | base (88) | hard_neg (98) | hard_neg_weighted (98) |",
        "|---|---|---|---|",
    ]
    for label, m in (("window", "accuracy"), ("@5s", "acc_5s")):
        auc_m = "roc_auc" if m == "accuracy" else "auc_5s"
        cells = []
        for key in ("base", "hard_neg", "hard_neg_weighted"):
            cells.append(f"{_ms(cv[key], m)} / {cv[key][auc_m].mean():.3f}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "## Signifikanz gegen base", "",
              "| Variante | Δacc (window) | Δacc (@5s) |", "|---|---|---|"]
    for key in ("hard_neg", "hard_neg_weighted"):
        sw = _sig(cv[key], base, "accuracy")
        s5 = _sig(cv[key], base, "acc_5s")
        lines.append(
            f"| {key} | median {sw['median_diff']:+.4f}, p={sw['p_value']:.4f} "
            f"({'SIG' if sw['significant'] else 'n.s.'}) | "
            f"median {s5['median_diff']:+.4f}, p={s5['p_value']:.4f} "
            f"({'SIG' if s5['significant'] else 'n.s.'}) |")
    lines += ["", "## ZIELCHECK: keyboard/phone-FPR", "",
              "| Task | base | hard_neg | hard_neg_weighted |", "|---|---|---|---|"]
    for task, key in (("keyboard_typing", "keyboard"), ("phone_typing", "phone")):
        lines.append(f"| {task} | {hard['base'][key]:.3f} | {hard['hard_neg'][key]:.3f} | "
                      f"{hard['hard_neg_weighted'][key]:.3f} |")
    lines += ["", "## Lesart", "",
              "Erfolg = keyboard/phone-FPR sinkt UND LOSO-acc nicht signifikant schlechter. "
              "hard_neg isoliert den Feature-Effekt, hard_neg_weighted zusaetzlich den "
              "Trainings-Gewichtungs-Effekt — Vergleich beider zeigt, ob neue Features oder "
              "staerkeres Gewicht auf bekannten Fenstern der wirksamere Hebel ist.", "",
              "Rohdaten: `models/hard_neg_oof_{base,hard_neg,hard_neg_weighted}.csv`.", "",
              ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "hard_negative_feature.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()

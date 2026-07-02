"""Rhythmus-Feature-Test: senkt es die keyboard/phone-FPR ohne die Headline zu schaden?

Baut den N=20-legacy-Pool mit den 4 Rhythmus-Features (``build_windows(rhythm=True)``)
und fährt LOSO-RF auf DENSELBEN Fenstern für **88 (baseline) vs 92 (rhythm)** —
perfekt kontrolliert, nur der Feature-Satz unterscheidet sich. Gepaarter Wilcoxon
(`significance.py`) auf window + kausalem Burst@5s. **Zielcheck:** die
keyboard/phone-FPR (via `marker_fpr`) mit vs. ohne Rhythmus.

CLI: ``python scripts/ml/rhythm_feature_test.py``. Output:
``reports/rhythm_feature.md`` + ``models/rhythm_oof_{base,rhythm}.csv``.
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
from src.features.rhythm import RHYTHM_FEATURE_NAMES  # noqa: E402
from src.features.windows import build_windows  # noqa: E402
from src.training.train_loso import _burst_metrics, _zscore_per_session  # noqa: E402

DATA_PROC = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
META = {"label", "t_center_ms", "session_id", "person_id", "task_id", "task_category"}
N_TREES, SEED = 200, 42

_mf_spec = importlib.util.spec_from_file_location(
    "marker_fpr", ROOT / "scripts" / "ml" / "marker_fpr.py")
marker_fpr = importlib.util.module_from_spec(_mf_spec)
_mf_spec.loader.exec_module(marker_fpr)


def _merged_source(sid: str) -> Path:
    legacy = DATA_PROC / f"{sid}_merged_legacy.csv"
    return legacy if legacy.exists() else DATA_PROC / f"{sid}_merged.csv"


def _build_pool() -> pd.DataFrame:
    """N=20-legacy-Sessions (aus loso_oof_legacy.csv) mit rhythm=True neu bauen."""
    oof = pd.read_csv(MODEL_DIR / "loso_oof_legacy.csv")
    sess_person = oof[["session_id", "person_id"]].drop_duplicates()
    frames = []
    for sid, person in sess_person.itertuples(index=False):
        src = _merged_source(sid)
        if not src.exists():
            print(f"  skip {sid} (kein merged)")
            continue
        w = build_windows(pd.read_csv(src), rhythm=True)
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
    print("=== Baue N=20-legacy-Pool mit Rhythmus-Features ===")
    allw = _build_pool()
    feats_all = [c for c in allw.columns if c not in META]
    rhythm = list(RHYTHM_FEATURE_NAMES)
    feats_base = [c for c in feats_all if c not in rhythm]
    allw = _zscore_per_session(allw, feats_all)
    persons = sorted(allw["person_id"].dropna().unique())
    print(f"{len(persons)} Personen | {len(allw)} Fenster | "
          f"{len(feats_base)} baseline + {len(rhythm)} rhythm")

    rows = {"base": [], "rhythm": []}
    oof = {"base": [], "rhythm": []}
    for held in persons:
        tr, te = allw[allw.person_id != held], allw[allw.person_id == held]
        if te["label"].nunique() < 2:
            print(f"  Fold {held}: uebersprungen (einklassig)")
            continue
        ytr, yte = tr["label"].to_numpy(), te["label"].to_numpy()
        for key, cols in (("base", feats_base), ("rhythm", feats_all)):
            rf = RandomForestClassifier(n_estimators=N_TREES, class_weight="balanced",
                                        random_state=SEED, n_jobs=-1).fit(tr[cols].to_numpy(), ytr)
            proba = rf.predict_proba(te[cols].to_numpy())[:, 1]
            rows[key].append({"held_out": held, **_fold_row(proba, yte, te)})
            oof[key].append(pd.DataFrame({
                "session_id": te["session_id"].to_numpy(), "person_id": held,
                "t_center_ms": te["t_center_ms"].to_numpy(), "label": yte,
                "proba_cal": proba}))
        print(f"  Fold {held}: base acc {rows['base'][-1]['accuracy']:.3f} | "
              f"rhythm acc {rows['rhythm'][-1]['accuracy']:.3f}")

    cv = {k: pd.DataFrame(v) for k, v in rows.items()}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    hard = {}
    for key in ("base", "rhythm"):
        p = MODEL_DIR / f"rhythm_oof_{key}.csv"
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
    b, r = cv["base"], cv["rhythm"]
    sig = {m: _sig(r, b, m) for m in ("accuracy", "roc_auc", "acc_5s", "auc_5s")}

    def sl(m):
        s = sig[m]
        return (f"Δ(rhythm−base) median {s['median_diff']:+.4f}, p={s['p_value']:.4f} "
                f"→ {'SIGNIFIKANT' if s['significant'] else 'n.s.'}")

    lines = [
        "# Rhythmus-Feature-Test: 88 vs 92 (Autokorr-Peak + spektrale Flatness)", "",
        f"N=20 legacy, LOSO-by-person, {len(b)} Folds. Perfekt kontrolliert "
        "(dieselben Fenster, nur Feature-Satz unterscheidet sich).", "",
        "## LOSO (acc±σ / AUC)", "", "| Metrik | baseline (88) | rhythm (92) | gepaart |",
        "|---|---|---|---|",
        f"| window | {_ms(b,'accuracy')} / {b['roc_auc'].mean():.3f} | "
        f"{_ms(r,'accuracy')} / {r['roc_auc'].mean():.3f} | {sl('accuracy')} |",
        f"| @5s | {_ms(b,'acc_5s')} / {b['auc_5s'].mean():.3f} | "
        f"{_ms(r,'acc_5s')} / {r['auc_5s'].mean():.3f} | {sl('acc_5s')} |", "",
        "## ZIELCHECK: keyboard/phone-FPR (sinkt sie durch Rhythmus?)", "",
        "| Task | baseline (88) | rhythm (92) | Δ |", "|---|---|---|---|",
        f"| keyboard_typing | {hard['base']['keyboard']:.3f} | "
        f"{hard['rhythm']['keyboard']:.3f} | {hard['rhythm']['keyboard']-hard['base']['keyboard']:+.3f} |",
        f"| phone_typing | {hard['base']['phone']:.3f} | "
        f"{hard['rhythm']['phone']:.3f} | {hard['rhythm']['phone']-hard['base']['phone']:+.3f} |", "",
        "## Lesart", "",
        "Erfolg = keyboard/phone-FPR **sinkt** (zielgenauer Effekt) UND LOSO-acc nicht "
        "signifikant schlechter (kein Schaden). Sinkt die FPR nicht, trennen Autokorr/"
        "Flatness Tippen nicht von Schreiben — dann ist die Verwechslung tiefer (mehr "
        "Daten/anderes Feature nötig).", "",
        "Rohdaten: `models/rhythm_oof_{base,rhythm}.csv`.", "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "rhythm_feature.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()

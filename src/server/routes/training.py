"""FastAPI-Router für das Web-Training-Cockpit (`/training/*`).

Startet/stoppt RF-LOSO-Läufe, listet die nicht-destruktive Run-Historie,
promotet einen Lauf zur Headline und lädt einen Lauf temporär in die
Live-Inference (Sandbox). RUNS_ROOT wird zur Call-Zeit gelesen, damit Tests
den Pfad monkeypatchen können.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.training import registry
from .. import training as training_mod
from .. import training_runs
from ..inference import live

router = APIRouter(prefix="/training", tags=["training"])


class StartBody(BaseModel):
    model: str = "rf"
    pool: str = "legacy"
    by: str = "person"
    zscore: bool = True
    # None = backend default (5,10,30); "" = only the 1 s base; else CSV "5,30".
    burst_scales: str | None = None
    # Feature-Build-Parameter; None = gecachte Defaults (1 s Fenster / 2500 ms gap).
    window_sec: float | None = None
    max_gap_ms: float | None = None


def _feature_group(name: str) -> str:
    """Mappt einen 88/92-Feature-Namen auf seine semantische Gruppe."""
    if "jerk" in name:
        return "jerk"
    if "zcr" in name:
        return "zcr"
    if "corr" in name:
        return "correlation"
    if "mag" in name:
        return "magnitude"
    if "tilt" in name or "grav" in name:
        return "gravity"
    if "dom_freq" in name or "spec_" in name or "band_" in name:
        return "spectral"
    return "time_stats"  # mean/std/min/max/rms/range


@router.get("/models")
def models():
    return registry.list_models()


@router.get("/pools")
def pools():
    """Probanden-/Session-Zahl je Pool (für die Live-Vorschau, N=x).

    Spiegelt die LOSO-Session-Auswahl (verdict/min-windows-Gates) und zählt die
    eindeutigen Probanden — n_subjects = Anzahl LOSO-Folds bei by-person.
    """
    # Why: lazy import — train_loso zieht sklearn; nicht beim Server-Start laden.
    from src.training import train_loso as _loso
    out = []
    for pid in ("legacy", "modern"):
        try:
            prof = _loso._profile_for_pool(pid)
            s = _loso._select_sessions(include_all=False, min_windows=0, profile=prof)
            n_subj = int(s["person_id"].nunique()) if "person_id" in s.columns else 0
            out.append({"id": pid, "n_subjects": n_subj, "n_sessions": int(len(s))})
        except Exception:
            out.append({"id": pid, "n_subjects": 0, "n_sessions": 0})
    return out


@router.get("/current")
def current():
    return training_mod.run.snapshot()


@router.post("/start")
async def start(body: StartBody):
    if not registry.validate(body.model, body.pool):
        raise HTTPException(400, f"invalid model/pool: {body.model}/{body.pool}")
    if not registry.get(body.model).enabled:
        raise HTTPException(400, f"model '{body.model}' runner not yet wired (post-MVP)")
    if training_mod.run.is_busy():
        raise HTTPException(409, "a training run is already in progress")
    return await training_mod.run.start(body.model, body.pool, body.by,
                                        body.zscore, body.burst_scales,
                                        body.window_sec, body.max_gap_ms)


@router.post("/stop")
async def stop():
    return await training_mod.run.stop()


@router.get("/runs")
def runs():
    return training_runs.list_runs(training_runs.RUNS_ROOT)


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    """Done-State-Analyse: per-fold cv, Feature-Gruppen-Importance (aggregiert
    über alle Features) und gepoolte ROC-Kurve aus den OOF-Predictions."""
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.metrics import roc_curve

    d = training_runs.RUNS_ROOT / run_id
    if not (d / "cv.csv").exists():
        raise HTTPException(404, f"run {run_id} not found")

    cv = pd.read_csv(d / "cv.csv").to_dict(orient="records")

    feature_groups: list[dict] = []
    mp = d / "model.joblib"
    if mp.exists():
        bundle = joblib.load(mp)
        clf, cols = bundle["model"], bundle["feature_cols"]
        imp = getattr(clf, "feature_importances_", None)
        if imp is not None:
            agg: dict[str, float] = {}
            for col, weight in zip(cols, imp):
                agg[_feature_group(col)] = agg.get(_feature_group(col), 0.0) + float(weight)
            feature_groups = sorted(
                ({"group": g, "imp": v} for g, v in agg.items()),
                key=lambda r: -r["imp"])

    roc: list[list[float]] = []
    oofp = d / "oof.csv"
    if oofp.exists():
        oof = pd.read_csv(oofp)
        if "label" in oof and "proba_raw" in oof and oof["label"].nunique() == 2:
            fpr, tpr, _ = roc_curve(oof["label"], oof["proba_raw"])
            idx = np.linspace(0, len(fpr) - 1, min(40, len(fpr))).astype(int)
            roc = [[float(fpr[i]), float(tpr[i])] for i in idx]

    return {"cv": cv, "feature_groups": feature_groups, "roc": roc}


@router.get("/runs/{run_id}/tasks")
def run_tasks(run_id: str, person: str | None = None):
    """FP/FN/acc je Task-Kategorie, marker-getrieben (Item ⑥ + Per-Person-Drawer).

    Kreuzt die OOF-Predictions des Laufs über ``t_center_ms`` mit den
    Study-Mode-Markern jeder Session (wiederverwendet engagement.task_timeline
    / assign_tasks). ``person`` filtert auf eine Person (Per-Person-Drill-in).
    """
    import pandas as pd
    from src.evaluation.engagement import task_timeline, assign_tasks

    oofp = training_runs.RUNS_ROOT / run_id / "oof.csv"
    if not oofp.exists():
        raise HTTPException(404, f"no oof for run {run_id}")
    oof = pd.read_csv(oofp)
    if person is not None:
        oof = oof[oof["person_id"].astype(str) == str(person)]

    assigned = []
    for sid, g in oof.groupby("session_id", sort=False):
        tl = task_timeline(sid)
        if tl.empty:
            continue
        assigned.append(assign_tasks(g, tl).dropna(subset=["task_index"]))
    if not assigned:
        return {"tasks": []}

    allrows = pd.concat(assigned, ignore_index=True)
    allrows["pred"] = (allrows["proba_raw"] >= 0.5).astype(int)
    out = []
    for task, g in allrows.groupby("task_name", sort=False):
        n = len(g)
        fp = int(((g["pred"] == 1) & (g["label"] == 0)).sum())
        fn = int(((g["pred"] == 0) & (g["label"] == 1)).sum())
        out.append({
            "task": task, "category": str(g["task_category"].iat[0]),
            "n": n, "fp": fp, "fn": fn,
            "acc": round(float((g["pred"] == g["label"]).mean()), 3),
            "fp_rate": round(fp / max(n, 1), 3),
            "fn_rate": round(fn / max(n, 1), 3),
        })
    out.sort(key=lambda r: -(r["fp"] + r["fn"]))
    return {"tasks": out}


@router.post("/runs/{run_id}/promote")
def promote(run_id: str):
    try:
        training_runs.promote(run_id, root=training_runs.RUNS_ROOT)
    except FileNotFoundError:
        raise HTTPException(404, f"run {run_id} not found")
    return {"ok": True}


@router.post("/runs/{run_id}/sandbox")
def sandbox(run_id: str):
    path = training_runs.RUNS_ROOT / run_id / "model.joblib"
    if not path.exists():
        raise HTTPException(404, f"no model.joblib for run {run_id}")
    ok = live.load_sandbox(path)
    return {"ok": ok, "model_id": "sandbox"}

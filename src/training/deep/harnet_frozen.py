"""Stufe 1 Transfer-Learning: harnet als *frozen feature extractor*.

Der Conv-Trunk (``model.feature_extractor``) des Oxford-Foundation-Models
liefert pro 5-s-Fenster ein 512-dim Embedding (harnet5) bzw. 1024-dim
(harnet10); der vortrainierte Klassifikationskopf wird abgeschnitten. Auf
den (eingefrorenen) Embeddings laeuft dann ein LOSO-by-person — identisches
Protokoll wie :mod:`src.training.train_loso` — mit zwei leichten Koepfen:

* **LogisticRegression** mit C-Sweep ``{0.01, 0.1, 1}``, gewaehlt per
  innerem GroupKFold (nach Person) auf den Trainings-Embeddings.
* **RandomForest** (200 Trees, ``class_weight='balanced'``), wie die
  RF-Headline.

Embeddings werden pro Session als ``.npz`` unter
``data/processed/embeddings/{variant}/`` gecached (gitignored, da ganz
``data/processed/`` ignoriert ist) — der teure Forward-Pass laeuft damit
einmal, der LOSO darueber ist billig.

Burst-Aggregation der Test-Wahrscheinlichkeiten ueber
:func:`src.training.train_loso._burst_metrics` (Skalen 5/10/30 s), exakt
wie RF und Deep-Sequenz-Modelle.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.training.deep.harnet_data import (
    HARNET_VARIANTS,
    load_session_harnet,
    select_harnet_sessions,
)
from src.training.train_loso import _burst_metrics

ROOT = Path(__file__).parents[3]
EMB_DIR = ROOT / "data" / "processed" / "embeddings"

HUB_REPO = "OxWearables/ssl-wearables"
LOGREG_C_GRID = (0.01, 0.1, 1.0)
RF_TREES = 200
SEED = 42

DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def _ensure_ca_bundle() -> None:
    """macOS-Framework-Python hat oft kein CA-Bundle -> torch.hub SSL-Fehler.

    certifi (transitive Dep) liefert eins; wir setzen es nur, falls noch
    nicht gesetzt. Greift nur beim ersten Lauf (Download); danach Cache.
    """
    try:
        import certifi
    except ImportError:
        return
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


def load_harnet_extractor(variant: str) -> torch.nn.Module:
    """Lade harnet (pretrained) und gib das eval-Modell zurueck.

    Der Kopf wird nicht entfernt, sondern in :func:`extract_embeddings` per
    ``model.feature_extractor`` umgangen. Lazy Download beim ersten Lauf;
    Cache-Pfad wird geloggt.
    """
    if variant not in HARNET_VARIANTS:
        raise ValueError(
            f"variant must be one of {sorted(HARNET_VARIANTS)}, got {variant!r}"
        )
    _ensure_ca_bundle()
    model = torch.hub.load(
        HUB_REPO, variant, class_num=2, pretrained=True,
        trust_repo=True, verbose=False,
    )
    model.eval().to(DEVICE)
    print(f"[harnet] {variant} geladen (device={DEVICE}); "
          f"torch.hub cache: {torch.hub.get_dir()}")
    return model


@torch.no_grad()
def extract_embeddings(
    model: torch.nn.Module, X: np.ndarray, batch_size: int = 64
) -> np.ndarray:
    """Frozen-Trunk-Embeddings fuer Fenster ``X`` (N, 3, L) -> (N, D).

    ``model.feature_extractor(x)`` gibt ``(b, D, 1)`` bei nativer
    Fensterlaenge; ``squeeze(-1)`` -> ``(b, D)``.
    """
    if len(X) == 0:
        return np.empty((0, 0), dtype=np.float32)
    out: list[np.ndarray] = []
    for i in range(0, len(X), batch_size):
        xb = torch.from_numpy(X[i:i + batch_size]).to(DEVICE)
        feat = model.feature_extractor(xb).squeeze(-1)
        out.append(feat.cpu().numpy().astype(np.float32))
    return np.concatenate(out)


def session_embeddings(
    model: torch.nn.Module,
    session_id: str,
    variant: str,
    force: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Embeddings + Labels + t_center fuer eine Session, mit .npz-Cache.

    Cache-Key ist (variant, win_samples). Bei Mismatch oder ``force`` wird
    neu berechnet.
    """
    win = HARNET_VARIANTS[variant]
    cache = EMB_DIR / variant / f"{session_id}.npz"
    if cache.exists() and not force:
        d = np.load(cache)
        if int(d["win_samples"]) == win["win_samples"]:
            return d["emb"], d["y"], d["t"]
    X, y, t = load_session_harnet(
        session_id, None, win["win_samples"], win["stride_samples"]
    )
    emb = extract_embeddings(model, X)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        cache, emb=emb, y=y, t=t,
        win_samples=np.int64(win["win_samples"]),
    )
    return emb, y, t


def _logreg_with_csweep(
    Xtr: np.ndarray, ytr: np.ndarray, groups: np.ndarray
) -> tuple[object, float]:
    """LogReg-Pipeline (StandardScaler + LogReg) mit C per innerem GroupKFold.

    Standardisierung betrifft die *Embeddings*, nicht die g-Inputs — der
    Input-Z-Score-Verbot gilt nur fuer harnet's Roh-Accel. GroupKFold nach
    Person verhindert Leakage im inneren Sweep. Returns (fitted_estimator, best_C).
    """
    n_groups = len(np.unique(groups))
    pipe = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )
    if n_groups < 2:
        pipe.fit(Xtr, ytr)
        return pipe, float("nan")
    gkf = GroupKFold(n_splits=min(3, n_groups))
    search = GridSearchCV(
        pipe,
        {"logisticregression__C": list(LOGREG_C_GRID)},
        scoring="roc_auc", cv=gkf, n_jobs=-1,
    )
    search.fit(Xtr, ytr, groups=groups)
    return search.best_estimator_, float(search.best_params_["logisticregression__C"])


def _fold_row(
    head: str, model_name: str, test_p: str,
    proba: np.ndarray, y_true: np.ndarray, test_df: pd.DataFrame,
    best_c: float,
) -> dict:
    pred = (proba >= 0.5).astype(int)
    try:
        auc = float(roc_auc_score(y_true, proba))
    except ValueError:
        auc = float("nan")
    row = {
        "model": model_name,
        "head": head,
        "held_out": test_p,
        "n_test": int(len(y_true)),
        "best_C": best_c,
        "accuracy": float((pred == y_true).mean()),
        "f1_writing": float(f1_score(y_true, pred, pos_label=1, zero_division=0)),
        "roc_auc": auc,
    }
    for scale, bm in _burst_metrics(proba, y_true, test_df).items():
        row[f"acc_{scale}"] = bm["accuracy"]
        row[f"auc_{scale}"] = bm["roc_auc"]
    return row


def harnet_loso(variant: str = "harnet5", force_embeddings: bool = False) -> pd.DataFrame:
    """LOSO-by-person auf frozen-harnet-Embeddings, zwei Koepfe. Per-fold-Tabelle.

    Pro Fold: Test = 1 Person, Train = alle uebrigen (C-Sweep per innerem
    GroupKFold). Kein separater Val-Holdout noetig — die Koepfe sind leicht.
    """
    if variant not in HARNET_VARIANTS:
        raise ValueError(
            f"variant must be one of {sorted(HARNET_VARIANTS)}, got {variant!r}"
        )
    np.random.seed(SEED)
    model = load_harnet_extractor(variant)
    sessions = select_harnet_sessions(pool="legacy")
    if sessions.empty:
        raise RuntimeError("Keine Sessions -- sessions.csv / verdict-Gate pruefen.")

    # Embeddings je Session (cached) sammeln.
    data: dict[str, dict] = {}
    for row in sessions.itertuples():
        sid = row.session_id
        emb, y, t = session_embeddings(model, sid, variant, force=force_embeddings)
        if len(emb) == 0:
            print(f"  skip {sid} -- keine Fenster")
            continue
        data[sid] = {"emb": emb, "y": y, "t": t, "person_id": row.person_id}
        print(f"  {sid}: {emb.shape[0]} Fenster -> {emb.shape[1]}-dim Embedding")

    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)
    if len(person_ids) < 3:
        raise RuntimeError(
            f"LOSO braucht >= 3 Personen, hat {len(person_ids)}."
        )

    print(f"\n=== {variant} frozen | {len(person_ids)} Folds | device={DEVICE} ===")
    rows: list[dict] = []
    for test_p in person_ids:
        train_ps = [p for p in person_ids if p != test_p]
        Xtr = np.concatenate([data[s]["emb"] for p in train_ps for s in persons[p]])
        ytr = np.concatenate([data[s]["y"] for p in train_ps for s in persons[p]])
        groups = np.concatenate([
            np.full(len(data[s]["y"]), p)
            for p in train_ps for s in persons[p]
        ])
        Xte = np.concatenate([data[s]["emb"] for s in persons[test_p]])
        yte = np.concatenate([data[s]["y"] for s in persons[test_p]])
        test_df = pd.concat([
            pd.DataFrame({"session_id": s, "t_center_ms": data[s]["t"]})
            for s in persons[test_p]
        ], ignore_index=True)

        if len(np.unique(yte)) < 2:
            print(f"  Fold {test_p}: uebersprungen -- Test-Fold einklassig")
            continue

        # Kopf 1: LogReg mit C-Sweep.
        lr, best_c = _logreg_with_csweep(Xtr, ytr, groups)
        proba_lr = lr.predict_proba(Xte)[:, 1]
        rows.append(_fold_row("logreg", variant, test_p, proba_lr, yte, test_df, best_c))

        # Kopf 2: RandomForest.
        rf = RandomForestClassifier(
            n_estimators=RF_TREES, class_weight="balanced",
            random_state=SEED, n_jobs=-1,
        )
        rf.fit(Xtr, ytr)
        proba_rf = rf.predict_proba(Xte)[:, 1]
        rows.append(_fold_row("rf", variant, test_p, proba_rf, yte, test_df, float("nan")))

        print(f"  Fold {test_p}: logreg acc={rows[-2]['accuracy']:.3f} "
              f"auc={rows[-2]['roc_auc']:.3f} (C={best_c}) | "
              f"rf acc={rows[-1]['accuracy']:.3f} auc={rows[-1]['roc_auc']:.3f}")

    return pd.DataFrame(rows)

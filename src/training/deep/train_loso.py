"""LOSO-Cross-Validation fuer die Deep-Sequenz-Modelle.

Spiegelt :mod:`src.training.train_loso` (RF-Headline): identische
Session-Auswahl und identische Burst-Aggregation, damit der Vergleich
fair ist. Statt eines RF wird pro Fold ein Torch-Modell mit Early
Stopping auf einem Person-Holdout trainiert.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score, roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

from src.training.deep.data import load_session_raw
from src.training.deep.models import MODELS
from src.training.train_loso import _burst_metrics, _select_sessions

ROOT = Path(__file__).parents[3]
MODEL_DIR = ROOT / "models"

# window-sec -> Sample-Anzahl bei 50 Hz.
WIN_SEQ_LEN: dict[int, int] = {1: 50, 5: 250}

DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def _set_seed(seed: int = 42) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def train_one_model(
    model: torch.nn.Module,
    train_X: np.ndarray,
    train_y: np.ndarray,
    val_X: np.ndarray,
    val_y: np.ndarray,
    max_epochs: int = 60,
    patience: int = 8,
    batch_size: int = 64,
    lr: float = 1e-3,
) -> torch.nn.Module:
    """Trainiere ein Modell mit Early Stopping auf Val-ROC-AUC.

    Das beste Modell (hoechste Val-AUC) wird am Ende zurueckgeladen.
    ``pos_weight`` gleicht die Klassen-Imbalance aus (Pendant zu
    ``class_weight='balanced'`` beim RF).
    """
    model = model.to(DEVICE)
    n_pos = float((train_y == 1).sum())
    n_neg = float((train_y == 0).sum())
    pos_weight = torch.tensor([n_neg / max(n_pos, 1.0)], device=DEVICE)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    ds = TensorDataset(
        torch.from_numpy(train_X),
        torch.from_numpy(train_y.astype(np.float32)),
    )
    # drop_last: BatchNorm1d kollabiert bei Batch-Groesse 1.
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_Xt = torch.from_numpy(val_X).to(DEVICE)

    best_auc = -1.0
    best_state: dict | None = None
    epochs_since_best = 0

    for _ in range(max_epochs):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            val_logits = model(val_Xt).cpu().numpy()
        try:
            val_auc = roc_auc_score(val_y, val_logits)
        except ValueError:
            val_auc = 0.0

        if val_auc > best_auc:
            best_auc = val_auc
            best_state = {
                k: v.detach().cpu().clone() for k, v in model.state_dict().items()
            }
            epochs_since_best = 0
        else:
            epochs_since_best += 1
            if epochs_since_best >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def predict_proba(model: torch.nn.Module, X: np.ndarray) -> np.ndarray:
    """Sigmoid-Wahrscheinlichkeiten fuer die positive Klasse (writing)."""
    model.eval()
    with torch.no_grad():
        logits = model(torch.from_numpy(X).to(DEVICE))
        return torch.sigmoid(logits).cpu().numpy()


def fold_metrics(
    proba: np.ndarray,
    y_true: np.ndarray,
    test_df: pd.DataFrame,
) -> dict:
    """1-s-Metriken + Burst-Aggregation (@5/10/30 s) fuer einen Test-Fold.

    ``test_df`` braucht die Spalten ``session_id`` und ``t_center_ms`` --
    :func:`src.training.train_loso._burst_metrics` glaettet pro Session.
    """
    pred = (proba >= 0.5).astype(int)
    try:
        auc = float(roc_auc_score(y_true, proba))
    except ValueError:
        auc = float("nan")
    return {
        "accuracy": float((pred == y_true).mean()),
        "f1_writing": float(f1_score(y_true, pred, pos_label=1, zero_division=0)),
        "roc_auc": auc,
        "bursts": _burst_metrics(proba, y_true, test_df),
    }


def _load_all_sessions(
    sessions: pd.DataFrame, seq_len: int, max_gap_ms: float
) -> dict[str, dict]:
    """Lade alle Sessions als rohe Sequenz-Windows.

    Returns ``{session_id: {"X", "y", "t", "person_id"}}``.
    """
    out: dict[str, dict] = {}
    for row in sessions.itertuples():
        sid = row.session_id
        X, y, t = load_session_raw(sid, seq_len, max_gap_ms=max_gap_ms)
        if len(X) == 0:
            print(f"  skip {sid} -- keine Fenster")
            continue
        out[sid] = {"X": X, "y": y, "t": t, "person_id": row.person_id}
    return out


def _stack_persons(
    plist: list[str],
    key: str,
    data: dict[str, dict],
    persons: dict[str, list[str]],
) -> np.ndarray:
    """Konkateniere ``data[session][key]`` ueber alle Sessions der Personen in ``plist``."""
    return np.concatenate([data[s][key] for p in plist for s in persons[p]])


def train_deep_loso(
    model_name: str,
    window_sec: int,
    include_all: bool = False,
    max_gap_ms: float = 2500.0,
    seed: int = 42,
) -> pd.DataFrame:
    """LOSO-by-person fuer ein Deep-Modell. Returns per-fold Metrik-Tabelle.

    Pro Fold: Test = 1 Person, Val = 1 rotierende Person, Train = Rest.
    """
    _set_seed(seed)
    seq_len = WIN_SEQ_LEN[window_sec]
    # Why: min_windows=0 -- das Deep-Pipeline baut Fenster direkt aus der
    # merged CSV, nicht aus dem gecachten {session}_windows.csv; der
    # windows-Count-Gate ist hier gegenstandslos.
    sessions = _select_sessions(include_all=include_all, min_windows=0)
    if sessions.empty:
        raise RuntimeError("Keine Sessions -- sessions.csv / verdict-Gate pruefen.")

    data = _load_all_sessions(sessions, seq_len, max_gap_ms)
    # person_id -> Liste von session_ids
    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)
    if len(person_ids) < 3:
        raise RuntimeError(
            f"LOSO mit Val-Holdout braucht >= 3 Personen, hat {len(person_ids)}."
        )

    print(
        f"\n=== {model_name.upper()} | {window_sec}s-Fenster ({seq_len} Samples) "
        f"| {len(person_ids)} Folds | device={DEVICE} ==="
    )

    rows: list[dict] = []
    for i, test_p in enumerate(person_ids):
        # Val: naechste Person in sortierter Reihenfolge, wrap-around --
        # jede Person ist genau einmal Test und genau einmal Val.
        val_p = person_ids[(i + 1) % len(person_ids)]
        train_ps = [p for p in person_ids if p not in (test_p, val_p)]

        train_X = _stack_persons(train_ps, "X", data, persons)
        train_y = _stack_persons(train_ps, "y", data, persons)
        val_X = _stack_persons([val_p], "X", data, persons)
        val_y = _stack_persons([val_p], "y", data, persons)
        test_X = _stack_persons([test_p], "X", data, persons)
        test_y = _stack_persons([test_p], "y", data, persons)

        if len(np.unique(test_y)) < 2:
            print(f"  Fold {test_p}: uebersprungen -- Test-Fold einklassig")
            continue

        # test_df fuer die per-Session-Burst-Aggregation.
        test_df = pd.concat(
            [
                pd.DataFrame({
                    "session_id": s,
                    "t_center_ms": data[s]["t"],
                })
                for s in persons[test_p]
            ],
            ignore_index=True,
        )

        model = MODELS[model_name]()
        model = train_one_model(model, train_X, train_y, val_X, val_y)
        proba = predict_proba(model, test_X)
        m = fold_metrics(proba, test_y, test_df)

        row = {
            "model": model_name,
            "window_sec": window_sec,
            "held_out": test_p,
            "n_test": len(test_y),
            "accuracy": m["accuracy"],
            "f1_writing": m["f1_writing"],
            "roc_auc": m["roc_auc"],
        }
        for scale, bm in m["bursts"].items():
            row[f"acc_{scale}"] = bm["accuracy"]
            row[f"auc_{scale}"] = bm["roc_auc"]
        rows.append(row)
        print(
            f"  Fold {test_p}: acc={m['accuracy']:.3f} "
            f"f1={m['f1_writing']:.3f} auc={m['roc_auc']:.3f}  "
            f"(@30s acc={m['bursts']['30s']['accuracy']:.3f} "
            f"auc={m['bursts']['30s']['roc_auc']:.3f})"
        )

    return pd.DataFrame(rows)

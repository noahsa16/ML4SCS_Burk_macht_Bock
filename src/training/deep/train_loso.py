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
from sklearn.metrics import confusion_matrix, f1_score, roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

try:
    from tqdm import tqdm
except ImportError:  # tqdm optional -> Fallback = Identitaet (kein Balken)
    def tqdm(iterable=None, **_kw):
        return iterable

from src.training import events as _events
from src.training.deep.augment import Augmenter
from src.training.deep.data import load_session_raw
from src.training.deep.models import MODELS
from src.training.train_loso import _burst_metrics, _select_sessions

ROOT = Path(__file__).parents[3]
MODEL_DIR = ROOT / "models"

# Sample-Rate je Pool (Hz). seq_len/stride werden hieraus abgeleitet statt
# 50 Hz hart anzunehmen — ein 1-s-Fenster ist 50 Samples im Legacy-Pool und
# 100 im Modern-Pool. Kein "auto": rohe Sequenzen koennen keine fs mischen.
POOL_FS: dict[str, int] = {"legacy": 50, "modern": 100}
# Pool -> natives watch_profile (sessions.csv) der Pool-eigenen Sessions.
# Legacy-Pool zieht zusaetzlich Modern-Sessions als 50-Hz-View mit.
_POOL_NATIVE_PROFILE: dict[str, str] = {"legacy": "50hz", "modern": "100hz_grav"}

DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def _set_seed(seed: int = 42) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def _pool_plan(sessions: pd.DataFrame, pool: str) -> dict[str, str | None]:
    """Map jede Session auf den merged-CSV-Suffix fuer diesen Pool.

    ``legacy`` will ueberall 50 Hz: nativ-50-Hz-Sessions (``watch_profile``
    == '50hz') laden ihre native ``{sid}_merged.csv`` (Suffix ``None``),
    100-Hz-Sessions die downsampled ``{sid}_merged_legacy.csv``-View
    (Suffix ``"legacy"``). ``modern`` nimmt nur native 100hz_grav-Sessions
    (Suffix ``None``); die Session-Auswahl hat das schon erzwungen.
    """
    if pool not in POOL_FS:
        raise ValueError(f"pool must be one of {sorted(POOL_FS)}, got {pool!r}")
    if "watch_profile" not in sessions.columns:
        raise ValueError(
            "sessions.csv fehlt die 'watch_profile'-Spalte — Quality-Refresh "
            "laufen lassen (Stop/Refresh schreibt sie)."
        )
    native = _POOL_NATIVE_PROFILE[pool]
    plan: dict[str, str | None] = {}
    for row in sessions.itertuples():
        prof = getattr(row, "watch_profile", None)
        # Native Form == Pool-Profil -> native merged; sonst Legacy-View.
        plan[row.session_id] = None if prof == native else "legacy"
    return plan


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
    weight_decay: float = 0.0,
    augmenter=None,
    on_epoch=None,
) -> tuple[torch.nn.Module, int]:
    """Trainiere ein Modell mit Early Stopping auf Val-ROC-AUC.

    Das beste Modell (hoechste Val-AUC) wird am Ende zurueckgeladen.
    ``pos_weight`` gleicht die Klassen-Imbalance aus (Pendant zu
    ``class_weight='balanced'`` beim RF).

    Returns ``(model, best_epoch)`` -- ``best_epoch`` (0-indexiert) ist die
    Epoche, in der die beste Val-AUC erreicht wurde, fuer die Under-/
    Overfit-Diagnose. ``-1`` falls keine Epoche je besser als der Startwert
    war (sollte praktisch nicht vorkommen).
    """
    model = model.to(DEVICE)
    n_pos = float((train_y == 1).sum())
    n_neg = float((train_y == 0).sum())
    pos_weight = torch.tensor([n_neg / max(n_pos, 1.0)], device=DEVICE)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    ds = TensorDataset(
        torch.from_numpy(train_X),
        torch.from_numpy(train_y.astype(np.float32)),
    )
    # drop_last: BatchNorm1d kollabiert bei Batch-Groesse 1.
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_Xt = torch.from_numpy(val_X).to(DEVICE)

    best_auc = -1.0
    best_epoch = -1
    best_state: dict | None = None
    epochs_since_best = 0

    for epoch in range(max_epochs):
        model.train()
        loss_sum, n_batches = 0.0, 0
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            if augmenter is not None:
                xb = augmenter(xb)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
            loss_sum += float(loss.item()); n_batches += 1

        model.eval()
        with torch.no_grad():
            val_logits = model(val_Xt).cpu().numpy()
        try:
            val_auc = roc_auc_score(val_y, val_logits)
        except ValueError:
            val_auc = 0.0

        # Why: echte Per-Epochen-Werte fürs Cockpit (Loss-Kurve der Deep-Modelle).
        # NaN/Inf abfangen (val_auc ist NaN bei einklassiger Val-Person) — sonst
        # bräche das ein WS-Tick-JSON (JSON kennt kein NaN).
        if on_epoch is not None:
            ep_loss = loss_sum / max(n_batches, 1)
            ep_auc = float(val_auc)
            on_epoch(epoch,
                     float(ep_loss) if np.isfinite(ep_loss) else 0.0,
                     ep_auc if np.isfinite(ep_auc) else 0.0)

        if val_auc > best_auc:
            best_auc = val_auc
            best_epoch = epoch
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
    return model, best_epoch


def _acc_auc(proba: np.ndarray, y_true: np.ndarray) -> tuple[float, float]:
    """Accuracy + ROC-AUC aus Wahrscheinlichkeiten -- fuer die Train/Val-Diagnose.

    Schlankere Variante von :func:`fold_metrics` ohne Burst-Aggregation:
    Train- und Val-Set brauchen kein Decision-Window, nur den rohen
    Generalisierungs-Gap.
    """
    pred = (proba >= 0.5).astype(int)
    acc = float((pred == y_true).mean())
    try:
        auc = float(roc_auc_score(y_true, proba))
    except ValueError:
        auc = float("nan")
    return acc, auc


def predict_proba(
    model: torch.nn.Module, X: np.ndarray, batch_size: int = 512
) -> np.ndarray:
    """Sigmoid-Wahrscheinlichkeiten fuer die positive Klasse (writing).

    Why: gebatcht statt Single-Shot — der volle Train-Split in einem
    Forward materialisiert beim Transformer Batch x Heads x L x L
    Attention (~40 GB bei ~20k 5-s-Fenstern) und OOMt den CI-Runner.
    """
    model.eval()
    out: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(0, len(X), batch_size):
            xb = torch.from_numpy(X[i:i + batch_size]).to(DEVICE)
            out.append(torch.sigmoid(model(xb)).cpu().numpy())
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)


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
    sessions: pd.DataFrame,
    seq_len: int,
    stride: int,
    plan: dict[str, str | None],
    max_gap_ms: float,
    exclude_boundary: tuple[float, float] | None = None,
    zscore: bool = False,
) -> dict[str, dict]:
    """Lade alle Sessions als rohe Sequenz-Windows.

    ``plan`` mappt session_id -> merged-Suffix (siehe :func:`_pool_plan`).
    Eine fehlende Legacy-View fuehrt zu Skip-mit-Hinweis, nicht zum Crash —
    kein stilles Mischen von Sample-Raten. ``zscore`` reicht den
    Per-Session-Z-Score-Schalter an :func:`load_session_raw` durch.

    Returns ``{session_id: {"X", "y", "t", "person_id"}}``.
    """
    out: dict[str, dict] = {}
    for row in sessions.itertuples():
        sid = row.session_id
        try:
            X, y, t = load_session_raw(
                sid, seq_len,
                merged_suffix=plan[sid],
                zscore=zscore,
                stride=stride,
                max_gap_ms=max_gap_ms,
                exclude_boundary=exclude_boundary,
            )
        except FileNotFoundError as exc:
            print(f"  skip {sid} -- {exc}")
            continue
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
    pool: str = "legacy",
    include_all: bool = False,
    max_gap_ms: float = 2500.0,
    seed: int = 42,
    lr: float = 1e-3,
    dropout: float | None = None,
    batch_size: int = 64,
    weight_decay: float = 0.0,
    patience: int = 8,
    max_epochs: int = 60,
    exclude_boundary: tuple[float, float] | None = None,
    zscore: bool = False,
    augment: bool = False,
    on_event=None,
    run_dir: Path | None = None,
) -> pd.DataFrame:
    """LOSO-by-person fuer ein Deep-Modell. Returns per-fold Metrik-Tabelle.

    ``pool`` ∈ {"legacy", "modern"} waehlt Sample-Rate, Session-Menge und
    merged-Quelle (siehe :func:`_pool_plan`). Bewusst kein ``auto`` — rohe
    Sequenzen koennen keine Sample-Raten mischen.

    Pro Fold: Test = 1 Person, Val = 1 rotierende Person, Train = Rest.

    ``zscore`` (default **False**): per-Session-Z-Score vor dem Training.
    Default aus — fuers CNN empirisch neutral (gepaartes A/B, N=14: Δacc
    −0.002, p=0.65) und ohne ist das Modell direkt deploybar (keine
    Kalibrierphase). ``True`` schaltet ihn ein.

    ``exclude_boundary`` wird an :func:`build_raw_windows` durchgereicht —
    fuer das Label-Qualitaets-Experiment (mehrdeutige Uebergangs-Fenster
    ausschliessen).

    ``on_event`` / ``run_dir`` verdrahten den Lauf ins Web-Training-Cockpit
    (Muster wie :func:`src.training.train_loso.train_loso`). ``on_event``
    bekommt run_start/fold_start/fold_end/run_end-Events; ``run_dir`` (wenn
    gesetzt) erhaelt ``cv.csv`` + ``oof.csv``. Bewusst **kein**
    ``model.joblib`` — Deep-Laeufe sind eval-only (nicht promotebar/sandbox-
    faehig, weil die Live-Inferenz nur sklearn laedt). Ohne beide Parameter
    ist das CLI-Verhalten unveraendert.
    """
    if pool not in POOL_FS:
        raise ValueError(f"pool must be one of {sorted(POOL_FS)}, got {pool!r}")
    _set_seed(seed)
    fs = POOL_FS[pool]
    seq_len = window_sec * fs
    stride = fs // 2  # 0,5 s, wie der RF-Window-Stride
    profile = _POOL_NATIVE_PROFILE[pool]
    # Why: profile reicht den windows-Existenz-Gate in _select_sessions an den
    # Pool-Ordner durch — S038-S041 qualifizieren ueber ihre 50hz-Views,
    # study_mode='test' und verdict-skip fliegen wie beim RF-LOSO raus.
    # min_windows=0 schaltet nur den Count-Gate aus; die Deep-Pipeline baut
    # Fenster direkt aus der merged CSV, nicht aus der windows-CSV.
    sessions = _select_sessions(
        include_all=include_all, min_windows=0, profile=profile
    )
    if sessions.empty:
        raise RuntimeError(
            f"Keine Sessions fuer pool={pool!r} -- sessions.csv / verdict-Gate / "
            f"windows/{profile}/ pruefen."
        )

    plan = _pool_plan(sessions, pool)
    data = _load_all_sessions(
        sessions, seq_len, stride, plan, max_gap_ms, exclude_boundary,
        zscore=zscore,
    )
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
        f"\n=== {model_name.upper()} | pool={pool} | {window_sec}s-Fenster "
        f"({seq_len} Samples @ {fs} Hz) | zscore={zscore} | "
        f"{len(person_ids)} Folds | device={DEVICE} ==="
    )

    emit = on_event if on_event is not None else (lambda _ev: None)
    emit({"type": _events.RUN_START, "model": model_name, "by": "person",
          "pool": pool, "n_folds": len(person_ids)})

    rows: list[dict] = []
    oof_frames: list[pd.DataFrame] = []
    interrupted = False
    for i, test_p in enumerate(
        tqdm(person_ids, desc=f"{model_name}/{pool} folds", unit="fold")
    ):
        emit({"type": _events.FOLD_START, "idx": i, "person": str(test_p)})
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

        # Why: SIGINT (Stop-Knopf) faengt im torch-Trainingsloop -- fertige
        # Folds finalisieren statt hart abbrechen, wie der RF-Runner.
        try:
            model = (MODELS[model_name]() if dropout is None
                     else MODELS[model_name](dropout=dropout))
            # Why: eigener Aug-RNG pro Fold (seed-abgeleitet, order-unabhaengig);
            # getrennt vom globalen RNG, damit Init+Shuffle bei gleichem Seed
            # zwischen aug/no-aug identisch bleiben -> sauber gepaart.
            # Richerer Augment-Satz: scale+rotate (staerker) + jitter + magnitude
            # + time_warp. time_warp greift die Schreibgeschwindigkeit (Soft-Writer)
            # an, die scale/rotate nicht beruehren.
            augmenter = (
                Augmenter(
                    seed=seed * 1000 + i,
                    scale=True, rotate=True, jitter=True, magnitude=True, time_warp=True,
                    scale_range=(0.7, 1.3), max_deg=20.0,
                )
                if augment else None
            )
            model, best_epoch = train_one_model(
                model, train_X, train_y, val_X, val_y,
                lr=lr, batch_size=batch_size, weight_decay=weight_decay,
                patience=patience, max_epochs=max_epochs,
                augmenter=augmenter,
                on_epoch=lambda e, l, a, _i=i: emit(
                    {"type": _events.EPOCH, "fold": _i, "epoch": e,
                     "loss": l, "val_auc": a}))

            # Under-/Overfit-Diagnose: Train- und Val-Metriken am besten Modell.
            # train_acc misst Fit auf die 8 Trainings-Personen, val_acc auf die
            # rotierende Holdout-Person, accuracy (unten) auf die Test-Person.
            # Gap train>>val~test => data-limited; train>>val>>test => Overfit.
            train_acc, train_auc = _acc_auc(predict_proba(model, train_X), train_y)
            val_acc, val_auc = _acc_auc(predict_proba(model, val_X), val_y)

            proba = predict_proba(model, test_X)
            m = fold_metrics(proba, test_y, test_df)
        except KeyboardInterrupt:
            print("\n[stop] KeyboardInterrupt -- finalisiere fertige Folds…")
            interrupted = True
            break

        row = {
            "model": model_name,
            "window_sec": window_sec,
            "held_out": test_p,
            "n_test": len(test_y),
            "accuracy": m["accuracy"],
            "f1_writing": m["f1_writing"],
            "roc_auc": m["roc_auc"],
            "train_acc": train_acc,
            "train_auc": train_auc,
            "val_acc": val_acc,
            "val_auc": val_auc,
            "best_epoch": best_epoch,
        }
        for scale, bm in m["bursts"].items():
            row[f"acc_{scale}"] = bm["accuracy"]
            row[f"auc_{scale}"] = bm["roc_auc"]
        rows.append(row)
        # OOF fuer ROC-Kurve + Fehler-nach-Task im Cockpit-Drawer. proba/test_y
        # liegen in derselben Reihenfolge wie test_df (beide ueber persons[test_p]
        # gestackt) -> spaltenweise ausrichtbar.
        oof_frames.append(pd.DataFrame({
            "label": test_y,
            "proba_raw": proba,
            "session_id": test_df["session_id"].to_numpy(),
            "person_id": test_p,
            "t_center_ms": test_df["t_center_ms"].to_numpy(),
        }))

        pred = (proba >= 0.5).astype(int)
        cm = confusion_matrix(test_y, pred, labels=[0, 1])
        emit({"type": _events.FOLD_END, "idx": i, "person": str(test_p),
              "n": len(person_ids), "acc": m["accuracy"], "auc": m["roc_auc"],
              "f1": m["f1_writing"],
              "burst": {scale: bm["accuracy"] for scale, bm in m["bursts"].items()},
              "confusion": {"tn": int(cm[0, 0]), "fp": int(cm[0, 1]),
                            "fn": int(cm[1, 0]), "tp": int(cm[1, 1])}})
        print(
            f"  Fold {test_p}: train={train_acc:.3f} val={val_acc:.3f} "
            f"test={m['accuracy']:.3f}  f1={m['f1_writing']:.3f} "
            f"auc={m['roc_auc']:.3f}  best_epoch={best_epoch}"
        )

    folds_df = pd.DataFrame(rows)
    _emit_run_end(emit, folds_df, oof_frames, run_dir, interrupted)
    return folds_df


def _emit_run_end(
    emit,
    folds_df: pd.DataFrame,
    oof_frames: list[pd.DataFrame],
    run_dir: Path | None,
    interrupted: bool,
) -> None:
    """Schreibt cv.csv/oof.csv (wenn run_dir) und emittiert das run_end-Event.

    Summary-Felder spiegeln den RF-Runner (mean_acc/std_acc/auc/f1/burst), damit
    ``TrainingRun._handle_event`` Deep- und RF-Laeufe gleich behandelt. Kein
    ``model.joblib`` -- Deep-Laeufe sind eval-only.
    """
    if not folds_df.empty:
        mean_acc = float(folds_df["accuracy"].mean())
        std_acc = float(folds_df["accuracy"].std(ddof=0))
        mean_auc = float(folds_df["roc_auc"].mean())
        mean_f1 = float(folds_df["f1_writing"].mean())
        burst = {scale: float(folds_df[f"acc_{scale}"].mean())
                 for scale in ("5s", "10s", "30s") if f"acc_{scale}" in folds_df}
    else:
        mean_acc = std_acc = mean_auc = mean_f1 = 0.0
        burst = {}

    if run_dir is not None and not folds_df.empty:
        run_dir.mkdir(parents=True, exist_ok=True)
        folds_df.to_csv(run_dir / "cv.csv", index=False)
        pd.concat(oof_frames, ignore_index=True).to_csv(
            run_dir / "oof.csv", index=False)

    emit({"type": _events.RUN_END, "partial": interrupted,
          "n_done": int(len(folds_df)),
          "mean_acc": mean_acc, "std_acc": std_acc,
          "auc": mean_auc, "f1": mean_f1, "burst": burst,
          "out_dir": str(run_dir) if run_dir else ""})

"""Rocket-LOSO — Convolutional-Transform-Baselines neben RF und den Deep-Netzen.

Verallgemeinert das MiniRocket-Bein (``minirocket_loso.py``) auf drei
Rocket-artige Transforms, wählbar per ``--transform``:

* ``minirocket``  — aeon ``MiniRocket`` (≈9996 Features bei Paper-Kernelzahl).
* ``multirocket`` — aeon ``MultiRocket`` (MiniRocket + 3 zusätzliche Pooling-
  Operatoren pro Kernel, ~4 Features/Kernel; deutlich reicherer Feature-Raum).
* ``hydra``       — aeon ``HydraTransformer`` (torch-basiert; Wettbewerbe von
  Kernel-Gruppen, zählt pro Dilation welcher Kernel am stärksten antwortet).

Alle drei transformieren die rohen ``(N, 6, seq_len)``-Sequenz-Fenster
(derselbe ``build_raw_windows``-Pfad wie die Deep-Modelle) und klassifizieren
mit **derselben** standardisierten, klassen-gewichteten LogisticRegression.
Wiederverwendet die Deep-Loader (``_select_sessions`` / ``_pool_plan`` /
``_load_all_sessions``) und den **kausalen** ``_burst_metrics`` der
RF-Headline — gleiche Sessions, gleiche Folds, gleiche Decision-Skalen, damit
der Vergleich fair ist.

Warum Transformer + LogReg statt der aeon-``*Classifier``-Wrapper: deren
Default-Estimator ist ``RidgeClassifierCV`` ohne ``predict_proba`` — ROC-AUC
und die Burst-Glättung brauchen aber einen kontinuierlichen Score. Bei ~22k
Trainings-Fenstern ist LogReg ohnehin die von der Rocket-Literatur empfohlene
Wahl (statt Ridge im Small-Data-Regime).

``--n-kernels`` mappt auf ``MiniRocket``/``MultiRocket`` (dort heißt der
Kernel-Parameter ``n_kernels``); für ``hydra`` bedeutet ``n_kernels`` etwas
anderes (Kernel *pro Gruppe*, Default 8) — dort wird der aeon-Default genutzt
und ``--n-kernels`` ignoriert.

CLI::

    python scripts/ml/rocket_loso.py --transform multirocket --window-sec 5
    python scripts/ml/rocket_loso.py --transform hydra --window-sec 5 --save-cv models/hydra_win5_cv.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from aeon.transformations.collection.convolution_based import (  # noqa: E402
    HydraTransformer,
    MiniRocket,
    MultiRocket,
)
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import f1_score, roc_auc_score  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from src.training.deep.train_loso import (  # noqa: E402
    POOL_FS,
    _POOL_NATIVE_PROFILE,
    _load_all_sessions,
    _pool_plan,
    _stack_persons,
)
from src.training.train_loso import _burst_metrics, _select_sessions  # noqa: E402

TRANSFORMS = ("minirocket", "multirocket", "hydra")
_LABELS = {"minirocket": "MiniRocket", "multirocket": "MultiRocket", "hydra": "Hydra"}

# RF-Headline-Referenz (legacy, N=15, post Capture-Clock-Fix, kausal) aus
# CLAUDE.md — zum direkten Nebeneinander im Output.
RF_REF = {
    "1s": (0.872, 0.947), "5s": (0.860, 0.933),
    "10s": (0.825, 0.906), "30s": (0.771, 0.856),
}
# Native-Lang-Fenster-Referenz (per-window, legacy N=15, no-zscore).
NATIVE_REF = {
    5: {"RF-nativ-5s": (0.885, 0.953), "TCN-5s": (0.911, 0.976)},
    10: {"RF-nativ-10s": (0.880, 0.955), "TCN-10s": (0.914, 0.979)},
}


def _build_transform(transform: str, seed: int, n_kernels: int):
    """Baut den aeon-Transformer für ``transform``.

    ``n_kernels`` gilt nur für Mini-/MultiRocket; ``Hydra`` nutzt seinen
    aeon-Default (dort meint ``n_kernels`` Kernel *pro Gruppe*, nicht die
    Gesamtzahl). ``Hydra`` gibt per Default einen torch-Tensor zurück —
    ``output_type='numpy'`` erzwingt ein sklearn-taugliches ndarray.
    """
    if transform == "minirocket":
        return MiniRocket(n_kernels=n_kernels, n_jobs=-1, random_state=seed)
    if transform == "multirocket":
        return MultiRocket(n_kernels=n_kernels, n_jobs=-1, random_state=seed)
    if transform == "hydra":
        return HydraTransformer(n_jobs=-1, random_state=seed, output_type="numpy")
    raise ValueError(f"transform muss in {TRANSFORMS} sein, war {transform!r}")


def _fit_predict(transform, train_X, train_y, test_X, seed, n_kernels):
    """Rocket-Transform + standardisierte LogReg. Returns writing-Proba.

    ``train_X``/``test_X`` kommen als ``(n, seq_len, 6)`` (cases, time,
    channels) aus ``build_raw_windows`` — die Rocket-Transforms wollen
    ``(n, channels, time)``, daher das ``transpose(0, 2, 1)``.
    """
    tf = _build_transform(transform, seed, n_kernels)
    Xtr = np.asarray(tf.fit_transform(train_X.transpose(0, 2, 1)), dtype=np.float32)
    Xte = np.asarray(tf.transform(test_X.transpose(0, 2, 1)), dtype=np.float32)
    clf = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000, n_jobs=-1),
    )
    clf.fit(Xtr, train_y)
    return clf.predict_proba(Xte)[:, 1]


def run(transform: str, window_sec: int, pool: str, zscore: bool, seed: int,
        max_folds: int | None, save_cv: Path | None,
        n_kernels: int = 2000) -> pd.DataFrame:
    if transform not in TRANSFORMS:
        raise ValueError(f"transform muss in {TRANSFORMS} sein, war {transform!r}")
    if pool not in POOL_FS:
        raise ValueError(f"pool muss in {sorted(POOL_FS)} sein, war {pool!r}")
    label = _LABELS[transform]
    fs = POOL_FS[pool]
    seq_len = window_sec * fs
    stride = fs // 2
    profile = _POOL_NATIVE_PROFILE[pool]

    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    if sessions.empty:
        raise RuntimeError(f"Keine Sessions für pool={pool!r}.")
    plan = _pool_plan(sessions, pool)
    data = _load_all_sessions(sessions, seq_len, stride, plan,
                              max_gap_ms=2500.0, zscore=zscore)

    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)
    if max_folds:
        person_ids = person_ids[:max_folds]

    print(f"\n=== {label} | pool={pool} | {window_sec}s ({seq_len} samples "
          f"@ {fs}Hz) | zscore={zscore} | {len(person_ids)} Folds ===")

    rows = []
    for i, test_p in enumerate(person_ids, 1):
        train_ps = [p for p in sorted(persons) if p != test_p]
        train_X = _stack_persons(train_ps, "X", data, persons)
        train_y = _stack_persons(train_ps, "y", data, persons)
        test_X = _stack_persons([test_p], "X", data, persons)
        test_y = _stack_persons([test_p], "y", data, persons)
        if len(np.unique(test_y)) < 2:
            print(f"  Fold {test_p}: übersprungen (einklassig)")
            continue

        test_df = pd.concat(
            [pd.DataFrame({"session_id": s, "t_center_ms": data[s]["t"]})
             for s in persons[test_p]],
            ignore_index=True,
        )
        proba = _fit_predict(transform, train_X, train_y, test_X, seed, n_kernels)
        pred = (proba >= 0.5).astype(int)
        acc = float((pred == test_y).mean())
        try:
            auc = float(roc_auc_score(test_y, proba))
        except ValueError:
            auc = float("nan")
        f1 = float(f1_score(test_y, pred, pos_label=1, zero_division=0))
        bursts = _burst_metrics(proba, test_y, test_df)

        row = {"held_out": test_p, "n_test": len(test_y),
               "accuracy": acc, "f1_writing": f1, "roc_auc": auc}
        for scale, m in bursts.items():
            row[f"acc_{scale}"] = m["accuracy"]
            row[f"f1_{scale}"] = m["f1_writing"]
            row[f"auc_{scale}"] = m["roc_auc"]
        rows.append(row)
        print(f"  [{i}/{len(person_ids)}] {test_p}: acc={acc:.3f} "
              f"auc={auc:.3f} f1={f1:.3f}  @5s acc={bursts['5s']['accuracy']:.3f}")

    df = pd.DataFrame(rows)
    if df.empty:
        print("Keine vollständigen Folds.")
        return df

    print(f"\n--- {label} Decision-Skalen (mean ± std) vs RF-Headline ---")
    print(f"{'scale':>6}  {label + ' acc':>16}  {'auc':>7}  "
          f"{'RF acc':>7}  {'RF auc':>7}  {'Δacc':>6}")
    for scale in ("1s", "5s", "10s", "30s"):
        if scale == "1s":
            a, u = df["accuracy"], df["roc_auc"]
        else:
            a, u = df[f"acc_{scale}"], df[f"auc_{scale}"]
        ra, ru = RF_REF[scale]
        print(f"{scale:>6}  {a.mean():.3f} ± {a.std(ddof=0):.3f}  {u.mean():>7.3f}  "
              f"{ra:>7.3f}  {ru:>7.3f}  {a.mean() - ra:>+6.3f}")

    if window_sec in NATIVE_REF:
        print(f"\n--- per-window ({window_sec}s nativ) vs Deep-Referenz ---")
        print(f"  {label}-{window_sec}s: acc={df['accuracy'].mean():.3f} "
              f"auc={df['roc_auc'].mean():.3f}")
        for name, (ra, ru) in NATIVE_REF[window_sec].items():
            print(f"  {name:>14}: acc={ra:.3f} auc={ru:.3f}  "
                  f"(Δacc {df['accuracy'].mean() - ra:+.3f})")

    if save_cv:
        save_cv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(save_cv, index=False)
        print(f"\n→ {save_cv}  (significance.py-kompatibel)")
    return df


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--transform", choices=list(TRANSFORMS), default="multirocket")
    p.add_argument("--window-sec", type=int, default=1)
    p.add_argument("--pool", choices=["legacy", "modern"], default="legacy")
    p.add_argument("--zscore", action="store_true",
                   help="Per-Session-Per-Kanal-Z-Score (Pendant zum RF). Default aus.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-kernels", type=int, default=2000,
                   help="Kernel-Zahl für Mini-/MultiRocket (Default 2000; ~10k = "
                        "Paper-Default, langsamer). Für Hydra ignoriert (dort ist "
                        "n_kernels die Kernelzahl pro Gruppe → aeon-Default).")
    p.add_argument("--max-folds", type=int, default=None,
                   help="Nur erste N Personen — Smoke-Test.")
    p.add_argument("--save-cv", type=Path, default=None)
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.transform, a.window_sec, a.pool, a.zscore, a.seed, a.max_folds,
        a.save_cv, n_kernels=a.n_kernels)

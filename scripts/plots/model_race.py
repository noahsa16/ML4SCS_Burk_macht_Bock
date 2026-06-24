"""Modell-Rennen — drei Modellfamilien, dieselben Einbrüche.

Auf einer einzigen schwachen LOSO-Fold (Default die datengetrieben schwächste
Person) laufen drei mechanistisch unverwandte Modelle gegeneinander:

  * **RF**   — 88 engineered Features + Bagging-Tree (aus dem leak-freien
               ``loso_oof.csv``-Cache, per-Session-Z-Score, Headline-Pipeline).
  * **TCN**  — gelernte dilatierte Kausal-Convs auf den rohen 6-Kanal-Sequenzen
               (frisch für genau diese Fold trainiert: Train = alle anderen
               Personen).
  * **MiniRocket** — ~10k zufällige Convolutional-Kernel + lineare LogReg.

Alle drei werden auf die Held-out-Person angewendet und ihre writing-Proba über
die Zeit überlagert, mit der Pen-Wahrheit als Hintergrundband. Aussage: die
Kurven zappeln *gemeinsam* an denselben mehrdeutigen Stellen und liegen
paarweise hoch korreliert — die Fehlerdecke ist eine Eigenschaft des Signals,
nicht eines einzelnen Modells. (Pendant zur Residuen-Korrelation r≈0.57 in
``reports/harnet_rf_fusion.md`` und zum Embedding in ``embedding_ceiling.py``.)

CLI::

    python scripts/plots/model_race.py
    python scripts/plots/model_race.py --person P09 --minutes 6
    python scripts/plots/model_race.py --minutes 0      # ganze Session
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from aeon.transformations.collection.convolution_based import MiniRocket  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from src.training.deep.models import MODELS  # noqa: E402
from src.training.deep.train_loso import (  # noqa: E402
    POOL_FS,
    _POOL_NATIVE_PROFILE,
    _load_all_sessions,
    _pool_plan,
    _stack_persons,
    predict_proba,
    train_one_model,
)
from src.training.train_loso import _select_sessions  # noqa: E402

OOF = ROOT / "models" / "loso_oof.csv"
FIG_DIR = ROOT / "reports" / "figures"

C_RF = "#3B3A6B"   # Indigo
C_TCN = "#B07A2C"  # Gold
C_MR = "#2E7D6B"   # Teal
C_TRUTH = "#E7D9B8"  # warmes Sandband


def _weakest_person(oof: pd.DataFrame) -> str:
    oof = oof.assign(pred=(oof["proba_raw"] >= 0.5).astype(int))
    acc = oof.groupby("person_id").apply(
        lambda g: (g["pred"] == g["label"]).mean(), include_groups=False)
    return acc.idxmin()


def _minirocket_proba(train_X, train_y, test_X, seed, n_kernels):
    """MiniRocket-Transform + standardisierte LogReg → writing-Proba.

    ``build_raw_windows`` liefert ``(n, seq_len, 6)``; MiniRocket will
    ``(n, 6, seq_len)`` — daher das transpose."""
    mr = MiniRocket(n_kernels=n_kernels, n_jobs=-1, random_state=seed)
    Xtr = mr.fit_transform(train_X.transpose(0, 2, 1))
    Xte = mr.transform(test_X.transpose(0, 2, 1))
    clf = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=1.0, class_weight="balanced", max_iter=1000, n_jobs=-1))
    clf.fit(Xtr, train_y)
    return clf.predict_proba(Xte)[:, 1]


def _causal_smooth(p: np.ndarray, k: int) -> np.ndarray:
    """Trailing (kausaler) gleitender Mittelwert — keine Zukunft, wie der
    Live-Tracker. Nur Display-Glättung, ändert die Aussage nicht."""
    if k <= 1:
        return p
    s = pd.Series(p).rolling(k, min_periods=1).mean()
    return s.to_numpy()


def _compute_deep_fold(held_out: str, seed: int, n_kernels: int):
    """Trainiere TCN + MiniRocket für genau die Held-out-Fold (1-s legacy)."""
    fs = POOL_FS["legacy"]
    seq_len, stride = fs, fs // 2
    profile = _POOL_NATIVE_PROFILE["legacy"]
    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    plan = _pool_plan(sessions, "legacy")
    data = _load_all_sessions(sessions, seq_len, stride, plan,
                              max_gap_ms=2500.0, zscore=False)

    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    if held_out not in persons:
        raise SystemExit(f"{held_out} nicht im legacy-Pool: {sorted(persons)}")

    pids = sorted(persons)
    val_p = pids[(pids.index(held_out) + 1) % len(pids)]
    train_ps = [p for p in pids if p not in (held_out, val_p)]
    train_X = _stack_persons(train_ps, "X", data, persons)
    train_y = _stack_persons(train_ps, "y", data, persons)
    val_X = _stack_persons([val_p], "X", data, persons)
    val_y = _stack_persons([val_p], "y", data, persons)
    test_X = _stack_persons([held_out], "X", data, persons)
    test_y = _stack_persons([held_out], "y", data, persons)
    test_t = np.concatenate([data[s]["t"] for s in persons[held_out]])

    print(f"  TCN: trainiere auf {len(train_ps)} Personen "
          f"({len(train_X)} Fenster), Val={val_p} …")
    model, _ = train_one_model(MODELS["tcn"](), train_X, train_y, val_X, val_y)
    tcn_p = predict_proba(model, test_X)

    print(f"  MiniRocket: {n_kernels} Kernel + LogReg …")
    mr_p = _minirocket_proba(train_X, train_y, test_X, seed, n_kernels)

    return test_t, test_y, tcn_p, mr_p


def _pick_window(t_min, gt, probas, minutes):
    """Wähle das interessanteste ``minutes``-Fenster: dort, wo der mittlere
    Modell-Fehler vs. Pen-Wahrheit am höchsten ist (die umkämpfte Stelle)."""
    if minutes <= 0:
        return t_min.min(), t_min.max()
    err = np.mean([np.abs(p - gt) for p in probas], axis=0)
    half = minutes / 2
    best_c, best_e = t_min[len(t_min) // 2], -1.0
    for c in np.linspace(t_min.min() + half, t_min.max() - half, 60):
        m = (t_min >= c - half) & (t_min <= c + half)
        if m.sum() < 5:
            continue
        e = err[m].mean()
        if e > best_e:
            best_e, best_c = e, c
    return best_c - half, best_c + half


def run(person: str | None, minutes: float, seed: int, n_kernels: int) -> None:
    oof = pd.read_csv(OOF)
    held_out = person or _weakest_person(oof)
    rf = oof[oof["person_id"] == held_out].sort_values("t_center_ms")
    if rf.empty:
        raise SystemExit(f"{held_out} nicht in loso_oof.csv")
    session = rf["session_id"].iloc[0]
    print(f"Modell-Rennen auf {held_out} / {session} "
          f"(RF-OOF: {len(rf)} Fenster, {rf['label'].mean():.0%} writing)")

    test_t, test_y, tcn_p, mr_p = _compute_deep_fold(held_out, seed, n_kernels)

    # Gemeinsame Zeitachse: Minuten seit dem frühesten Fenster der Session.
    t0 = min(rf["t_center_ms"].min(), test_t.min())
    rf_tm = (rf["t_center_ms"].to_numpy() - t0) / 60000.0
    deep_tm = (test_t - t0) / 60000.0

    rf_p = rf["proba_raw"].to_numpy()
    gt = rf["label"].to_numpy()

    k = 5  # ~2,5 s kausale Display-Glättung
    series = {
        "RF (engineered + tree)": (rf_tm, _causal_smooth(rf_p, k), C_RF),
        "TCN (learned conv)": (deep_tm, _causal_smooth(tcn_p, k), C_TCN),
        "MiniRocket (random conv)": (deep_tm, _causal_smooth(mr_p, k), C_MR),
    }

    # Paarweise Korrelation auf der gemeinsamen RF-Zeitachse (TCN/MR auf RF-t
    # interpoliert — nur fürs Korrelations-Readout, nicht fürs Plotten).
    tcn_on_rf = np.interp(rf_tm, deep_tm, tcn_p)
    mr_on_rf = np.interp(rf_tm, deep_tm, mr_p)
    corr = {
        "RF·TCN": np.corrcoef(rf_p, tcn_on_rf)[0, 1],
        "RF·MiniRocket": np.corrcoef(rf_p, mr_on_rf)[0, 1],
        "TCN·MiniRocket": np.corrcoef(tcn_on_rf, mr_on_rf)[0, 1],
    }
    print("  Proba-Korrelation:", {k_: round(v, 3) for k_, v in corr.items()})

    lo, hi = _pick_window(rf_tm, gt, [rf_p, tcn_on_rf, mr_on_rf], minutes)

    fig, ax = plt.subplots(figsize=(13, 5.4))
    # Pen-Wahrheit als Hintergrundband.
    in_w = gt == 1
    ax.fill_between(rf_tm, 0, 1, where=in_w, step="mid", color=C_TRUTH,
                    alpha=0.9, linewidth=0, label="Pen: schreibt")
    for name, (tm, p, c) in series.items():
        ax.plot(tm, p, color=c, lw=1.6, alpha=0.95, label=name)
    ax.axhline(0.5, color="#888", lw=0.8, ls="--")
    ax.set_xlim(lo, hi)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Minuten seit Session-Start")
    ax.set_ylabel("P(writing)")
    ax.set_title(f"Modell-Rennen — {held_out}: drei Familien, dieselben Einbrüche",
                 fontsize=13)
    ax.legend(loc="lower left", ncol=2, framealpha=0.92, fontsize=9)

    txt = "Proba-Korrelation\n" + "\n".join(
        f"{k_}:  r={v:.2f}" for k_, v in corr.items())
    ax.text(0.985, 0.97, txt, transform=ax.transAxes, ha="right", va="top",
            fontsize=9, family="monospace",
            bbox=dict(boxstyle="round", fc="white", ec="#ccc", alpha=0.9))

    fig.tight_layout()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    span = "full" if minutes <= 0 else f"{minutes:g}min"
    out = FIG_DIR / f"model_race_{held_out}_{span}.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"\n→ {out}")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--person", default=None,
                   help="Person-ID; default = schwächste aus loso_oof.csv.")
    p.add_argument("--minutes", type=float, default=6.0,
                   help="Breite des gezeigten Zeitfensters (0 = ganze Session).")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--n-kernels", type=int, default=10000,
                   help="MiniRocket-Kernel (Default 10k = Paper-Default; "
                        "ein einzelner Fold ist schnell genug).")
    return p.parse_args()


if __name__ == "__main__":
    a = _parse()
    run(a.person, a.minutes, a.seed, a.n_kernels)

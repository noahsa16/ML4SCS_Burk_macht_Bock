"""HMM-Hyperparameter-Sweep auf den vorberechneten LOSO-OOF-Probas.

Tunt die drei bisher mit Default belassenen HMM-Knoepfe gegen die deployte
Baseline (smoothing=1.0, eps=1e-3, gamma=1.0):

- **smoothing** — Laplace-Glaettung der Transitionsmatrix (kleiner = klebriger).
- **eps** — Emissions-Clipping ``[eps, 1-eps]`` (Umgang mit extremen Probas).
- **gamma** — Acoustic Scale ``b = (P(s|o)/P(s))**gamma`` (Emissions- vs.
  Zeitstruktur-Vertrauen; der theoretisch motivierte Kandidat).

Rein CPU (numpy ueber die OOF-CSV), kein GPU/Retraining. Leakage-frei: die
Transition/Priors jedes Folds kommen NUR aus den Trainings-Personen.

**Drei Decode-Modi, alle erste Klasse** (der Scrybe-Tagestracker darf in die
Zukunft schauen; Live ist nur noch Gimmick):
- ``filter``   — kausaler Forward-Filter (live-tauglich).
- ``smoother`` — Forward-Backward (nicht-kausal, nutzt den ganzen Tag).
- ``viterbi``  — MAP-Pfad (nicht-kausal, hart).

**Anti-Dredge:** je Modus wird der acc-Sieger gegen die Default per gepaartem
Wilcoxon getestet (``significance.py``). Nur ``p<0.05 & Δ>0`` gilt als
deploy-wuerdig; alles andere ist Rauschen und die Default bleibt.

CLI: ``python scripts/ml/hmm_hyperparameter_sweep.py [--oof models/loso_oof_legacy.csv]``.
Output: ``models/hmm_hyperparameter_sweep_results.csv`` + ``reports/hmm_hyperparameter_sweep.md``.
"""
from __future__ import annotations

import argparse
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.hmm import (  # noqa: E402
    class_priors, estimate_transition_matrix, forward_backward, forward_filter,
    scaled_likelihoods, viterbi,
)
from src.evaluation.significance import paired_fold_test  # noqa: E402

OOF_DEFAULT = ROOT / "models" / "loso_oof_legacy.csv"
CSV_OUT = ROOT / "models" / "hmm_hyperparameter_sweep_results.csv"
REPORT = ROOT / "reports" / "hmm_hyperparameter_sweep.md"

GRID = {
    "smoothing": [0.01, 0.1, 0.5, 1.0, 2.0],
    "eps": [1e-5, 1e-4, 1e-3, 1e-2, 0.05],
    "gamma": [0.25, 0.5, 0.75, 1.0, 1.25, 1.5],
    "modes": ["filter", "smoother", "viterbi"],
}
DEFAULT = {"smoothing": 1.0, "eps": 1e-3, "gamma": 1.0}


# ---- testbarer Kern (rein, leakage-frei) ---------------------------------

def fit_fold(train_df: pd.DataFrame, smoothing: float):
    """Transitionsmatrix + Priors aus den Trainings-Sessions (per-Session-Seqs)."""
    seqs = [g["y"].to_numpy() for _, g in train_df.groupby("session_id", sort=False)]
    A = estimate_transition_matrix(seqs, smoothing=smoothing)
    priors = class_priors(train_df["y"].to_numpy(), smoothing=smoothing)
    return A, np.asarray(priors, dtype=float)


def decode_person(test_df: pd.DataFrame, A, priors, eps: float, gamma: float,
                  mode: str) -> np.ndarray:
    """Dekodiert die Sessions einer Person -> harte 0/1-Labels. Label-frei."""
    out = []
    for _, g in test_df.groupby("session_id", sort=False):
        b = scaled_likelihoods(g["proba"].to_numpy(), priors, eps=eps, gamma=gamma)
        if mode == "filter":
            out.append((forward_filter(b, A, priors)[:, 1] >= 0.5).astype(int))
        elif mode == "smoother":
            out.append((forward_backward(b, A, priors)[:, 1] >= 0.5).astype(int))
        elif mode == "viterbi":
            out.append(viterbi(b, A, priors).astype(int))
        else:
            raise ValueError(f"unbekannter mode {mode!r}")
    return np.concatenate(out)


def decode_loso(df: pd.DataFrame, smoothing: float, eps: float, gamma: float,
                mode: str) -> pd.DataFrame:
    """Leakage-freie Per-Person-LOSO -> per-Fold accuracy/f1.

    Der Fit jedes gehaltenen Folds kommt NUR aus ``df[person_id != held]``.
    """
    rows = []
    for held, test_df in df.groupby("person_id", sort=False):
        A, priors = fit_fold(df[df["person_id"] != held], smoothing)
        preds = decode_person(test_df, A, priors, eps, gamma, mode)
        y = test_df["y"].to_numpy()
        rows.append({
            "held_out": held,
            "accuracy": float((preds == y).mean()),
            "f1": float(f1_score(y, preds, zero_division=0)),
        })
    return pd.DataFrame(rows)


def combo_key(mode: str, smoothing: float, eps: float, gamma: float) -> str:
    return f"{mode}|sm={smoothing:g}|eps={eps:g}|g={gamma:g}"


# ---- Sweep + Gate (Plumbing) ---------------------------------------------

def run_sweep(df: pd.DataFrame, grid: dict = GRID):
    """Alle Kombis dekodieren. Returns (results_df, per_fold_cvs).

    ``results_df``: eine Zeile je Kombi (mode/smoothing/eps/gamma + mean acc/f1).
    ``per_fold_cvs``: ``{combo_key: DataFrame[held_out, accuracy, f1]}`` fuers Gate.
    """
    combos = list(product(grid["modes"], grid["smoothing"], grid["eps"], grid["gamma"]))
    rows, cvs = [], {}
    for i, (mode, sm, eps, g) in enumerate(combos, 1):
        cv = decode_loso(df, sm, eps, g, mode)
        key = combo_key(mode, sm, eps, g)
        cvs[key] = cv
        rows.append({"mode": mode, "smoothing": sm, "eps": eps, "gamma": g,
                     "key": key, "accuracy": float(cv["accuracy"].mean()),
                     "f1": float(cv["f1"].mean())})
        if i % 25 == 0 or i == len(combos):
            print(f"  {i}/{len(combos)}  {key}  acc={rows[-1]['accuracy']:.4f}")
    return pd.DataFrame(rows), cvs


def gate_winner(results: pd.DataFrame, cvs: dict, mode: str) -> dict:
    """Bester acc-Sieger eines Modus, gepaart gegen die Default getestet."""
    mode_df = results[results["mode"] == mode]
    best = mode_df.loc[mode_df["accuracy"].idxmax()]
    default_key = combo_key(mode, DEFAULT["smoothing"], DEFAULT["eps"], DEFAULT["gamma"])
    default = results[results["key"] == default_key].iloc[0]
    sig = paired_fold_test(cvs[best["key"]]["accuracy"].to_numpy(),
                           cvs[default_key]["accuracy"].to_numpy())
    d_acc = float(best["accuracy"] - default["accuracy"])
    return {
        "mode": mode, "best": best, "default": default,
        "delta_acc": d_acc, "p_value": sig["p_value"],
        "significant": bool(sig["significant"]),
        "deploy_worthy": bool(sig["significant"] and d_acc > 0),
    }


def _fmt(row) -> str:
    return f"sm={row['smoothing']:g} / eps={row['eps']:g} / gamma={row['gamma']:g}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oof", type=Path, default=OOF_DEFAULT)
    args = ap.parse_args()
    if not args.oof.exists():
        sys.exit(f"OOF nicht gefunden: {args.oof}")

    df = pd.read_csv(args.oof).rename(columns={"label": "y", "proba_cal": "proba"})
    n_combos = (len(GRID["smoothing"]) * len(GRID["eps"]) * len(GRID["gamma"])
                * len(GRID["modes"]))
    print(f"HMM-Sweep: {n_combos} Kombis, {df['person_id'].nunique()} Folds, "
          f"{len(df):,} Fenster")
    results, cvs = run_sweep(df)
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    results.drop(columns=["key"]).to_csv(CSV_OUT, index=False)

    gates = [gate_winner(results, cvs, m) for m in GRID["modes"]]
    _write_report(df, results, gates)


def _write_report(df, results, gates) -> None:
    default_key = combo_key("filter", DEFAULT["smoothing"], DEFAULT["eps"], DEFAULT["gamma"])
    base_acc = float(results[results["key"] == default_key]["accuracy"].iloc[0])
    lines = [
        "# HMM-Hyperparameter-Sweep (smoothing × eps × gamma × mode)", "",
        f"Legacy-Pool, {df['person_id'].nunique()} LOSO-Folds, {len(df):,} Fenster. "
        f"Baseline (deployed): smoothing=1.0 / eps=1e-3 / gamma=1.0, "
        f"filter-acc {base_acc:.4f}.", "",
        "Modi: **filter** = kausal (Live-Gimmick), **smoother/viterbi** = "
        "nicht-kausal (Scrybe-Tagestracker, darf in die Zukunft schauen). "
        "Sieger je Modus gepaart (Wilcoxon) vs. Default; **deploy-würdig nur bei "
        "p<0.05 ∧ Δ>0** (Anti-Dredge bei 450 Kombis).", "",
        "| Modus | Sieger-HP | acc | Δ vs default | p | Verdikt |",
        "|---|---|---|---|---|---|",
    ]
    for g in gates:
        verdict = "**DEPLOY-WÜRDIG**" if g["deploy_worthy"] else (
            "n.s. (Rauschen)" if g["delta_acc"] > 0 else "≤ default")
        lines.append(
            f"| {g['mode']} | {_fmt(g['best'])} | {g['best']['accuracy']:.4f} | "
            f"{g['delta_acc']:+.4f} | {g['p_value']:.4f} | {verdict} |")
    lines += [
        "", "## Lesart", "",
        "Ein Sieger ist nur dann echt, wenn er die Default **signifikant** "
        "schlägt — bei 450 Ziehungen hebt reine Ordnungsstatistik das Max fast "
        "sicher um Bruchteile. Überlebt kein Modus das Gate, ist die deployte "
        "Default bestätigt und die HMM-Knöpfe sind ausgereizt. Ein deploy-würdiger "
        "`filter`-Sieger wandert nach `models/hmm_live.json` (+ gamma in "
        "`OnlineForwardFilter`); ein `smoother`/`viterbi`-Sieger ist der Decoder "
        "für den Tagestracker.", "",
        f"Rohdaten: `{CSV_OUT.relative_to(ROOT)}`.", "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\n-> {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

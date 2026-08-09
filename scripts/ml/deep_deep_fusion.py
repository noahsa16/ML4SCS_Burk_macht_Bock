"""Deep×Deep-Ensemble: hebt das Proba-Mittel zweier Deep-Modelle die Solos?

Frage (Nutzer-Vorschlag): zwei *verschieden* aufgebaute Deep-Netze (z. B.
``tcn_bigru`` = dilatierte Causal-Convs + bidirektionaler GRU vs. ``inception``
= parallele Multi-Scale-Convs) lernen Muster unterschiedlich. Hebt ein
gleichgewichtetes Proba-Mittel ihrer Out-of-Fold-Vorhersagen das *bessere*
Solo-Modell — oder irren beide an denselben Fenstern?

Anders als ``scripts/ml/tcn_rf_fusion.py`` (das gecachte OOFs für tcn6/RF
wiederverwendet) existiert für die HP-Grid-Probes KEIN OOF-Cache — beide Netze
werden hier frisch pro Fold trainiert (Muster aus
``scripts/ml/deep_hard_negative_weight.py``), gepaart auf identischen Folds
(``_fold_splits``, gleicher Fold-Seed), dann gemittelt. Native-5-s-Fenster =
jede Prediction ist bereits eine 5-s-Entscheidung (kein Burst nötig).

Der entscheidende mechanistische Test bleibt die **Residuen-Korrelation**
``pearsonr(a−y, b−y)``: Fusion kann nur helfen, wenn die Fehler dekorreliert
sind. Referenz: tcn6↔RF r=0.599 (half, cross-paradigm), harnet↔RF r=0.574
(null). Zwei Deep-Conv-Netze erwartungsgemäß höher korreliert.

    python scripts/ml/deep_deep_fusion.py [--model-a tcn_bigru] [--model-b inception]
        [--folds 5] [--window-sec 5] [--seed 42] [--lr 3e-4] [--dropout 0.05]

Output: reports/deep_deep_fusion_{a}_{b}.md
        + models/deep_deep_fusion_{a}_{b}_{oof,cv}.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.metrics import roc_auc_score

# Why: run as `python scripts/ml/deep_deep_fusion.py` from repo root —
# add the project root to sys.path BEFORE the src imports below.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.deep.train_loso import (  # noqa: E402
    DEVICE, POOL_FS, _POOL_NATIVE_PROFILE, _fold_splits, _load_all_sessions,
    _pool_plan, _set_seed, _stack_persons, predict_proba, train_one_model,
)
from src.training.deep.models import MODELS  # noqa: E402
from src.training.train_loso import _select_sessions  # noqa: E402
from src.evaluation.significance import paired_fold_test  # noqa: E402

MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"


# ---- reine, testbare Kernlogik -------------------------------------------

def ensemble_proba(a: np.ndarray, b: np.ndarray, w: float = 0.5) -> np.ndarray:
    """Gewichtetes Proba-Mittel (Default gleichgewichtet)."""
    return w * np.asarray(a) + (1.0 - w) * np.asarray(b)


def _acc_auc(proba: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    acc = float(((proba >= 0.5).astype(int) == y).mean())
    try:
        auc = float(roc_auc_score(y, proba)) if len(np.unique(y)) > 1 else float("nan")
    except ValueError:
        auc = float("nan")
    return acc, auc


def residual_corr(a: np.ndarray, b: np.ndarray, y: np.ndarray) -> float:
    """Pearson-r der Residuen (a−y, b−y). Fusion hilft nur bei niedrigem r."""
    ra, rb = np.asarray(a) - y, np.asarray(b) - y
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(pearsonr(ra, rb)[0])


def _paired(cv: pd.DataFrame, arm_a: str, arm_b: str, metric: str) -> dict:
    """paired_fold_test auf gemeinsamen Folds (held_out) für eine Metrik."""
    a = cv[cv["arm"] == arm_a][["held_out", metric]]
    b = cv[cv["arm"] == arm_b][["held_out", metric]]
    m = a.merge(b, on="held_out", suffixes=("_a", "_b")).dropna()
    if len(m) < 1:
        return {"median_diff": float("nan"), "p_value": float("nan"),
                "significant": False}
    return paired_fold_test(m[f"{metric}_a"].to_numpy(), m[f"{metric}_b"].to_numpy())


# ---- Fold-Loop (trainiert beide Netze frisch, gepaart) -------------------

def run_fusion(model_a: str, model_b: str, args) -> tuple[pd.DataFrame, pd.DataFrame]:
    pool = args.pool
    fs = POOL_FS[pool]
    seq_len = args.window_sec * fs
    stride = fs // 2

    sessions = _select_sessions(
        include_all=False, min_windows=0, profile=_POOL_NATIVE_PROFILE[pool])
    plan = _pool_plan(sessions, pool)
    data = _load_all_sessions(sessions, seq_len, stride, plan, 2500.0, None,
                              zscore=False)

    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)

    print(f"=== Deep×Deep-Fusion | {model_a} × {model_b} | {args.window_sec}s | "
          f"{len(person_ids)} Personen | {args.folds}-fold | device={DEVICE} ===")

    splits = _fold_splits(person_ids, args.folds)
    oof_rows: list[pd.DataFrame] = []
    per_fold: list[dict] = []
    common = dict(max_epochs=args.max_epochs, patience=args.patience,
                  batch_size=args.batch_size, lr=args.lr,
                  weight_decay=args.weight_decay)

    for i, (test_group, val_p, train_ps) in enumerate(splits):
        train_X = _stack_persons(train_ps, "X", data, persons)
        train_y = _stack_persons(train_ps, "y", data, persons)
        val_X = _stack_persons([val_p], "X", data, persons)
        val_y = _stack_persons([val_p], "y", data, persons)
        test_X = _stack_persons(test_group, "X", data, persons)
        test_y = _stack_persons(test_group, "y", data, persons)
        test_t = _stack_persons(test_group, "t", data, persons)
        if len(np.unique(test_y)) < 2:
            continue
        test_sids = [s for p in test_group for s in persons[p]]
        test_sess = np.concatenate(
            [np.full(len(data[s]["y"]), s, dtype=object) for s in test_sids])

        held = "+".join(sorted(test_group))
        fold_seed = args.seed + i

        # Beide Arme: identischer Fold-Seed vor Konstruktion -> gleiche
        # Daten-Shuffle-Sequenz, verschiedene Architektur = die einzige Variable.
        _set_seed(fold_seed)
        m_a = MODELS[model_a](dropout=args.dropout)
        m_a, _ = train_one_model(m_a, train_X, train_y, val_X, val_y, **common)
        pa = predict_proba(m_a, test_X)

        _set_seed(fold_seed)
        m_b = MODELS[model_b](dropout=args.dropout)
        m_b, _ = train_one_model(m_b, train_X, train_y, val_X, val_y, **common)
        pb = predict_proba(m_b, test_X)

        pe = ensemble_proba(pa, pb)
        acc_a, auc_a = _acc_auc(pa, test_y)
        acc_b, auc_b = _acc_auc(pb, test_y)
        acc_e, auc_e = _acc_auc(pe, test_y)
        for arm, acc, auc in ((model_a, acc_a, auc_a), (model_b, acc_b, auc_b),
                              ("ensemble", acc_e, auc_e)):
            per_fold.append({"held_out": held, "arm": arm,
                             "accuracy": acc, "roc_auc": auc})
        print(f"  fold {i} [{held:>18}]  {model_a} {acc_a:.3f}/{auc_a:.3f}  "
              f"{model_b} {acc_b:.3f}/{auc_b:.3f}  ens {acc_e:.3f}/{auc_e:.3f}")

        oof_rows.append(pd.DataFrame({
            "session_id": test_sess, "t_center_ms": test_t, "label": test_y,
            "proba_a": pa, "proba_b": pb, "proba_ens": pe,
        }))

    return pd.concat(oof_rows, ignore_index=True), pd.DataFrame(per_fold)


def _summary(cv: pd.DataFrame, arm: str) -> str:
    g = cv[cv["arm"] == arm]
    return (f"{g['accuracy'].mean():.3f}±{g['accuracy'].std(ddof=0):.3f} / "
            f"{g['roc_auc'].mean():.3f}")


def _report(model_a, model_b, oof, cv, r_resid, sig, cv_out) -> Path:
    n_folds = cv["held_out"].nunique()
    da = cv[cv["arm"] == "ensemble"]["accuracy"].mean() - \
        cv[cv["arm"] == model_a]["accuracy"].mean()
    db = cv[cv["arm"] == "ensemble"]["accuracy"].mean() - \
        cv[cv["arm"] == model_b]["accuracy"].mean()
    better_solo = model_a if cv[cv["arm"] == model_a]["accuracy"].mean() >= \
        cv[cv["arm"] == model_b]["accuracy"].mean() else model_b
    key = f"ens_vs_{better_solo}_acc"
    helps = sig[key]["significant"] and (da if better_solo == model_a else db) > 0
    verdict = (f"**hebt** das bessere Solo ({better_solo})" if helps
               else f"**hebt {better_solo} nicht** (Δ n.s. / ≤ 0)")

    def sline(k):
        s = sig[k]
        return (f"median Δ {s['median_diff']:+.4f}, p={s['p_value']:.4f} "
                f"→ {'SIGNIFIKANT' if s['significant'] else 'n.s.'}")

    lines = [
        f"# Deep×Deep-Ensemble: {model_a} × {model_b}", "",
        f"Legacy-Pool, nativ-5s, grouped-{n_folds}-fold, {len(oof)} Fenster. Beide "
        "Netze frisch trainiert, gepaart auf identischen Folds (gleicher Fold-Seed, "
        "einzige Variable = Architektur).", "",
        "## Per-Fold acc±σ / AUC (nativ-5s)", "",
        "| Arm | acc±σ / AUC |", "|---|---|",
        f"| {model_a} solo | {_summary(cv, model_a)} |",
        f"| {model_b} solo | {_summary(cv, model_b)} |",
        f"| **Ensemble (mean)** | {_summary(cv, 'ensemble')} |", "",
        "## Der entscheidende Test: Residuen-Korrelation", "",
        f"- **r(a−y, b−y) = {r_resid:+.3f}**  "
        + ("→ Fehler stark korreliert, kaum Fusions-Spielraum."
           if r_resid > 0.5 else
           "→ Fehler nur teilweise korreliert, etwas Spielraum."),
        "", "## Gepaarter Wilcoxon (Ensemble vs. solo)", "",
        f"- Ensemble vs **{model_a}** (acc): {sline(f'ens_vs_{model_a}_acc')}",
        f"- Ensemble vs **{model_a}** (AUC): {sline(f'ens_vs_{model_a}_auc')}",
        f"- Ensemble vs **{model_b}** (acc): {sline(f'ens_vs_{model_b}_acc')}",
        f"- Ensemble vs **{model_b}** (AUC): {sline(f'ens_vs_{model_b}_auc')}",
        "", f"**Verdikt:** Fusion {verdict} "
        f"(Δacc vs {model_a} {da:+.4f}, vs {model_b} {db:+.4f}).",
        "", f"Rohdaten: `{cv_out.relative_to(ROOT)}`.", "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"deep_deep_fusion_{model_a}_{model_b}.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-a", default="tcn_bigru")
    ap.add_argument("--model-b", default="inception")
    ap.add_argument("--folds", type=int, default=5,
                    help="grouped-K-fold (Suchprotokoll); für LOSO-by-person höher setzen")
    ap.add_argument("--window-sec", type=int, default=5)
    ap.add_argument("--pool", default="legacy")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--weight-decay", type=float, default=1e-5)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-epochs", type=int, default=120)
    ap.add_argument("--patience", type=int, default=8)
    args = ap.parse_args()

    for m in (args.model_a, args.model_b):
        if m not in MODELS:
            raise SystemExit(f"unbekanntes Modell {m!r}; verfügbar: {sorted(MODELS)}")

    oof, cv = run_fusion(args.model_a, args.model_b, args)

    y = oof["label"].to_numpy()
    r_resid = residual_corr(oof["proba_a"].to_numpy(), oof["proba_b"].to_numpy(), y)
    sig = {}
    for arm in (args.model_a, args.model_b):
        sig[f"ens_vs_{arm}_acc"] = _paired(cv, "ensemble", arm, "accuracy")
        sig[f"ens_vs_{arm}_auc"] = _paired(cv, "ensemble", arm, "roc_auc")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{args.model_a}_{args.model_b}"
    oof.to_csv(MODEL_DIR / f"deep_deep_fusion_{tag}_oof.csv", index=False)
    cv_out = MODEL_DIR / f"deep_deep_fusion_{tag}_cv.csv"
    cv.to_csv(cv_out, index=False)

    out = _report(args.model_a, args.model_b, oof, cv, r_resid, sig, cv_out)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()

"""TCN6↔RF-Ensemble: hebt Fusion des besten Deep-Modells (TCN6) mit dem RF?

Frage: Der TCN6 (nativ-5s, acc 0.922) ist das stärkste Einzelmodell, der RF-nativ-5s
(0.885) bringt eine *andere* Sicht (Gyro + handgebaute Hochfrequenz-Statistiken vs.
Roh-Accel-Conv). Bringt ein Proba-Ensemble der beiden etwas — oder irren beide an
denselben Fenstern?

Beide Arme sind reine **Out-of-Fold**-Vorhersagen des gehaltenen Probanden im
identischen LOSO-by-person-Protokoll (legacy-Pool, nativ-5s-Decision), also
leakage-frei. Verglichen wird das Ensemble gegen **TCN6-solo** (hebt es das *beste*
Modell?) und gegen RF-solo, per-Fold gepaart (Wilcoxon, ``significance.py``).

Der entscheidende mechanistische Test ist die **Residuen-Korrelation**
``pearsonr(rf−y, tcn6−y)``: Fusion kann nur helfen, wenn die Fehler *dekorreliert*
sind (harnet↔RF war r=0.574 → kein Spielraum; TCN6↔RF ist offen).

CLI: ``python scripts/ml/tcn_rf_fusion.py [--force-oof]``.
Output: ``reports/tcn_rf_fusion.md`` + ``models/tcn_rf_fusion_cv.csv``
(significance-kompatible Per-Fold-CVs je Arm) + OOF-Caches
``models/{rf5,tcn6}_oof_legacy.csv``.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.significance import paired_fold_test  # noqa: E402

MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
WIN_SEC = 5
POOL = "legacy"


# ---- reine, testbare Kernlogik -------------------------------------------

def _pick(cols: list[str], candidates: tuple[str, ...]) -> str:
    for c in candidates:
        if c in cols:
            return c
    raise KeyError(f"keine von {candidates} in {cols}")


def _normalise_oof(df: pd.DataFrame) -> pd.DataFrame:
    """Robust auf einheitliche Spalten: session_id, t_center_ms, person_id, y, proba."""
    cols = list(df.columns)
    proba = _pick(cols, ("proba_cal", "proba", "proba_raw"))
    label = _pick(cols, ("label", "y"))
    person = _pick(cols, ("person_id", "held_out", "person"))
    out = df.rename(columns={proba: "proba", label: "y", person: "person_id"})
    return out[["session_id", "t_center_ms", "person_id", "y", "proba"]].copy()


def align_oofs(rf: pd.DataFrame, tcn6: pd.DataFrame) -> pd.DataFrame:
    """Paart RF- und TCN6-OOF per Session auf nächstem t_center (nearest).

    Beide sind nativ-5s; ``merge_asof(direction='nearest')`` fängt kleine
    Gitter-Offsets ab. Ground-Truth ``y`` + ``person_id`` kommen vom RF-Arm
    (linkes Frame). Returns Spalten session_id, t_center_ms, person_id, y,
    rf_proba, tcn6_proba.
    """
    left = _normalise_oof(rf).rename(columns={"proba": "rf_proba"}).sort_values("t_center_ms")
    right = (_normalise_oof(tcn6)[["session_id", "t_center_ms", "proba"]]
             .rename(columns={"proba": "tcn6_proba"}).sort_values("t_center_ms"))
    merged = pd.merge_asof(left, right, on="t_center_ms", by="session_id",
                           direction="nearest")
    missing = int(merged["tcn6_proba"].isna().sum())
    if missing:
        print(f"[fusion] {missing} Fenster ohne TCN6-Match — verworfen")
        merged = merged.dropna(subset=["tcn6_proba"])
    return merged.reset_index(drop=True)


def per_fold_metrics(df: pd.DataFrame, proba_col: str) -> pd.DataFrame:
    """Per-Person acc/AUC auf nativer 5-s-Decision (ein Fenster = eine Entscheidung).

    Returns significance.py-kompatibles CV: held_out, accuracy, roc_auc.
    """
    rows = []
    for person, g in df.groupby("person_id"):
        y = g["y"].to_numpy()
        p = g[proba_col].to_numpy()
        acc = float(((p >= 0.5).astype(int) == y).mean())
        try:
            auc = float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan")
        except ValueError:
            auc = float("nan")
        rows.append({"held_out": person, "accuracy": acc, "roc_auc": auc})
    return pd.DataFrame(rows).sort_values("held_out").reset_index(drop=True)


def ensemble_proba(rf_proba: np.ndarray, tcn6_proba: np.ndarray,
                   w: float = 0.5) -> np.ndarray:
    """Gewichtetes Proba-Mittel (Default gleichgewichtet)."""
    return w * np.asarray(rf_proba) + (1.0 - w) * np.asarray(tcn6_proba)


def _paired(a_cv: pd.DataFrame, b_cv: pd.DataFrame, metric: str) -> dict:
    """paired_fold_test auf gemeinsamen Folds (held_out) für eine Metrik."""
    m = a_cv[["held_out", metric]].merge(
        b_cv[["held_out", metric]], on="held_out", suffixes=("_a", "_b")).dropna()
    return paired_fold_test(m[f"{metric}_a"].to_numpy(), m[f"{metric}_b"].to_numpy())


# ---- OOF-Erzeugung (Plumbing, gecached) ----------------------------------

def _rf5_oof(force: bool) -> pd.DataFrame:
    cache = MODEL_DIR / "rf5_oof_legacy.csv"
    if cache.exists() and not force:
        print(f"[fusion] RF-5s-OOF aus Cache {cache.name}")
        return pd.read_csv(cache)
    print("[fusion] berechne RF-nativ-5s-OOF (train_loso --window-sec 5) …")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "rf5_oof.csv"
        subprocess.run(
            [sys.executable, "-m", "src.training.train_loso", "--pool", POOL,
             "--window-sec", str(WIN_SEC), "--save-oof", str(out)],
            cwd=ROOT, check=True,
        )
        # --pool legacy suffixt --save-oof automatisch zu rf5_oof_legacy.csv
        produced = sorted(Path(td).glob("rf5_oof*.csv"))
        if not produced:
            raise FileNotFoundError(f"train_loso schrieb keine rf5_oof*.csv in {td}")
        df = pd.read_csv(produced[0])
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def _tcn6_oof(force: bool) -> pd.DataFrame:
    cache = MODEL_DIR / "tcn6_oof_legacy.csv"
    if cache.exists() and not force:
        print(f"[fusion] TCN6-5s-OOF aus Cache {cache.name}")
        return pd.read_csv(cache)
    print("[fusion] berechne TCN6-nativ-5s-OOF (train_deep_loso tcn6 @5s) …")
    from src.training.deep.train_loso import train_deep_loso
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        train_deep_loso("tcn6", WIN_SEC, pool=POOL, run_dir=rd)
        produced = sorted(rd.glob("*oof*.csv"))
        if not produced:
            raise FileNotFoundError(f"train_deep_loso schrieb keine oof.csv in {rd}")
        df = pd.read_csv(produced[0])
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def _summary(cv: pd.DataFrame) -> str:
    return (f"{cv['accuracy'].mean():.3f}±{cv['accuracy'].std(ddof=0):.3f} / "
            f"{cv['roc_auc'].mean():.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force-oof", action="store_true")
    args = ap.parse_args()

    aligned = align_oofs(_rf5_oof(args.force_oof), _tcn6_oof(args.force_oof))
    aligned["ens_proba"] = ensemble_proba(
        aligned["rf_proba"].to_numpy(), aligned["tcn6_proba"].to_numpy())

    rf_cv = per_fold_metrics(aligned, "rf_proba")
    tcn6_cv = per_fold_metrics(aligned, "tcn6_proba")
    ens_cv = per_fold_metrics(aligned, "ens_proba")

    y = aligned["y"].to_numpy()
    r_resid, _ = pearsonr(aligned["rf_proba"].to_numpy() - y,
                          aligned["tcn6_proba"].to_numpy() - y)

    sig = {
        "ens_vs_tcn6_acc": _paired(ens_cv, tcn6_cv, "accuracy"),
        "ens_vs_tcn6_auc": _paired(ens_cv, tcn6_cv, "roc_auc"),
        "ens_vs_rf_acc": _paired(ens_cv, rf_cv, "accuracy"),
        "ens_vs_rf_auc": _paired(ens_cv, rf_cv, "roc_auc"),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    cv_out = MODEL_DIR / "tcn_rf_fusion_cv.csv"
    pd.concat([rf_cv.assign(arm="rf"), tcn6_cv.assign(arm="tcn6"),
               ens_cv.assign(arm="ensemble")]).to_csv(cv_out, index=False)

    _report(rf_cv, tcn6_cv, ens_cv, r_resid, sig, len(aligned), cv_out)


def _report(rf_cv, tcn6_cv, ens_cv, r_resid, sig, n_win, cv_out) -> None:
    d_acc = ens_cv["accuracy"].mean() - tcn6_cv["accuracy"].mean()
    d_auc = ens_cv["roc_auc"].mean() - tcn6_cv["roc_auc"].mean()
    helps = (sig["ens_vs_tcn6_acc"]["significant"] and d_acc > 0) or \
            (sig["ens_vs_tcn6_auc"]["significant"] and d_auc > 0)
    verdict = ("**hebt** den TCN6" if helps
               else "**hebt den TCN6 nicht** (Δ n.s. / ≤ 0)")

    def sline(k):
        s = sig[k]
        return (f"median Δ {s['median_diff']:+.4f}, p={s['p_value']:.4f} "
                f"→ {'SIGNIFIKANT' if s['significant'] else 'n.s.'}")

    lines = [
        "# TCN6↔RF-Ensemble: hebt Fusion das stärkste Modell?", "",
        f"Legacy-Pool, nativ-5s, LOSO-by-person, {len(tcn6_cv)} Folds, "
        f"{n_win} aligned Fenster.", "",
        "## Per-Fold acc±σ / AUC (nativ-5s)", "",
        "| Arm | acc±σ / AUC |", "|---|---|",
        f"| RF-nativ-5s solo | {_summary(rf_cv)} |",
        f"| TCN6-nativ-5s solo | {_summary(tcn6_cv)} |",
        f"| **Ensemble (mean)** | {_summary(ens_cv)} |", "",
        "## Der entscheidende Test: Residuen-Korrelation", "",
        f"- **r(rf−y, tcn6−y) = {r_resid:+.3f}**  "
        + ("→ Fehler stark korreliert, kaum Fusions-Spielraum."
           if r_resid > 0.5 else
           "→ Fehler nur teilweise korreliert, etwas Spielraum."),
        "", "## Gepaarter Wilcoxon (Ensemble vs. solo)", "",
        f"- Ensemble vs **TCN6** (acc): {sline('ens_vs_tcn6_acc')}",
        f"- Ensemble vs **TCN6** (AUC): {sline('ens_vs_tcn6_auc')}",
        f"- Ensemble vs RF (acc): {sline('ens_vs_rf_acc')}",
        f"- Ensemble vs RF (AUC): {sline('ens_vs_rf_auc')}",
        "", f"**Verdikt:** Fusion {verdict} "
        f"(vs TCN6-solo: Δacc {d_acc:+.4f}, ΔAUC {d_auc:+.4f}).",
        "", f"Rohdaten: `{cv_out.relative_to(ROOT)}`.", "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "tcn_rf_fusion.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\n-> {REPORTS_DIR / 'tcn_rf_fusion.md'}")


if __name__ == "__main__":
    main()

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

Das Deep-Modell ist über ``--model`` wählbar (Default tcn6); jedes Deep-Modell
aus ``MODELS`` (z. B. inception, tcn_bigru) lässt sich so gegen den RF fusionieren.

CLI: ``python scripts/ml/tcn_rf_fusion.py [--model tcn6] [--force-oof]``.
Output: ``reports/{model}_rf_fusion.md`` + ``models/{model}_rf_fusion_cv.csv``
(significance-kompatible Per-Fold-CVs je Arm) + OOF-Caches
``models/rf5_oof_legacy.csv`` + ``models/{model}_oof_legacy.csv``.
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


def align_oofs(rf: pd.DataFrame, deep: pd.DataFrame) -> pd.DataFrame:
    """Paart RF- und Deep-OOF per Session auf nächstem t_center (nearest).

    Beide sind nativ-5s; ``merge_asof(direction='nearest')`` fängt kleine
    Gitter-Offsets ab. Ground-Truth ``y`` + ``person_id`` kommen vom RF-Arm
    (linkes Frame). Die Deep-Spalte heißt generisch ``deep_proba`` (nicht
    modell-spezifisch), damit das Tool jedes Deep-Modell fusionieren kann.
    Returns Spalten session_id, t_center_ms, person_id, y, rf_proba, deep_proba.
    """
    left = _normalise_oof(rf).rename(columns={"proba": "rf_proba"}).sort_values("t_center_ms")
    right = (_normalise_oof(deep)[["session_id", "t_center_ms", "proba"]]
             .rename(columns={"proba": "deep_proba"}).sort_values("t_center_ms"))
    merged = pd.merge_asof(left, right, on="t_center_ms", by="session_id",
                           direction="nearest")
    missing = int(merged["deep_proba"].isna().sum())
    if missing:
        print(f"[fusion] {missing} Fenster ohne Deep-Match — verworfen")
        merged = merged.dropna(subset=["deep_proba"])
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


def ensemble_proba(rf_proba: np.ndarray, deep_proba: np.ndarray,
                   w: float = 0.5) -> np.ndarray:
    """Gewichtetes Proba-Mittel (Default gleichgewichtet)."""
    return w * np.asarray(rf_proba) + (1.0 - w) * np.asarray(deep_proba)


def _deep_cache_path(model: str) -> Path:
    """OOF-Cache-Pfad, dem Modellnamen folgend (statt hartem tcn6)."""
    return MODEL_DIR / f"{model}_oof_legacy.csv"


def _output_paths(model: str) -> tuple[Path, Path]:
    """(cv-CSV, Report-md) je Modell — kein Clobbern zwischen Fusions-Läufen."""
    return (MODEL_DIR / f"{model}_rf_fusion_cv.csv",
            REPORTS_DIR / f"{model}_rf_fusion.md")


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="tcn6",
                    help="Deep-Modell-Key (z. B. tcn6, inception, tcn_bigru)")
    ap.add_argument("--force-oof", action="store_true")
    return ap


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


def _deep_oof(model: str, force: bool) -> pd.DataFrame:
    cache = _deep_cache_path(model)
    if cache.exists() and not force:
        print(f"[fusion] {model}-5s-OOF aus Cache {cache.name}")
        return pd.read_csv(cache)
    print(f"[fusion] berechne {model}-nativ-5s-OOF (train_deep_loso {model} @5s) …")
    from src.training.deep.train_loso import train_deep_loso
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        train_deep_loso(model, WIN_SEC, pool=POOL, run_dir=rd)
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
    args = _build_parser().parse_args()
    model = args.model
    cv_out, report_out = _output_paths(model)

    aligned = align_oofs(_rf5_oof(args.force_oof), _deep_oof(model, args.force_oof))
    aligned["ens_proba"] = ensemble_proba(
        aligned["rf_proba"].to_numpy(), aligned["deep_proba"].to_numpy())

    rf_cv = per_fold_metrics(aligned, "rf_proba")
    deep_cv = per_fold_metrics(aligned, "deep_proba")
    ens_cv = per_fold_metrics(aligned, "ens_proba")

    y = aligned["y"].to_numpy()
    r_resid, _ = pearsonr(aligned["rf_proba"].to_numpy() - y,
                          aligned["deep_proba"].to_numpy() - y)

    sig = {
        "ens_vs_deep_acc": _paired(ens_cv, deep_cv, "accuracy"),
        "ens_vs_deep_auc": _paired(ens_cv, deep_cv, "roc_auc"),
        "ens_vs_rf_acc": _paired(ens_cv, rf_cv, "accuracy"),
        "ens_vs_rf_auc": _paired(ens_cv, rf_cv, "roc_auc"),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    pd.concat([rf_cv.assign(arm="rf"), deep_cv.assign(arm=model),
               ens_cv.assign(arm="ensemble")]).to_csv(cv_out, index=False)

    _report(model, rf_cv, deep_cv, ens_cv, r_resid, sig, len(aligned),
            cv_out, report_out)


def _report(model, rf_cv, deep_cv, ens_cv, r_resid, sig, n_win,
            cv_out, report_out) -> None:
    d_acc = ens_cv["accuracy"].mean() - deep_cv["accuracy"].mean()
    d_auc = ens_cv["roc_auc"].mean() - deep_cv["roc_auc"].mean()
    helps = (sig["ens_vs_deep_acc"]["significant"] and d_acc > 0) or \
            (sig["ens_vs_deep_auc"]["significant"] and d_auc > 0)
    verdict = (f"**hebt** den {model}" if helps
               else f"**hebt den {model} nicht** (Δ n.s. / ≤ 0)")

    def sline(k):
        s = sig[k]
        return (f"median Δ {s['median_diff']:+.4f}, p={s['p_value']:.4f} "
                f"→ {'SIGNIFIKANT' if s['significant'] else 'n.s.'}")

    lines = [
        f"# {model}↔RF-Ensemble: hebt Fusion das Deep-Modell?", "",
        f"Legacy-Pool, nativ-5s, LOSO-by-person, {len(deep_cv)} Folds, "
        f"{n_win} aligned Fenster.", "",
        "## Per-Fold acc±σ / AUC (nativ-5s)", "",
        "| Arm | acc±σ / AUC |", "|---|---|",
        f"| RF-nativ-5s solo | {_summary(rf_cv)} |",
        f"| {model}-nativ-5s solo | {_summary(deep_cv)} |",
        f"| **Ensemble (mean)** | {_summary(ens_cv)} |", "",
        "## Der entscheidende Test: Residuen-Korrelation", "",
        f"- **r(rf−y, {model}−y) = {r_resid:+.3f}**  "
        + ("→ Fehler stark korreliert, kaum Fusions-Spielraum."
           if r_resid > 0.5 else
           "→ Fehler nur teilweise korreliert, etwas Spielraum."),
        "", "## Gepaarter Wilcoxon (Ensemble vs. solo)", "",
        f"- Ensemble vs **{model}** (acc): {sline('ens_vs_deep_acc')}",
        f"- Ensemble vs **{model}** (AUC): {sline('ens_vs_deep_auc')}",
        f"- Ensemble vs RF (acc): {sline('ens_vs_rf_acc')}",
        f"- Ensemble vs RF (AUC): {sline('ens_vs_rf_auc')}",
        "", f"**Verdikt:** Fusion {verdict} "
        f"(vs {model}-solo: Δacc {d_acc:+.4f}, ΔAUC {d_auc:+.4f}).",
        "", f"Rohdaten: `{cv_out.relative_to(ROOT)}`.", "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_out.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\n-> {report_out}")


if __name__ == "__main__":
    main()

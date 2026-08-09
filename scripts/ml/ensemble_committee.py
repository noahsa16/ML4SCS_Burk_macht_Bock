"""N-Wege-Ensemble-Komitees aus vorhandenen OOF-CSVs — reines CPU-Post-Processing.

Alle OOF-Probas liegen auf **identischen Folds** (LOSO-by-person, grouped-5-fold,
``random_state=42``, gleiche Session-Selektion), daher sind N-Wege-Ensembles ein
Join + Mittelwert auf vorhandenen CSVs — **kein GPU, kein Retraining**.

Das Tool nimmt beliebig viele OOF-Quellen (Modellnamen ->
``models/{name}_oof_legacy.csv`` oder direkte CSV-Pfade), joined sie per Session
auf nächstem ``t_center_ms`` (``fusion_utils.align_frames``), und rechnet **alle
2er/3er/…/Ner-Kombinationen** durch: Ensemble-acc/AUC (per-Fold, nativ),
mittlere Residuen-Korrelation ``r(a−y, b−y)`` (die Leitgröße — hoch = Modelle
irren gemeinsam, wenig Spielraum) und gepaarter Wilcoxon gegen das jeweils
**stärkste Solo-Mitglied** der Kombination.

CLI: ``python scripts/ml/ensemble_committee.py rf5 tcn6 inception [tcn_bigru …]``.
Output: ``reports/ensemble_committee.md`` + ``models/ensemble_committee.csv``.
"""
from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.fusion_utils import (  # noqa: E402
    align_frames, mean_proba, paired_metric, per_fold_metrics, residual_corr)

MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"


# ---- testbarer Kern ------------------------------------------------------

def committee_table(aligned: pd.DataFrame, members: list[str]) -> pd.DataFrame:
    """Alle Kombinationen (Größe 2..N) mit Ensemble-Metrik + Residuen-r + Wilcoxon.

    ``aligned`` trägt ``person_id``, ``y`` und je ein ``{m}_proba`` pro Mitglied.
    Vergleich pro Kombination gegen das **stärkste Solo-Mitglied** (höchste
    per-Fold-mean-acc). Rückgabe nach acc absteigend sortiert.
    """
    solo = {m: per_fold_metrics(aligned, f"{m}_proba") for m in members}
    solo_acc = {m: float(solo[m]["accuracy"].mean()) for m in members}

    rows = []
    for k in range(2, len(members) + 1):
        for combo in combinations(members, k):
            ens = mean_proba([aligned[f"{m}_proba"].to_numpy() for m in combo])
            ens_cv = per_fold_metrics(aligned.assign(_ens=ens), "_ens")
            best = max(combo, key=lambda m: solo_acc[m])
            pr = paired_metric(ens_cv, solo[best], "accuracy")
            acc = float(ens_cv["accuracy"].mean())
            rows.append({
                "members": "+".join(combo),
                "n": k,
                "acc": acc,
                "auc": float(ens_cv["roc_auc"].mean()),
                "r_resid": residual_corr(aligned, list(combo)),
                "best_solo": best,
                "best_solo_acc": solo_acc[best],
                "delta_acc": acc - solo_acc[best],
                "p_acc": pr["p_value"],
                "significant": pr["significant"],
            })
    return pd.DataFrame(rows).sort_values("acc", ascending=False).reset_index(drop=True)


def solo_table(aligned: pd.DataFrame, members: list[str]) -> pd.DataFrame:
    """Per-Mitglied Solo-acc/AUC (per-Fold-Mittel) — die Baselines."""
    rows = []
    for m in members:
        cv = per_fold_metrics(aligned, f"{m}_proba")
        rows.append({"member": m, "acc": float(cv["accuracy"].mean()),
                     "auc": float(cv["roc_auc"].mean())})
    return pd.DataFrame(rows).sort_values("acc", ascending=False).reset_index(drop=True)


# ---- Plumbing (IO / Report) ----------------------------------------------

def _resolve(spec: str) -> tuple[str, Path]:
    """CLI-Spec -> (Mitglieds-Name, OOF-Pfad). Modellname oder direkter CSV-Pfad."""
    p = Path(spec)
    if p.suffix == ".csv":
        return p.stem.replace("_oof_legacy", ""), p
    return spec, MODEL_DIR / f"{spec}_oof_legacy.csv"


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("members", nargs="+",
                    help="Modellnamen (models/{name}_oof_legacy.csv) oder OOF-CSV-Pfade")
    return ap


def main() -> None:
    args = _build_parser().parse_args()
    frames: dict[str, pd.DataFrame] = {}
    for spec in args.members:
        name, path = _resolve(spec)
        if not path.exists():
            raise FileNotFoundError(f"OOF nicht gefunden: {path} (für '{spec}')")
        frames[name] = pd.read_csv(path)

    aligned = align_frames(frames)
    members = list(frames)
    solo = solo_table(aligned, members)
    committee = committee_table(aligned, members)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = MODEL_DIR / "ensemble_committee.csv"
    committee.to_csv(csv_out, index=False)
    _write_report(members, len(aligned), solo, committee, csv_out)


def _write_report(members, n_win, solo, committee, csv_out) -> None:
    winners = committee[committee["significant"] & (committee["delta_acc"] > 0)]
    lines = [
        "# N-Wege-Ensemble-Komitees (Post-Processing auf OOF-CSVs)", "",
        f"Mitglieder: {', '.join(members)}. Legacy-Pool, nativ, LOSO-by-person, "
        f"{n_win} aligned Fenster. Reines Post-Processing (kein GPU/Retraining).", "",
        "## Solo-Baselines (per-Fold acc/AUC)", "",
        "| Modell | acc | AUC |", "|---|---|---|",
        *[f"| {r.member} | {r.acc:.4f} | {r.auc:.4f} |" for r in solo.itertuples()],
        "", "## Komitees — alle Kombinationen (nach acc)", "",
        "Δacc = Ensemble − stärkstes Solo-Mitglied; r = mittlere Residuen-"
        "Korrelation (niedrig = mehr Fusions-Spielraum); p = gepaarter Wilcoxon "
        "vs. bestes Solo.", "",
        "| Komitee | acc | AUC | r_resid | vs. best solo | Δacc | p | sig |",
        "|---|---|---|---|---|---|---|---|",
        *[f"| {r.members} | {r.acc:.4f} | {r.auc:.4f} | {r.r_resid:+.3f} | "
          f"{r.best_solo} ({r.best_solo_acc:.4f}) | {r.delta_acc:+.4f} | "
          f"{r.p_acc:.4f} | {'**JA**' if r.significant and r.delta_acc > 0 else 'nein'} |"
          for r in committee.itertuples()],
        "", "## Lesart", "",
        (f"**{len(winners)} Komitee(s) heben das jeweils beste Solo-Mitglied "
         f"signifikant** (p<0.05, Δacc>0): "
         + ", ".join(f"`{r.members}` (Δ{r.delta_acc:+.4f})" for r in winners.itertuples())
         if len(winners) else
         "**Kein Komitee** hebt sein bestes Solo-Mitglied signifikant — "
         "die Residuen sind zu korreliert (geteilter systematischer Fehler an "
         "denselben Fenstern bleibt im Mittel erhalten)."),
        "", f"Rohdaten: `{csv_out.relative_to(ROOT)}`.", "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "ensemble_committee.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\n-> {REPORTS_DIR / 'ensemble_committee.md'}")


if __name__ == "__main__":
    main()

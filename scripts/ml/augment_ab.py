"""Ehrliches Augmentation-A/B fuer die Deep-Netze (gegen den Seed-Rausch-Floor).

Faehrt EIN Modell auf EINEM Pool, je {aug, no-aug} ueber mehrere Seeds,
mittelt per-Fold ueber die Seeds und testet die Differenz gepaart
(Wilcoxon, src.evaluation.significance) auf accuracy + ROC-AUC. Default:
tcn6 @ 5 s, pool modern, Seeds 42/43/44 -- schluepft in das 3-Seed-Protokoll
der modern-Headline.

    python scripts/ml/augment_ab.py                       # tcn6, modern, 5 s
    python scripts/ml/augment_ab.py --pool legacy         # Bestaetigung N=15
    python scripts/ml/augment_ab.py --seeds 42 43 44 45    # mehr Seeds

Output: models/augment_ab_{pool}.csv (significance-kompatibel: held_out +
accuracy + roc_auc je condition) + reports/augment_ab.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.evaluation.significance import paired_fold_test
from src.training.deep.train_loso import train_deep_loso
MODEL_DIR = ROOT / "models"
REPORT = ROOT / "reports" / "augment_ab.md"



def _seed_average(folds_list: list[pd.DataFrame]) -> pd.DataFrame:
    """Per-held_out-Mittel von accuracy + roc_auc ueber mehrere Seed-Laeufe."""
    cat = pd.concat(folds_list, ignore_index=True)
    return (
        cat.groupby("held_out", as_index=False)[["accuracy", "roc_auc"]]
        .mean()
        .sort_values("held_out")
        .reset_index(drop=True)
    )


def _paired(aug: pd.DataFrame, base: pd.DataFrame, metric: str) -> dict:
    """Gepaarter Wilcoxon auf gemeinsamen Folds, Differenz aug - base."""
    m = aug[["held_out", metric]].merge(
        base[["held_out", metric]], on="held_out", suffixes=("_aug", "_base")
    )
    res = paired_fold_test(
        m[f"{metric}_aug"].to_numpy(), m[f"{metric}_base"].to_numpy()
    )
    res["metric"] = metric
    return res


def _cohort_means(runs: list[pd.DataFrame]) -> list[float]:
    """Kohorten-Mean-Accuracy je Seed-Lauf -- fuer das Seed-σ-Band."""
    return [float(df["accuracy"].mean()) for df in runs]


def _write_report(
    model: str, pool: str, win: int, seeds: list[int],
    base_runs: list[pd.DataFrame], aug_runs: list[pd.DataFrame],
    base: pd.DataFrame, aug: pd.DataFrame,
    res_acc: dict, res_auc: dict, out_csv: Path,
) -> None:
    import statistics as st

    bm, am = _cohort_means(base_runs), _cohort_means(aug_runs)
    base_mu, base_sd = st.mean(bm), (st.pstdev(bm) if len(bm) > 1 else 0.0)
    aug_mu, aug_sd = st.mean(am), (st.pstdev(am) if len(am) > 1 else 0.0)
    merged = aug.merge(base, on="held_out", suffixes=("_aug", "_base"))

    lines = [
        f"# Augmentation-A/B — {model} @ {win}s, pool={pool}",
        "",
        f"Seeds: {seeds} | Folds: {len(aug)} | Transforms: scale(0.8-1.2) + rotate(+/-10 deg)",
        "",
        "## Kohorten-Mean-Accuracy (Seed-Spread)",
        f"- no-aug: {base_mu:.4f} ± {base_sd:.4f} (Seed-σ)",
        f"- aug:    {aug_mu:.4f} ± {aug_sd:.4f} (Seed-σ)",
        f"- Δ (aug − no-aug): {aug_mu - base_mu:+.4f}",
        "",
        "## Gepaarter Wilcoxon (seed-gemittelte Folds, aug − no-aug)",
        f"- accuracy: Δ_median {res_acc['median_diff']:+.4f}, "
        f"Δ_mean {res_acc['mean_diff']:+.4f}, p={res_acc['p_value']:.4f}, "
        f"signifikant={res_acc['significant']}",
        f"- roc_auc:  Δ_median {res_auc['median_diff']:+.4f}, "
        f"Δ_mean {res_auc['mean_diff']:+.4f}, p={res_auc['p_value']:.4f}, "
        f"signifikant={res_auc['significant']}",
        "",
        "## Verdikt",
        "Gewinn NUR wenn Δ außerhalb des Seed-σ-Bands UND p < 0.05 (acc + AUC). "
        "Sonst als Rauschen reporten — kein Headline-Claim.",
        "",
        "## Per-Fold (seed-gemittelt)",
        "| held_out | acc no-aug | acc aug | Δacc | auc no-aug | auc aug |",
        "|---|---|---|---|---|---|",
    ]
    for r in merged.itertuples():
        lines.append(
            f"| {r.held_out} | {r.accuracy_base:.3f} | {r.accuracy_aug:.3f} | "
            f"{r.accuracy_aug - r.accuracy_base:+.3f} | "
            f"{r.roc_auc_base:.3f} | {r.roc_auc_aug:.3f} |"
        )
    lines += ["", f"Daten: `{out_csv.relative_to(ROOT)}`"]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(prog="python scripts/ml/augment_ab.py")
    p.add_argument("--model", default="tcn6",
                   choices=["cnn", "lstm", "gru", "tcn", "tcn6"])
    p.add_argument("--pool", default="modern", choices=["legacy", "modern"])
    p.add_argument("--win", type=int, default=5)
    p.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    args = p.parse_args()

    base_runs, aug_runs = [], []
    for seed in args.seeds:
        print(f"\n##### seed={seed} | no-aug")
        base_runs.append(train_deep_loso(
            args.model, args.win, pool=args.pool, seed=seed, augment=False))
        print(f"\n##### seed={seed} | aug")
        aug_runs.append(train_deep_loso(
            args.model, args.win, pool=args.pool, seed=seed, augment=True))

    base = _seed_average(base_runs)
    aug = _seed_average(aug_runs)

    out_csv = MODEL_DIR / f"augment_ab_{args.pool}.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(
        [base.assign(condition="no_aug"), aug.assign(condition="aug")],
        ignore_index=True,
    ).to_csv(out_csv, index=False)

    res_acc = _paired(aug, base, "accuracy")
    res_auc = _paired(aug, base, "roc_auc")
    _write_report(args.model, args.pool, args.win, args.seeds,
                  base_runs, aug_runs, base, aug, res_acc, res_auc, out_csv)

    print(f"\n-> {out_csv}")
    print(f"-> {REPORT}")
    print(f"acc: Δ_mean {res_acc['mean_diff']:+.4f} p={res_acc['p_value']:.4f} "
          f"sig={res_acc['significant']}")
    print(f"auc: Δ_mean {res_auc['mean_diff']:+.4f} p={res_auc['p_value']:.4f} "
          f"sig={res_auc['significant']}")


if __name__ == "__main__":
    main()

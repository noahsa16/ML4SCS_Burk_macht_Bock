"""tsai-LOSO: InceptionTime / XceptionTime / ResNet / TSiTPlus gegen die
nativen RF-/TCN-Baselines, im identischen LOSO-by-person-Protokoll.

Drei Modi:

- **full** (Default, kein Argument): alle Modelle x WIN_SECS x SEEDS in einem
  Prozess, Seed-gemittelte Probas pro Fold (lokaler Komplett-Lauf).
- **trial** (``--model X --win W --seed S``): genau EIN Modell/Fenster/Seed
  ueber alle 20 Folds — CI-Matrix-Job. Schreibt per-window-OOF nach
  ``models/tsai/tsai_oof_{model}_win{W}_seed{S}.csv`` (person_id, session_id,
  t_center_ms, label, proba) fuer das Seed-Ensemble im Collect.
- **collect** (``--collect``): liest alle OOFs unter ``models/tsai/``,
  rechnet per-Seed-Fold-Metriken + **Seed-Ensemble** (Proba-Mittel ueber
  Seeds) und schreibt significance-kompatible CVs
  (``models/tsai_{model}_win{W}_cv.csv``) + ``reports/tsai_loso.md``.

Wiederverwendet die Deep-Pipeline (train_one_model, load_session_raw,
fold_metrics, _pool_plan) — nur das Modell ist getauscht.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

SEEDS = [42, 123, 7]
POOL = "legacy"
WIN_SECS = [1, 5]
MODEL_NAMES = ["InceptionTime", "XceptionTime", "ResNet", "TSiTPlus"]
OOF_DIR = ROOT / "models" / "tsai"
REPORT = ROOT / "reports" / "tsai_loso.md"
# N=20-Referenzen (nativ, aus tcn_rf_fusion-Lauf 2026-07-01; tcn6 = EIN Seed)
BASELINES = "RF-nativ-5s 0.879/0.953 | tcn6-nativ-5s 0.898/0.969 (1 Seed) | RF@1s 0.869/0.946"


def _lazy_imports():
    import torch
    import torch.nn as nn
    from tsai.models.InceptionTime import InceptionTime
    from tsai.models.ResNet import ResNet
    from tsai.models.TSiTPlus import TSiTPlus
    from tsai.models.XceptionTime import XceptionTime

    from src.training.deep.data import load_session_raw
    from src.training.deep.train_loso import (
        POOL_FS, _pool_plan, _set_seed, fold_metrics, predict_proba,
        train_one_model,
    )
    from src.training.train_loso import _select_sessions

    classes = {"InceptionTime": InceptionTime, "XceptionTime": XceptionTime,
               "ResNet": ResNet, "TSiTPlus": TSiTPlus}
    return (torch, nn, classes, load_session_raw, POOL_FS, _pool_plan,
            _set_seed, fold_metrics, predict_proba, train_one_model,
            _select_sessions)


def _build_model(nn, cls, c_in: int, seq_len: int):
    class _TsaiWrapper(nn.Module):
        """Adaptiert tsais (batch, 2)-Output auf (batch,) fuer BCEWithLogitsLoss."""

        def __init__(self, backbone) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, x):
            out = self.backbone(x)
            return out[:, 1] - out[:, 0]

    kw = dict(c_in=c_in, c_out=2)
    if "seq_len" in cls.__init__.__code__.co_varnames:
        kw["seq_len"] = seq_len
    try:
        backbone = cls(**kw)
    except TypeError:
        kw["seq_len"] = seq_len
        backbone = cls(**kw)
    return _TsaiWrapper(backbone)


def run_loso(win_sec: int, model_names: list[str], seeds: list[int],
             oof_out: Path | None = None) -> pd.DataFrame:
    (torch, nn, classes, load_session_raw, POOL_FS, _pool_plan, _set_seed,
     fold_metrics, predict_proba, train_one_model, _select_sessions) = _lazy_imports()

    fs = POOL_FS[POOL]
    seq_len = win_sec * fs
    sessions = _select_sessions(include_all=False, min_windows=20, profile="50hz")
    plan = _pool_plan(sessions, POOL)
    print(f"\n{'='*60}")
    print(f"tsai LOSO  win={win_sec}s  pool={POOL}  N={len(sessions)} sessions  "
          f"models={model_names}  seeds={seeds}")
    print(f"{'='*60}")

    all_X, all_y, all_meta = {}, {}, {}
    for _, sess in sessions.iterrows():
        sid = sess["session_id"]
        try:
            X, y, t = load_session_raw(
                sid, seq_len=seq_len, merged_suffix=plan[sid], zscore=False,
            )
        except Exception as e:
            print(f"  skip {sid}: {e}")
            continue
        all_X[sid], all_y[sid] = X, y
        all_meta[sid] = pd.DataFrame({"session_id": sid, "t_center_ms": t})

    persons = sessions["person_id"].unique()
    records, oof_rows = [], []

    for model_name in model_names:
        cls = classes[model_name]
        print(f"\n--- {model_name} @{win_sec}s ---")
        fold_accs, fold_aucs = [], []

        for person in persons:
            test_sids = sessions.loc[sessions["person_id"] == person, "session_id"].tolist()
            train_sids = sessions.loc[sessions["person_id"] != person, "session_id"].tolist()
            train_sids = [s for s in train_sids if s in all_X]
            test_sids = [s for s in test_sids if s in all_X]
            if not train_sids or not test_sids:
                continue

            test_X = np.concatenate([all_X[s] for s in test_sids])
            test_y = np.concatenate([all_y[s] for s in test_sids])
            test_df = pd.concat([all_meta[s] for s in test_sids], ignore_index=True)
            if len(np.unique(test_y)) < 2:
                continue

            # Val-Person: Train-Person mit wenigsten Sessions (deterministisch, kein Leak)
            val_person = sessions.loc[
                sessions["session_id"].isin(train_sids), "person_id"
            ].value_counts().index[-1]
            val_sids = [s for s in sessions.loc[
                sessions["person_id"] == val_person, "session_id"] if s in all_X]
            fit_sids = [s for s in train_sids if s not in val_sids]

            fit_X = np.concatenate([all_X[s] for s in fit_sids])
            fit_y = np.concatenate([all_y[s] for s in fit_sids])
            val_X = np.concatenate([all_X[s] for s in val_sids])
            val_y = np.concatenate([all_y[s] for s in val_sids])

            seed_probas = []
            for seed in seeds:
                _set_seed(seed)
                model = _build_model(nn, cls, test_X.shape[1], seq_len)
                model, _ = train_one_model(
                    model, fit_X, fit_y, val_X, val_y,
                    max_epochs=60, patience=8, batch_size=64, lr=1e-3,
                )
                seed_probas.append(predict_proba(model, test_X))
                del model
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()

            proba = np.mean(seed_probas, axis=0)
            metrics = fold_metrics(proba, test_y, test_df)
            acc, auc = metrics["accuracy"], metrics["roc_auc"]
            fold_accs.append(acc)
            fold_aucs.append(auc)
            print(f"  {person}: acc={acc:.3f}  AUC={auc:.3f}")
            records.append({"model": model_name, "win_sec": win_sec,
                            "held_out": person, "accuracy": acc, "auc": auc})
            if oof_out is not None:
                oof_rows.append(pd.DataFrame({
                    "person_id": person,
                    "session_id": test_df["session_id"].to_numpy(),
                    "t_center_ms": test_df["t_center_ms"].to_numpy(),
                    "label": test_y, "proba": proba,
                }))

        if fold_accs:
            print(f"  -> mean acc={np.mean(fold_accs):.3f}+/-{np.std(fold_accs):.3f}  "
                  f"AUC={np.mean(fold_aucs):.3f}+/-{np.std(fold_aucs):.3f}")

    if oof_out is not None and oof_rows:
        oof_out.parent.mkdir(parents=True, exist_ok=True)
        pd.concat(oof_rows, ignore_index=True).to_csv(oof_out, index=False)
        print(f"OOF -> {oof_out}")
    return pd.DataFrame(records)


def _fold_cv(oof: pd.DataFrame) -> pd.DataFrame:
    from sklearn.metrics import roc_auc_score
    rows = []
    for person, g in oof.groupby("person_id"):
        pred = (g["proba"].to_numpy() >= 0.5).astype(int)
        y = g["label"].to_numpy()
        auc = roc_auc_score(y, g["proba"]) if len(np.unique(y)) > 1 else float("nan")
        rows.append({"held_out": person, "accuracy": float((pred == y).mean()),
                     "roc_auc": float(auc)})
    return pd.DataFrame(rows)


def collect(oof_dir: Path) -> None:
    pat = re.compile(r"tsai_oof_(?P<model>\w+)_win(?P<win>\d+)_seed(?P<seed>\d+)\.csv")
    groups: dict[tuple[str, int], dict[int, pd.DataFrame]] = {}
    for f in sorted(oof_dir.glob("tsai_oof_*.csv")):
        m = pat.match(f.name)
        if not m:
            continue
        key = (m["model"], int(m["win"]))
        groups.setdefault(key, {})[int(m["seed"])] = pd.read_csv(f)
    if not groups:
        raise SystemExit(f"Keine tsai_oof_*.csv unter {oof_dir}")

    lines = ["# tsai-LOSO: Seed-Ensembles vs. RF/TCN-Baselines", "",
             f"Pool={POOL}, LOSO-by-person. Baselines (N=20): {BASELINES}", "",
             "| Modell | win | Seeds | per-Seed acc (mean+/-std ueber Seeds) | "
             "**Seed-Ensemble acc+/-sigma / AUC** |", "|---|---|---|---|---|"]
    for (model, win), by_seed in sorted(groups.items()):
        per_seed_means = []
        for seed, oof in sorted(by_seed.items()):
            cv = _fold_cv(oof)
            per_seed_means.append(cv["accuracy"].mean())
        keys = ["person_id", "session_id", "t_center_ms"]
        merged = None
        for seed, oof in sorted(by_seed.items()):
            o = oof.rename(columns={"proba": f"proba_{seed}"})
            merged = o if merged is None else merged.merge(
                o[keys + [f"proba_{seed}"]], on=keys, validate="1:1")
        proba_cols = [c for c in merged.columns if c.startswith("proba_")]
        merged["proba"] = merged[proba_cols].mean(axis=1)
        cv = _fold_cv(merged)
        out = ROOT / "models" / f"tsai_{model}_win{win}_cv.csv"
        cv.to_csv(out, index=False)
        ens_oof = ROOT / "models" / f"tsai_{model}_win{win}_ensemble_oof.csv"
        merged[keys + ["label", "proba"]].to_csv(ens_oof, index=False)
        lines.append(
            f"| {model} | {win}s | {len(by_seed)} | "
            f"{np.mean(per_seed_means):.3f}+/-{np.std(per_seed_means):.3f} | "
            f"**{cv['accuracy'].mean():.3f}+/-{cv['accuracy'].std(ddof=0):.3f} / "
            f"{cv['roc_auc'].mean():.3f}** |")
        print(f"{model} win{win}: ensemble acc {cv['accuracy'].mean():.3f} "
              f"({len(by_seed)} seeds) -> {out.name}")
    lines += ["", "Per-Modell-CVs sind `significance.py`-kompatibel "
              "(`python -m src.evaluation.significance A.csv B.csv`). "
              "Ensemble-OOFs (`*_ensemble_oof.csv`) tragen t_center_ms fuer "
              "HMM-Nachtests.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print(f"-> {REPORT}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", choices=MODEL_NAMES, default=None,
                   help="Trial-Modus: genau ein Modell (CI-Matrix-Job).")
    p.add_argument("--win", type=int, choices=[1, 5], default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--collect", action="store_true",
                   help="OOFs unter --dir zu Seed-Ensembles + Report einsammeln.")
    p.add_argument("--dir", type=Path, default=OOF_DIR)
    args = p.parse_args()

    if args.collect:
        collect(args.dir)
        return

    if args.model is not None:
        if args.win is None or args.seed is None:
            raise SystemExit("Trial-Modus braucht --win und --seed.")
        out = args.dir / f"tsai_oof_{args.model}_win{args.win}_seed{args.seed}.csv"
        run_loso(args.win, [args.model], [args.seed], oof_out=out)
        return

    # full mode: alles in einem Prozess (lokal), Seed-Mittel wie gehabt
    all_results = []
    for win_sec in WIN_SECS:
        all_results.append(run_loso(win_sec, MODEL_NAMES, SEEDS))
    results = pd.concat(all_results, ignore_index=True)
    out = ROOT / "models" / "tsai_loso.csv"
    results.to_csv(out, index=False)
    print(f"\nSaved -> {out}")
    summary = (results.groupby(["model", "win_sec"])[["accuracy", "auc"]]
               .agg(["mean", "std"]).round(3))
    print(summary.to_string())
    print(f"\nBaselines (N=20): {BASELINES}")


if __name__ == "__main__":
    main()

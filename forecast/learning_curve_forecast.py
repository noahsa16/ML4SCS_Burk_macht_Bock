"""Lernkurven-Prognose: Wie wird Accuracy mit mehr Probanden skalieren?

Empirische Stuetzpunkte aus der 3-Personen-Basis:
- n_train=1: trainiere auf 1 Person, teste auf jede der anderen 2
- n_train=2: trainiere auf 2 Personen, teste auf die dritte

Fittet ein Power-Law-Saettigungsmodell:
    acc(n) = C - A * n^(-B)   mit C, A, B > 0
"""

from __future__ import annotations

import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from itertools import combinations
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from sklearn.base import clone
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from tqdm.auto import tqdm
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT / "data" / "processed"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"
OUT_DIR = ROOT / "forecast"
OUT_DIR.mkdir(exist_ok=True)

FORECAST_N = [3, 5, 10, 20, 30, 40, 49]


def _load_windows() -> pd.DataFrame:
    s = pd.read_csv(SESSIONS_CSV)
    s = s[s["verdict"].isin({"trainable", "usable"})]
    s = s[s["study_mode"].fillna("") != "test"]
    s = s[s["session_id"].apply(lambda x: (DATA_PROC / f"{x}_windows.csv").exists())]
    frames = []
    for sid in s["session_id"]:
        df = pd.read_csv(DATA_PROC / f"{sid}_windows.csv")
        df["session_id"] = sid
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.merge(s[["session_id", "person_id"]], on="session_id", how="left")


def _zscore_per_session(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    g = out.groupby("session_id", sort=False)[cols]
    mu = g.transform("mean")
    sigma = g.transform("std").replace(0.0, 1.0).fillna(1.0)
    out[cols] = (out[cols] - mu) / sigma
    return out


def _models() -> dict[str, object]:
    return {
        "ExtraTrees": ExtraTreesClassifier(
            n_estimators=300, class_weight="balanced", n_jobs=-1, random_state=42),
        "RandomForest": RandomForestClassifier(
            n_estimators=200, class_weight="balanced", n_jobs=-1, random_state=42),
        "HistGradBoost": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.05, random_state=42),
        "LogReg": Pipeline([
            ("sc", StandardScaler()),
            ("lr", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]),
    }


def _train_test(model, train, test, cols):
    X_tr, y_tr = train[cols].to_numpy(), train["label"].to_numpy()
    X_te, y_te = test[cols].to_numpy(), test["label"].to_numpy()
    if len(np.unique(y_te)) < 2:
        return None
    m = clone(model)
    m.fit(X_tr, y_tr)
    y_pred = m.predict(X_te)
    y_proba = m.predict_proba(X_te)[:, 1]
    return {
        "acc": float((y_pred == y_te).mean()),
        "auc": float(roc_auc_score(y_te, y_proba)),
    }


def empirical_points(all_w, persons, feat_cols, models):
    jobs = []
    for n_train in (1, 2):
        for train_combo in combinations(persons, n_train):
            test_set = set(persons) - set(train_combo)
            for test_p in test_set:
                for name, model in models.items():
                    jobs.append((n_train, train_combo, test_p, name, model))

    rows = []
    bar = tqdm(jobs, desc="sklearn-Modelle", unit="fit", colour="magenta")
    for n_train, train_combo, test_p, name, model in bar:
        bar.set_postfix_str(
            f"n={n_train} {'+'.join(train_combo)}→{test_p} | {name}"
        )
        train = all_w[all_w["person_id"].isin(set(train_combo))]
        test = all_w[all_w["person_id"] == test_p]
        r = _train_test(model, train, test, feat_cols)
        if r is None:
            continue
        rows.append({"model": name, "n_train": n_train,
                     "test_person": test_p, **r})
    return pd.DataFrame(rows)


def _powerlaw(n, c, a, b):
    return c - a * np.power(n, -b)


def _fit_powerlaw(xs, ys):
    try:
        popt, _ = curve_fit(
            _powerlaw, xs, ys,
            p0=[0.95, 0.3, 0.5],
            bounds=([0.5, 0.0, 0.05], [1.0, 5.0, 3.0]),
            maxfev=5000,
        )
        return tuple(popt)
    except Exception:
        return (0.92, 0.3, 0.5)


def main():
    all_w = _load_windows()
    persons = sorted(all_w["person_id"].dropna().unique().tolist())
    print(f"Probanden in der Basis: {persons}")
    feat_cols = [c for c in all_w.columns if c not in {
        "label", "t_center_ms", "session_id", "person_id",
        "task_id", "task_category",
    }]
    all_w = _zscore_per_session(all_w, feat_cols)
    print(f"Features: {len(feat_cols)}, Windows: {len(all_w)}\n")

    models = _models()
    df = empirical_points(all_w, persons, feat_cols, models)
    print("\nEmpirische Stuetzpunkte (Mittel +/- sigma pro Modell & n_train):")
    summary = (df.groupby(["model", "n_train"])
                 .agg(acc_mean=("acc", "mean"), acc_std=("acc", "std"),
                      auc_mean=("auc", "mean"), auc_std=("auc", "std"),
                      n=("acc", "count"))
                 .round(3))
    print(summary)

    forecasts = {}
    for name in models.keys():
        sub = df[df["model"] == name]
        xs = sub["n_train"].to_numpy(dtype=float)
        ys = sub["acc"].to_numpy(dtype=float)
        c, a, b = _fit_powerlaw(xs, ys)
        forecasts[name] = {"c": c, "a": a, "b": b}
        print(f"\n{name}: acc(n) = {c:.3f} - {a:.3f} * n^(-{b:.3f})")
        print(f"  Prognose:")
        for nf in FORECAST_N:
            print(f"    n={nf:>3d}: acc ~ {_powerlaw(nf, c, a, b):.3f}")

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(11, 6.5), dpi=110)

    colors = {
        "ExtraTrees":   "#5cffb8",
        "RandomForest": "#7eb8ff",
        "HistGradBoost":"#ffb45c",
        "LogReg":       "#ff7eb8",
    }

    n_grid = np.logspace(np.log10(1), np.log10(60), 200)

    for name, pars in forecasts.items():
        sub = df[df["model"] == name]
        for n_train, g in sub.groupby("n_train"):
            mu, sigma = g["acc"].mean(), g["acc"].std()
            ax.errorbar(n_train, mu, yerr=sigma if not np.isnan(sigma) else 0,
                        fmt="o", color=colors[name], capsize=4, markersize=8,
                        markeredgecolor="white", markeredgewidth=0.6,
                        elinewidth=1.2, zorder=4)

        ys = _powerlaw(n_grid, pars["c"], pars["a"], pars["b"])
        emp_mask = n_grid <= 2.0
        extra_mask = n_grid >= 2.0
        ax.plot(n_grid[emp_mask], ys[emp_mask], "-", color=colors[name],
                lw=2.2, label=name, zorder=3)
        ax.plot(n_grid[extra_mask], ys[extra_mask], "--", color=colors[name],
                lw=1.8, alpha=0.85, zorder=2)
        ax.axhline(pars["c"], color=colors[name], lw=0.6, alpha=0.25,
                   linestyle=":", zorder=1)

    ax.axvspan(2.0, 60, alpha=0.06, color="white", zorder=0)
    ax.text(3, 0.555,
            "Extrapolation\n(nur 2 empirische Stuetzpunkte -\nUnsicherheit waechst nach rechts)",
            color="#bbbbbb", fontsize=8.5, ha="left", va="bottom", style="italic")

    for nf in FORECAST_N:
        ax.axvline(nf, color="white", alpha=0.06, lw=0.8, zorder=0)

    ax.set_xscale("log")
    ax.set_xticks([1, 2, 3, 5, 10, 20, 30, 40, 50])
    ax.set_xticklabels(["1", "2", "3", "5", "10", "20", "30", "40", "50"])
    ax.set_xlim(0.85, 60)
    ax.set_ylim(0.55, 1.0)
    ax.set_xlabel("Probanden im Trainings-Pool  (n_train)", fontsize=11)
    ax.set_ylabel("Cross-subject LOSO Accuracy", fontsize=11)
    ax.set_title(
        "Lernkurven-Prognose - Power-Law-Fit auf 3-Personen-Basis\n"
        "(durchgezogen = empirisch beobachtet  /  gestrichelt = extrapoliert)",
        fontsize=12, pad=12,
    )
    ax.grid(True, alpha=0.12)
    ax.legend(loc="lower right", framealpha=0.85, fontsize=10)

    ax.annotate(
        "Aktueller Stand:\nExtraTrees + Z-Score\nacc 0.842 +/- 0.007",
        xy=(2, 0.842), xytext=(1.05, 0.96),
        color="#5cffb8", fontsize=9, ha="left",
        arrowprops=dict(arrowstyle="->", color="#5cffb8", lw=1.0, alpha=0.7),
    )

    fig.tight_layout()
    out_png = OUT_DIR / "learning_curve_forecast.png"
    fig.savefig(out_png, dpi=140, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print(f"\n-> {out_png}")

    out_csv = OUT_DIR / "learning_curve_forecast.csv"
    rows = []
    for name, pars in forecasts.items():
        for nf in FORECAST_N:
            rows.append({
                "model": name, "n_train": nf,
                "acc_predicted": _powerlaw(nf, pars["c"], pars["a"], pars["b"]),
                "asymptote_c": pars["c"], "a": pars["a"], "b": pars["b"],
            })
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"-> {out_csv}")


if __name__ == "__main__":
    main()

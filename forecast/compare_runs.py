"""Vergleich aller historischen Lernkurven-Runs.

Liest jede ``forecast/learning_curve_raw_all_n*.csv``, fittet pro
(Modell, N_probanden) das Power-Law neu und rendert eine interaktive
Plotly-HTML mit zwei Subplots:

  oben:  Lernkurven pro (Modell, N) - eine Linie je Run, alle Modelle
         eines Runs in derselben Farbe; toggle pro Eintrag in der Legende.
  unten: Asymptote C vs N pro Modell - zeigt, ob der Forecast
         stabilisiert (Linie wird flach) oder noch wandert.

Output: ``forecast/learning_curve_compare.html``.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.optimize import curve_fit

OUT_DIR = Path(__file__).resolve().parent
RAW_GLOB = "learning_curve_raw_all_n*.csv"
N_PATTERN = re.compile(r"_n(\d+)\.csv$")

COLORS = {
    "ExtraTrees":    "#5cffb8",
    "RandomForest":  "#7eb8ff",
    "HistGradBoost": "#ffb45c",
    "XGBoost":       "#ff9a4d",
    "LogReg":        "#ff7eb8",
    "DeepMLP":       "#c890ff",
    "1D-CNN":        "#ffd95c",
    "BiLSTM":        "#a8ff5c",
    "Transformer":   "#5ce3ff",
}
MODEL_ORDER = list(COLORS.keys())


def _power(n, c, a, b):
    return c - a * np.power(n, -b)


def _fit(xs, ys):
    try:
        popt, _ = curve_fit(
            _power, xs, ys, p0=[0.95, 0.3, 0.4],
            bounds=([0.5, 0.0, 0.05], [1.0, 5.0, 3.0]), maxfev=5000,
        )
        return tuple(popt)
    except Exception:
        return None


def _load_runs() -> dict[int, pd.DataFrame]:
    runs: dict[int, pd.DataFrame] = {}
    for path in sorted(OUT_DIR.glob(RAW_GLOB)):
        m = N_PATTERN.search(path.name)
        if not m:
            continue
        n = int(m.group(1))
        df = pd.read_csv(path)
        if "n_persons" not in df.columns:
            df["n_persons"] = n
        runs[n] = df
    return runs


def main():
    runs = _load_runs()
    if not runs:
        raise SystemExit(
            f"No raw-data files matching {RAW_GLOB} in {OUT_DIR}. "
            "Run forecast/learning_curve.py first."
        )

    ns = sorted(runs.keys())
    print(f"Found runs for N = {ns}")
    for n in ns:
        models = sorted(runs[n]["model"].unique())
        print(f"  N={n}: {len(runs[n])} rows, models={models}")

    # Fit power-law per (N, model)
    fits: dict[tuple[int, str], tuple[float, float, float]] = {}
    for n, df in runs.items():
        for model, sub in df.groupby("model"):
            popt = _fit(sub["n_train"].to_numpy(float),
                        sub["acc"].to_numpy(float))
            if popt is not None:
                fits[(n, model)] = popt

    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.12,
        subplot_titles=(
            "Lernkurven (Power-Law-Fits pro Run)",
            "Asymptote C vs Anzahl Probanden im Run  -  je flacher, desto stabiler der Forecast",
        ),
    )

    n_grid = np.logspace(np.log10(1), np.log10(110), 250)

    # Top: one trace per (N, model) — solid for newest N, faded for older
    n_max = max(ns)

    def _opacity_for(n_run: int) -> float:
        if len(ns) == 1:
            return 1.0
        return 0.35 + 0.65 * ((n_run - min(ns)) / (n_max - min(ns)))

    models_in_data = sorted(
        {m for df in runs.values() for m in df["model"].unique()},
        key=lambda m: MODEL_ORDER.index(m) if m in MODEL_ORDER else 999,
    )

    for model in models_in_data:
        color = COLORS.get(model, "#cccccc")
        group = model
        for n_run in ns:
            key = (n_run, model)
            if key not in fits:
                continue
            c, a, b = fits[key]
            ys = _power(n_grid, c, a, b)
            opacity = _opacity_for(n_run)

            fig.add_trace(
                go.Scatter(
                    x=n_grid, y=ys, mode="lines",
                    name=f"{model}  (N={n_run})",
                    legendgroup=group, legendgrouptitle_text=model,
                    line=dict(color=color, width=2.2,
                              dash="solid" if n_run == n_max else "dot"),
                    opacity=opacity,
                    hovertemplate=(f"<b>{model}</b>  Run N={n_run}<br>"
                                   "n_train=%{x:.1f}<br>acc=%{y:.3f}"
                                   "<extra></extra>"),
                ),
                row=1, col=1,
            )

            sub = runs[n_run]
            sub = sub[sub["model"] == model]
            agg = sub.groupby("n_train")["acc"].agg(["mean", "std"]).reset_index()
            fig.add_trace(
                go.Scatter(
                    x=agg["n_train"], y=agg["mean"],
                    error_y=dict(type="data",
                                 array=agg["std"].fillna(0).values,
                                 thickness=1.0, color=color, width=3),
                    mode="markers", name=f"{model} N={n_run} pts",
                    legendgroup=group, showlegend=False,
                    marker=dict(color=color, size=8, opacity=opacity,
                                line=dict(color="white", width=0.6)),
                    hovertemplate=(f"<b>{model}</b>  Run N={n_run}<br>"
                                   "n_train=%{x} (empirisch)<br>"
                                   "acc=%{y:.3f}<extra></extra>"),
                ),
                row=1, col=1,
            )

        # Bottom: asymptote C drift
        xs_drift = []
        ys_drift = []
        for n_run in ns:
            if (n_run, model) in fits:
                xs_drift.append(n_run)
                ys_drift.append(fits[(n_run, model)][0])
        if xs_drift:
            fig.add_trace(
                go.Scatter(
                    x=xs_drift, y=ys_drift,
                    mode="lines+markers", name=model,
                    legendgroup=group, showlegend=False,
                    line=dict(color=color, width=2.0),
                    marker=dict(color=color, size=10,
                                line=dict(color="white", width=0.8)),
                    hovertemplate=(f"<b>{model}</b><br>Run N=%{{x}}<br>"
                                   "Asymptote C=%{y:.3f}<extra></extra>"),
                ),
                row=2, col=1,
            )

    fig.update_xaxes(
        type="log",
        tickvals=[1, 2, 3, 5, 10, 20, 30, 50, 70, 100],
        ticktext=["1", "2", "3", "5", "10", "20", "30", "50", "70", "100"],
        range=[np.log10(0.85), np.log10(110)],
        title_text="Probanden im Trainings-Pool  (n_train)",
        gridcolor="rgba(255,255,255,0.08)",
        row=1, col=1,
    )
    fig.update_yaxes(
        title_text="Cross-subject LOSO Accuracy",
        range=[0.40, 1.0], gridcolor="rgba(255,255,255,0.08)",
        row=1, col=1,
    )
    fig.update_xaxes(
        title_text="Anzahl Probanden im Run  (N)",
        tickvals=ns, ticktext=[str(n) for n in ns],
        gridcolor="rgba(255,255,255,0.08)",
        row=2, col=1,
    )
    fig.update_yaxes(
        title_text="Asymptote C  (extrapolierte Max-Accuracy)",
        gridcolor="rgba(255,255,255,0.08)",
        row=2, col=1,
    )

    fig.update_layout(
        title=dict(
            text=(f"Lernkurven-Vergleich: Runs N={min(ns)} ... N={max(ns)}"
                  "<br><sub>Klick auf Modell in Legende = aus/ein  |  "
                  "Doppelklick = nur dieses Modell  |  "
                  "ausgeblasste Linien = ältere Runs (gepunktet)</sub>"),
            x=0.5, xanchor="center",
        ),
        template="plotly_dark", hovermode="closest",
        legend=dict(orientation="v", x=1.02, y=1.0,
                    bgcolor="rgba(0,0,0,0.4)", groupclick="togglegroup"),
        margin=dict(l=70, r=220, t=100, b=60),
        width=1300, height=900,
    )

    out_html = OUT_DIR / "learning_curve_compare.html"
    fig.write_html(str(out_html), include_plotlyjs="cdn", full_html=True)
    print(f"\n-> {out_html}")


if __name__ == "__main__":
    main()

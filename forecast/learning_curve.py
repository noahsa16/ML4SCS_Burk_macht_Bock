"""Lernkurven-Prognose ueber alle Modellfamilien.

Trainiert klassische sklearn-Modelle (ExtraTrees / RandomForest /
HistGradBoost / LogReg) auf den 88 engineered features UND PyTorch-
Architekturen (DeepMLP auf features; 1D-CNN / BiLSTM / Transformer auf
raw IMU 50x6) auf denselben Person-Splits, misst wie Accuracy mit der
Anzahl Trainings-Probanden skaliert, und extrapoliert per Power-Law-
Saettigungsfit auf n=99.

Empirische Stuetzpunkte pro Modell:
- n_train=k: alle C(n_persons, k) Trainings-Kombinationen, jede
  verbleibende Person als Test-Fold (k=1..n_persons-1).

Outputs (N=Anzahl Probanden in der Datenbasis):
- forecast/learning_curve_n{N}.csv         -- Power-Law-Prognose pro Modell
- forecast/learning_curve_raw_all_n{N}.csv -- pro-Fold Rohmessungen
- forecast/learning_curve_n{N}.png         -- vereinter Graph (alle Modelle)
"""

from __future__ import annotations

import os
# Why: PyTorch and XGBoost each ship their own libomp.dylib on macOS arm64.
# Loading both in one Python process triggers __kmp_suspend_initialize_thread
# segfaults. Apple's documented workaround; must be set before any import that
# pulls in OpenMP (torch, xgboost, numpy with MKL...). Single-threaded fallback
# for XGBoost would also work but at noticeable slowdown.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import argparse
from itertools import combinations
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.optimize import curve_fit
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
DATA_PROC = ROOT / "data" / "processed"
SESSIONS_CSV = ROOT / "data" / "sessions.csv"
OUT_DIR = ROOT / "forecast"

FS_HZ = 50
WIN_SAMPLES = 50
STRIDE_SAMPLES = 25
WRITING_THRESH = 0.6
MAX_GAP_MS = 300

EPOCHS = 30
BATCH = 128
LR = 1e-3
WEIGHT_DECAY = 1e-4
PATIENCE = 6
DEVICE = "cpu"  # overridden in main() from --device flag
SEED = 42


def _resolve_device(arg: str) -> str:
    """Pick a torch device. 'auto' prefers mps > cuda > cpu when available."""
    if arg == "auto":
        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    if arg == "mps" and not (
        torch.backends.mps.is_available() and torch.backends.mps.is_built()
    ):
        print("[warn] --device=mps requested but not available; falling back to cpu")
        return "cpu"
    if arg == "cuda" and not torch.cuda.is_available():
        print("[warn] --device=cuda requested but not available; falling back to cpu")
        return "cpu"
    return arg

FORECAST_N = [3, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 99]


def _smooth_labels(labels: np.ndarray, max_gap: int) -> np.ndarray:
    if max_gap <= 0:
        return labels.astype(np.int8)
    out = labels.astype(np.int8).copy()
    n = len(out)
    i = 0
    while i < n:
        if out[i] == 1:
            j = i
            while j < n and out[j] == 1:
                j += 1
            k = j
            while k < n and out[k] == 0:
                k += 1
            if k < n and (k - j) <= max_gap:
                out[j:k] = 1
            i = k
        else:
            i += 1
    return out


def _build_raw_windows_for_session(sid: str) -> tuple[np.ndarray, np.ndarray]:
    df = pd.read_csv(DATA_PROC / f"{sid}_merged.csv")
    imu = df[["ax", "ay", "az", "rx", "ry", "rz"]].to_numpy(dtype=np.float32)
    lbl = df["label_writing"].to_numpy(dtype=np.int8)
    max_gap_samples = int(round(MAX_GAP_MS / 1000.0 * FS_HZ))
    lbl = _smooth_labels(lbl, max_gap_samples)
    Xs, ys = [], []
    for start in range(0, len(imu) - WIN_SAMPLES + 1, STRIDE_SAMPLES):
        end = start + WIN_SAMPLES
        Xs.append(imu[start:end])
        ys.append(int(lbl[start:end].mean() >= WRITING_THRESH))
    return np.stack(Xs), np.array(ys, dtype=np.int64)


def _load_data():
    s = pd.read_csv(SESSIONS_CSV)
    s = s[s["verdict"].isin({"trainable", "usable"})]
    s = s[s["study_mode"].fillna("") != "test"]
    s = s[s["session_id"].apply(lambda x: (DATA_PROC / f"{x}_merged.csv").exists())]

    raw_per_sid, feat_per_sid, y_per_sid, sid_to_person = {}, {}, {}, {}
    for _, row in s.iterrows():
        sid, person = row["session_id"], row["person_id"]
        sid_to_person[sid] = person

        Xraw, y = _build_raw_windows_for_session(sid)
        mu = Xraw.mean(axis=(0, 1), keepdims=True)
        sigma = Xraw.std(axis=(0, 1), keepdims=True)
        sigma[sigma == 0] = 1.0
        Xraw = (Xraw - mu) / sigma
        raw_per_sid[sid] = Xraw.astype(np.float32)
        y_per_sid[sid] = y

        wf = pd.read_csv(DATA_PROC / f"{sid}_windows.csv")
        feat_cols = [c for c in wf.columns if c not in
                     {"label", "t_center_ms", "task_id", "task_category"}]
        F = wf[feat_cols].to_numpy(dtype=np.float32)
        mu = F.mean(axis=0, keepdims=True)
        sigma = F.std(axis=0, keepdims=True)
        sigma[sigma == 0] = 1.0
        F = (F - mu) / sigma

        n = min(len(F), len(Xraw))
        feat_per_sid[sid] = F[:n].astype(np.float32)
        raw_per_sid[sid] = raw_per_sid[sid][:n]
        y_per_sid[sid] = y_per_sid[sid][:n]
    return raw_per_sid, feat_per_sid, y_per_sid, sid_to_person


class DeepMLP(nn.Module):
    def __init__(self, in_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 128), nn.BatchNorm1d(128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, 64), nn.BatchNorm1d(64), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(64, 32), nn.BatchNorm1d(32), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(32, 2),
        )

    def forward(self, x):
        return self.net(x)


class CNN1D(nn.Module):
    def __init__(self):
        super().__init__()
        self.feat = nn.Sequential(
            nn.Conv1d(6, 32, kernel_size=5, padding=2), nn.BatchNorm1d(32), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(32, 64, kernel_size=3, padding=1), nn.BatchNorm1d(64), nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(64, 64, kernel_size=3, padding=1), nn.BatchNorm1d(64), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(nn.Flatten(), nn.Dropout(0.3), nn.Linear(64, 2))

    def forward(self, x):
        return self.head(self.feat(x.transpose(1, 2)))


class BiLSTM(nn.Module):
    def __init__(self, hidden=48, layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size=6, hidden_size=hidden,
                            num_layers=layers, batch_first=True,
                            bidirectional=True, dropout=0.2 if layers > 1 else 0.0)
        self.head = nn.Sequential(
            nn.LayerNorm(hidden * 2),
            nn.Dropout(0.3),
            nn.Linear(hidden * 2, 2),
        )

    def forward(self, x):
        h, _ = self.lstm(x)
        return self.head(h.mean(dim=1))


class TinyTransformer(nn.Module):
    def __init__(self, d_model=32, nhead=4, layers=2):
        super().__init__()
        self.in_proj = nn.Linear(6, d_model)
        self.pos = nn.Parameter(torch.randn(1, WIN_SAMPLES, d_model) * 0.02)
        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead, dim_feedforward=64,
            dropout=0.2, batch_first=True, activation="gelu",
        )
        self.enc = nn.TransformerEncoder(enc_layer, num_layers=layers)
        self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, 2))

    def forward(self, x):
        h = self.in_proj(x) + self.pos
        h = self.enc(h)
        return self.head(h.mean(dim=1))


def _train_torch(model, Xtr, ytr, Xva, yva, desc="train"):
    torch.manual_seed(SEED)
    model = model.to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    counts = np.bincount(ytr.numpy(), minlength=2).astype(np.float32)
    w = (counts.sum() / (2.0 * np.maximum(counts, 1))).astype(np.float32)
    loss_fn = nn.CrossEntropyLoss(weight=torch.tensor(w, device=DEVICE))

    tr_loader = DataLoader(TensorDataset(Xtr, ytr), batch_size=BATCH,
                           shuffle=True, drop_last=False)
    best_val, best_state, bad_epochs = float("inf"), None, 0
    for _ in range(EPOCHS):
        model.train(True)
        for xb, yb in tr_loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()
        model.train(False)
        with torch.no_grad():
            v = loss_fn(model(Xva.to(DEVICE)), yva.to(DEVICE)).item()
        if v < best_val - 1e-4:
            best_val = v
            best_state = {k: t.detach().clone() for k, t in model.state_dict().items()}
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= PATIENCE:
                break
    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def _predict_torch(model, X):
    model.train(False)
    with torch.no_grad():
        logits = model(X.to(DEVICE))
        proba = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
    return (proba >= 0.5).astype(int), proba


def _torch_run(build_model, X_tr_np, y_tr_np, X_te_np, y_te_np, desc="train"):
    n = len(X_tr_np)
    rng = np.random.RandomState(SEED)
    idx = rng.permutation(n)
    cut = int(n * 0.85)
    tr_idx, va_idx = idx[:cut], idx[cut:]

    Xtr = torch.from_numpy(X_tr_np[tr_idx]).float()
    ytr = torch.from_numpy(y_tr_np[tr_idx]).long()
    Xva = torch.from_numpy(X_tr_np[va_idx]).float()
    yva = torch.from_numpy(y_tr_np[va_idx]).long()
    Xte = torch.from_numpy(X_te_np).float()

    model = _train_torch(build_model(), Xtr, ytr, Xva, yva, desc=desc)
    y_pred, y_proba = _predict_torch(model, Xte)
    return {
        "acc": float((y_pred == y_te_np).mean()),
        "auc": float(roc_auc_score(y_te_np, y_proba))
        if len(np.unique(y_te_np)) >= 2 else float("nan"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--device", choices=["auto", "cpu", "mps", "cuda"], default="auto",
        help="Torch-Device fuer NN-Training. 'auto' bevorzugt mps > cuda > cpu.",
    )
    args = ap.parse_args()
    global DEVICE
    DEVICE = _resolve_device(args.device)

    from forecast._ui import boot_sequence, ForecastUI, reveal_finale, CONSOLE

    with CONSOLE.status("[bold cyan]loading sessions + building windows ...",
                        spinner="dots12"):
        raw, feat, y, sid_to_person = _load_data()
    persons = sorted(set(sid_to_person.values()))
    n_persons = len(persons)

    def _stack(sids):
        return (
            np.concatenate([raw[s] for s in sids]),
            np.concatenate([feat[s] for s in sids]),
            np.concatenate([y[s] for s in sids]),
        )

    sids_by_person = {p: [s for s, pp in sid_to_person.items() if pp == p]
                      for p in persons}

    architectures = {
        "DeepMLP":     (lambda: DeepMLP(in_dim=88), "feat"),
        "1D-CNN":      (CNN1D, "raw"),
        "BiLSTM":      (BiLSTM, "raw"),
        "Transformer": (TinyTransformer, "raw"),
    }

    from forecast._common import (
        load_windows, zscore_per_session, sklearn_models, train_test_sklearn,
    )
    sk_model_objs = sklearn_models()

    all_w = load_windows()
    feat_cols_sk = [c for c in all_w.columns if c not in
                    {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}]
    all_w = zscore_per_session(all_w, feat_cols_sk)

    n_train_range = range(1, n_persons)

    dl_jobs = []
    for n_train in n_train_range:
        for train_combo in combinations(persons, n_train):
            test_persons = [p for p in persons if p not in train_combo]
            for test_p in test_persons:
                for name, (builder, kind) in architectures.items():
                    dl_jobs.append(("DL", n_train, train_combo, test_p,
                                    name, builder, kind))

    sk_jobs = []
    for n_train in n_train_range:
        for train_combo in combinations(persons, n_train):
            test_persons = [p for p in persons if p not in train_combo]
            for test_p in test_persons:
                for name, model in sk_model_objs.items():
                    sk_jobs.append(("SK", n_train, train_combo, test_p,
                                    name, model))

    total = len(dl_jobs) + len(sk_jobs)
    boot_sequence(persons, DEVICE, total)

    model_order_ui = ["ExtraTrees", "RandomForest", "HistGradBoost", "LogReg",
                      "DeepMLP", "1D-CNN", "BiLSTM", "Transformer"]
    n_train_values = list(n_train_range)

    rows = []       # DL rows
    sk_rows = []    # SK rows
    with ForecastUI(persons, model_order_ui, n_train_values, total) as ui:
        for _, n_train, train_combo, test_p, name, builder, kind in dl_jobs:
            ui.start_job("DL", n_train, train_combo, test_p, name)
            train_sids = [s for p in train_combo for s in sids_by_person[p]]
            test_sids = sids_by_person[test_p]
            Xraw_tr, Xfeat_tr, ytr = _stack(train_sids)
            Xraw_te, Xfeat_te, yte = _stack(test_sids)
            X_tr = Xraw_tr if kind == "raw" else Xfeat_tr
            X_te = Xraw_te if kind == "raw" else Xfeat_te
            r = _torch_run(builder, X_tr, ytr, X_te, yte, desc=name)
            rows.append({"model": name, "n_train": n_train,
                         "test_person": test_p, **r})
            ui.finish_job(r["acc"], r.get("auc"))

        for _, n_train, train_combo, test_p, name, model in sk_jobs:
            ui.start_job("SK", n_train, train_combo, test_p, name)
            train = all_w[all_w["person_id"].isin(set(train_combo))]
            test = all_w[all_w["person_id"] == test_p]
            r = train_test_sklearn(model, train, test, feat_cols_sk)
            if r is not None:
                sk_rows.append({"model": name, "n_train": n_train,
                                "test_person": test_p, **r})
                ui.finish_job(r["acc"], r.get("auc"))
            else:
                ui.finish_job(float("nan"), None)

    df_dl = pd.DataFrame(rows)
    df_sk = pd.DataFrame(sk_rows)
    df_all = pd.concat([df_sk[["model", "n_train", "test_person", "acc", "auc"]],
                        df_dl], ignore_index=True)
    df_all["n_persons"] = n_persons
    df_all.to_csv(OUT_DIR / f"learning_curve_raw_all_n{n_persons}.csv", index=False)

    def _power(n, c, a, b):
        return c - a * np.power(n, -b)

    from forecast._stats import (
        fit_power_law, bootstrap_ci, loso_curve_validation,
    )

    forecasts = {}
    ci_bands: dict[str, dict] = {}
    validation: dict[str, dict] = {}

    n_grid_ci = np.logspace(np.log10(1), np.log10(110), 250)

    with CONSOLE.status("[bold cyan]bootstrap CIs + LOSO validation ...",
                        spinner="dots12"):
        for name in df_all["model"].unique():
            sub = df_all[df_all["model"] == name]
            xs = sub["n_train"].to_numpy(float)
            ys = sub["acc"].to_numpy(float)

            fit = fit_power_law(xs, ys)
            if fit is None:
                forecasts[name] = (0.9, 0.3, 0.3)
                continue
            forecasts[name] = fit

            band = bootstrap_ci(xs, ys, n_grid_ci, n_boot=1000)
            ci_bands[name] = dict(
                n_grid=band.n_grid, lo=band.lo, mid=band.mid, hi=band.hi,
                asymptotes=band.asymptote_samples,
                n_successful=band.n_successful,
            )

            loso = loso_curve_validation(sub[["test_person", "n_train", "acc"]])

            ci_lo = (float(np.percentile(band.asymptote_samples, 5))
                     if len(band.asymptote_samples) >= 10 else float("nan"))
            ci_hi = (float(np.percentile(band.asymptote_samples, 95))
                     if len(band.asymptote_samples) >= 10 else float("nan"))

            validation[name] = dict(
                ci_lo=ci_lo, ci_hi=ci_hi,
                loso_mae=loso.mae_mean,
            )

    reveal_finale(forecasts, FORECAST_N, validation=validation)

    # persist bootstrap bands for downstream consumers
    ci_rows = []
    for name, b in ci_bands.items():
        for i, n in enumerate(b["n_grid"]):
            ci_rows.append({
                "model": name, "n_train": float(n),
                "lo_5pct": float(b["lo"][i]) if not np.isnan(b["lo"][i]) else None,
                "median": float(b["mid"][i]) if not np.isnan(b["mid"][i]) else None,
                "hi_95pct": float(b["hi"][i]) if not np.isnan(b["hi"][i]) else None,
                "n_persons": n_persons,
            })
    if ci_rows:
        pd.DataFrame(ci_rows).to_csv(
            OUT_DIR / f"learning_curve_ci_n{n_persons}.csv", index=False)

    rows_fc = []
    for name, (c, a, b) in forecasts.items():
        for n in [2, *FORECAST_N]:
            rows_fc.append({"model": name, "n_train": n,
                            "acc_predicted": _power(n, c, a, b),
                            "asymptote_c": c, "a": a, "b": b,
                            "n_persons": n_persons})
    pd.DataFrame(rows_fc).to_csv(OUT_DIR / f"learning_curve_n{n_persons}.csv", index=False)

    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12.5, 7.0), dpi=110)

    colors = {
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
    dash = {
        "DeepMLP": (0, (1, 1)),
        "1D-CNN": (0, (4, 2)),
        "BiLSTM": (0, (3, 1, 1, 1, 1, 1)),
        "Transformer": (0, (6, 1, 1, 1)),
    }
    n_grid = np.logspace(np.log10(1), np.log10(110), 250)

    order = ["ExtraTrees", "RandomForest", "HistGradBoost", "XGBoost", "LogReg",
             "DeepMLP", "1D-CNN", "BiLSTM", "Transformer"]
    for name in order:
        if name not in forecasts:
            continue
        c, a, b = forecasts[name]
        sub = df_all[df_all["model"] == name]
        for n_train, g in sub.groupby("n_train"):
            mu, sigma = g["acc"].mean(), g["acc"].std()
            ax.errorbar(n_train, mu, yerr=sigma if not np.isnan(sigma) else 0,
                        fmt="o", color=colors[name], capsize=3.5, markersize=7,
                        markeredgecolor="white", markeredgewidth=0.5,
                        elinewidth=1.0, zorder=4)
        ys = _power(n_grid, c, a, b)
        max_emp = float(n_persons - 1)
        emp_mask = n_grid <= max_emp
        extra_mask = n_grid >= max_emp

        band = ci_bands.get(name)
        if band is not None and not np.all(np.isnan(band["lo"])):
            ax.fill_between(band["n_grid"], band["lo"], band["hi"],
                            color=colors[name], alpha=0.12, zorder=1,
                            linewidth=0)

        ax.plot(n_grid[emp_mask], ys[emp_mask],
                "-", color=colors[name], lw=2.2, label=name, zorder=3)
        ax.plot(n_grid[extra_mask], ys[extra_mask],
                linestyle=dash.get(name, "--"),
                color=colors[name], lw=1.8, alpha=0.85, zorder=2)

    max_emp = float(n_persons - 1)
    ax.axvspan(max_emp, 110, alpha=0.06, color="white", zorder=0)
    ax.text(max_emp * 1.25, 0.435,
            f"EXTRAPOLATION  ({n_persons - 1} empirische Stuetzpunkte)\n"
            f"schattierte Baender = 90% Bootstrap-CI ueber {len(df_all)} Fold-Messungen\n"
            "bei n_train > 5 wachsen die Baender stark - Werte qualitativ behandeln",
            color="#cccccc", fontsize=8.5, ha="left", va="bottom",
            style="italic")
    for nf in FORECAST_N:
        ax.axvline(nf, color="white", alpha=0.06, lw=0.8, zorder=0)

    ax.set_xscale("log")
    ax.set_xticks([1, 2, 3, 5, 10, 20, 30, 50, 70, 100])
    ax.set_xticklabels(["1", "2", "3", "5", "10", "20", "30", "50", "70", "100"])
    ax.set_xlim(0.85, 110)
    ax.set_ylim(0.40, 1.0)
    ax.set_xlabel("Probanden im Trainings-Pool  (n_train)", fontsize=11)
    ax.set_ylabel("Cross-subject LOSO Accuracy", fontsize=11)
    ax.set_title(
        f"Lernkurven-Prognose - alle Modelle (Basis: n={n_persons} Probanden)\n"
        "(durchgezogen = empirisch  /  gestrichelt = extrapoliert  -  "
        "DL hat eigene Strichmuster)",
        fontsize=12, pad=12,
    )
    ax.grid(True, alpha=0.12)
    ax.legend(loc="lower right", framealpha=0.85, fontsize=9, ncol=2)

    fig.tight_layout()
    out_png = OUT_DIR / f"learning_curve_n{n_persons}.png"
    fig.savefig(out_png, dpi=140, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print(f"\n-> {out_png}")

    import plotly.graph_objects as go

    pfig = go.Figure()
    for name in order:
        if name not in forecasts:
            continue
        c, a, b = forecasts[name]
        col = colors[name]
        ys_curve = _power(n_grid, c, a, b)
        emp_mask = n_grid <= max_emp
        extra_mask = n_grid >= max_emp

        # rgba for translucent CI fill
        r, g, bl = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)
        fill_rgba = f"rgba({r},{g},{bl},0.12)"

        band = ci_bands.get(name)
        if band is not None and not np.all(np.isnan(band["lo"])):
            pfig.add_trace(go.Scatter(
                x=band["n_grid"], y=band["hi"], mode="lines",
                line=dict(width=0), showlegend=False,
                legendgroup=name, hoverinfo="skip",
            ))
            pfig.add_trace(go.Scatter(
                x=band["n_grid"], y=band["lo"], mode="lines",
                line=dict(width=0), fill="tonexty", fillcolor=fill_rgba,
                showlegend=False, legendgroup=name,
                hovertemplate=(f"<b>{name}</b> 90% CI<br>n=%{{x:.1f}}<br>"
                               "acc=%{y:.3f}<extra></extra>"),
            ))

        pfig.add_trace(go.Scatter(
            x=n_grid[emp_mask], y=ys_curve[emp_mask],
            mode="lines", name=name, legendgroup=name,
            line=dict(color=col, width=2.5),
            hovertemplate=f"<b>{name}</b><br>n=%{{x:.1f}}<br>acc=%{{y:.3f}}<extra></extra>",
        ))
        pfig.add_trace(go.Scatter(
            x=n_grid[extra_mask], y=ys_curve[extra_mask],
            mode="lines", name=name, legendgroup=name, showlegend=False,
            line=dict(color=col, width=1.8, dash="dash"),
            hovertemplate=f"<b>{name}</b> (extrapoliert)<br>n=%{{x:.1f}}<br>acc=%{{y:.3f}}<extra></extra>",
        ))

        sub = df_all[df_all["model"] == name]
        agg = sub.groupby("n_train")["acc"].agg(["mean", "std"]).reset_index()
        pfig.add_trace(go.Scatter(
            x=agg["n_train"], y=agg["mean"],
            error_y=dict(type="data", array=agg["std"].fillna(0), thickness=1.2,
                         color=col, width=4),
            mode="markers", name=name, legendgroup=name, showlegend=False,
            marker=dict(color=col, size=10, line=dict(color="white", width=0.8)),
            hovertemplate=(f"<b>{name}</b><br>n_train=%{{x}}<br>"
                           "acc=%{y:.3f} (empirisch)<extra></extra>"),
        ))

    pfig.add_vrect(x0=max_emp, x1=110, fillcolor="white", opacity=0.04,
                   layer="below", line_width=0)
    pfig.add_annotation(
        x=max_emp * 1.4, y=0.46, xref="x", yref="y",
        text=(f"<b><i>EXTRAPOLATION</i></b><br>"
              f"<i>{n_persons - 1} empirische Stuetzpunkte<br>"
              "schattierte Baender = 90% Bootstrap-CI<br>"
              "n>5: Werte qualitativ behandeln</i>"),
        showarrow=False, font=dict(color="#dddddd", size=11),
        align="left",
        bgcolor="rgba(0,0,0,0.45)",
        bordercolor="rgba(255,255,255,0.15)", borderwidth=1, borderpad=6,
    )

    pfig.update_layout(
        title=dict(
            text=(f"Lernkurven-Prognose - alle Modelle (Basis: n={n_persons} Probanden)"
                  "<br><sub>Klick auf Modell in Legende = aus/ein  |  "
                  "Doppelklick = nur dieses Modell</sub>"),
            x=0.5, xanchor="center",
        ),
        xaxis=dict(
            type="log", title="Probanden im Trainings-Pool  (n_train)",
            tickvals=[1, 2, 3, 5, 10, 20, 30, 50, 70, 100],
            ticktext=["1", "2", "3", "5", "10", "20", "30", "50", "70", "100"],
            range=[np.log10(0.85), np.log10(110)],
            gridcolor="rgba(255,255,255,0.08)",
        ),
        yaxis=dict(
            title="Cross-subject LOSO Accuracy",
            range=[0.40, 1.0],
            gridcolor="rgba(255,255,255,0.08)",
        ),
        template="plotly_dark",
        hovermode="closest",
        legend=dict(orientation="v", x=1.02, y=1.0, bgcolor="rgba(0,0,0,0.4)"),
        margin=dict(l=70, r=180, t=80, b=60),
        width=1200, height=700,
    )

    out_html = OUT_DIR / f"learning_curve_n{n_persons}.html"
    pfig.write_html(str(out_html), include_plotlyjs="cdn",
                    full_html=True)
    print(f"-> {out_html}")


if __name__ == "__main__":
    main()

"""Deep-Learning-Erweiterung der Lernkurven-Prognose.

Trainiert drei Architekturen auf denselben Splits wie der sklearn-Vergleich:
- DeepMLP: 88 engineered features -> 128 -> 64 -> 32 -> 2 (mit Dropout/BN)
- 1D-CNN:  raw IMU (50 samples x 6 channels) -> 2x Conv1d -> GAP -> FC
- Transformer: raw IMU als 50-Token-Sequenz, 6-dim -> linear 32 -> 2x EncoderLayer

Fuer jede Architektur:
- n_train=1: alle 3 (train_person, test_person)-Kombinationen mit den
  anderen 2 als Test (-> 6 Messungen)
- n_train=2: alle 3 (train_pair, test_person)-Kombinationen (-> 3 Messungen)


->trainiert 8 verschiedene Modelle auf allen möglichen Aufteilungen deiner 3 Probanden, misst wie sehr ein Modell besser wird wenn es mehr Probanden im Training sieht, und
  extrapoliert dann mathematisch, wie die Performance bei 10, 50, oder 100 Probanden aussehen würde.

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
from tqdm.auto import tqdm

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
    print(f"Device: {DEVICE}")

    print("Loading + windowing sessions...")
    raw, feat, y, sid_to_person = _load_data()
    persons = sorted(set(sid_to_person.values()))
    print(f"Persons: {persons}")
    for p in persons:
        n = sum(len(y[s]) for s, pp in sid_to_person.items() if pp == p)
        print(f"  {p}: {n} windows")

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

    # Build DL + sklearn job lists upfront so we can show ONE master progress bar.
    from forecast.learning_curve_forecast import (
        _load_windows, _zscore_per_session, _models as sk_models, _train_test,
    )
    sk_model_objs = sk_models()

    all_w = _load_windows()
    feat_cols_sk = [c for c in all_w.columns if c not in
                    {"label", "t_center_ms", "session_id", "person_id",
                     "task_id", "task_category"}]
    all_w = _zscore_per_session(all_w, feat_cols_sk)

    dl_jobs = []
    for n_train in (1, 2):
        for train_combo in combinations(persons, n_train):
            test_persons = [p for p in persons if p not in train_combo]
            for test_p in test_persons:
                for name, (builder, kind) in architectures.items():
                    dl_jobs.append(("DL", n_train, train_combo, test_p,
                                    name, builder, kind))

    sk_jobs = []
    for n_train in (1, 2):
        for train_combo in combinations(persons, n_train):
            test_persons = [p for p in persons if p not in train_combo]
            for test_p in test_persons:
                for name, model in sk_model_objs.items():
                    sk_jobs.append(("SK", n_train, train_combo, test_p,
                                    name, model))

    total = len(dl_jobs) + len(sk_jobs)
    print(f"\nGesamt: {total} Fits ({len(dl_jobs)} Deep Learning + {len(sk_jobs)} sklearn)\n")
    bar = tqdm(total=total, desc="Lernkurve", unit="fit", colour="cyan")

    rows = []  # DL rows
    for _, n_train, train_combo, test_p, name, builder, kind in dl_jobs:
        bar.set_postfix_str(f"DL  n={n_train} {'+'.join(train_combo)}→{test_p} | {name}")
        train_sids = [s for p in train_combo for s in sids_by_person[p]]
        test_sids = sids_by_person[test_p]
        Xraw_tr, Xfeat_tr, ytr = _stack(train_sids)
        Xraw_te, Xfeat_te, yte = _stack(test_sids)
        X_tr = Xraw_tr if kind == "raw" else Xfeat_tr
        X_te = Xraw_te if kind == "raw" else Xfeat_te
        r = _torch_run(builder, X_tr, ytr, X_te, yte, desc=name)
        rows.append({"model": name, "n_train": n_train,
                     "test_person": test_p, **r})
        bar.update(1)
    df_dl = pd.DataFrame(rows)

    sk_rows = []
    for _, n_train, train_combo, test_p, name, model in sk_jobs:
        bar.set_postfix_str(f"SK  n={n_train} {'+'.join(train_combo)}→{test_p} | {name}")
        train = all_w[all_w["person_id"].isin(set(train_combo))]
        test = all_w[all_w["person_id"] == test_p]
        r = _train_test(model, train, test, feat_cols_sk)
        if r is not None:
            sk_rows.append({"model": name, "n_train": n_train,
                            "test_person": test_p, **r})
        bar.update(1)
    bar.close()
    df_sk = pd.DataFrame(sk_rows)
    df_all = pd.concat([df_sk[["model", "n_train", "test_person", "acc", "auc"]],
                        df_dl], ignore_index=True)
    df_all.to_csv(OUT_DIR / "learning_curve_raw_all.csv", index=False)

    print("\nEmpirische Stuetzpunkte (alle Modelle):")
    print(df_all.groupby(["model", "n_train"])["acc"]
          .agg(["mean", "std", "count"]).round(3))

    def _power(n, c, a, b):
        return c - a * np.power(n, -b)

    forecasts = {}
    for name in df_all["model"].unique():
        sub = df_all[df_all["model"] == name]
        try:
            popt, _ = curve_fit(_power, sub["n_train"].values, sub["acc"].values,
                                p0=[0.95, 0.3, 0.4],
                                bounds=([0.5, 0.0, 0.05], [1.0, 5.0, 3.0]),
                                maxfev=5000)
            forecasts[name] = tuple(popt)
        except Exception:
            forecasts[name] = (0.9, 0.3, 0.3)

    print("\nProgose-Tabelle:")
    head = ["Modell"] + [f"n={n}" for n in [2, *FORECAST_N]]
    print(" | ".join(f"{h:>14}" for h in head))
    rows_fc = []
    for name, (c, a, b) in forecasts.items():
        vals = [_power(n, c, a, b) for n in [2, *FORECAST_N]]
        print(" | ".join([f"{name:>14}"] + [f"{v:>14.3f}" for v in vals]))
        for n in [2, *FORECAST_N]:
            rows_fc.append({"model": name, "n_train": n,
                            "acc_predicted": _power(n, c, a, b),
                            "asymptote_c": c, "a": a, "b": b})
    pd.DataFrame(rows_fc).to_csv(OUT_DIR / "learning_curve_forecast.csv", index=False)

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
        emp_mask = n_grid <= 2.0
        extra_mask = n_grid >= 2.0
        ax.plot(n_grid[emp_mask], ys[emp_mask],
                "-", color=colors[name], lw=2.2, label=name, zorder=3)
        ax.plot(n_grid[extra_mask], ys[extra_mask],
                linestyle=dash.get(name, "--"),
                color=colors[name], lw=1.8, alpha=0.85, zorder=2)

    ax.axvspan(2.0, 110, alpha=0.06, color="white", zorder=0)
    ax.text(2.5, 0.435,
            "Extrapolation\n(2 empirische Stuetzpunkte -\nUnsicherheit waechst stark mit n)",
            color="#bbbbbb", fontsize=8.5, ha="left", va="bottom", style="italic")
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
        "Lernkurven-Prognose inkl. Deep Learning\n"
        "(durchgezogen = empirisch  /  gestrichelt = extrapoliert  -  "
        "DL hat eigene Strichmuster)",
        fontsize=12, pad=12,
    )
    ax.grid(True, alpha=0.12)
    ax.legend(loc="lower right", framealpha=0.85, fontsize=9, ncol=2)

    fig.tight_layout()
    out_png = OUT_DIR / "learning_curve_forecast_with_dl.png"
    fig.savefig(out_png, dpi=140, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    print(f"\n-> {out_png}")


if __name__ == "__main__":
    main()

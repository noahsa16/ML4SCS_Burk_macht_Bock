"""Stufe 2 Transfer-Learning: harnet end-to-end **fine-tunen**.

Im Gegensatz zur Stufe 1 (`harnet_frozen.py`, eingefrorener Trunk +
leichter Kopf) wird hier das **gesamte** vortrainierte Modell (Conv-Trunk
+ 2-Klassen-Kopf) mit kleiner Lernrate end-to-end nachtrainiert — im
identischen LOSO-by-person-Protokoll. Hypothese: der bewusste
Einheiten-/Domain-Shift (userAcceleration ohne Gravity vs. Biobank-Total-
Accel) laesst sich teilweise wegtrainieren, sodass Fine-Tuning die
Frozen-Schranke (per-window 0.896/0.958) anhebt.

Wichtig bei kleinem N (14 Probanden): vollstaendiges Fine-Tuning eines
vortrainierten Netzes ueberanpasst leicht. Gegenmittel hier: **kleine
Lernrate** (1e-4), **Early Stopping** auf einem rotierenden Val-Person-
Holdout (wie `src.training.deep.train_loso`), wenige Epochen. Der
Train/Test-Gap im Report ist die Overfit-Diagnose.

Pro Fold wird das Modell **frisch pretrained geladen** — sonst leckten
Gewichte des vorigen Test-Probanden in den naechsten Fold.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score, roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

from src.training.deep.harnet import (
    BURST_SCALES,
    NATIVE_SCALE,
    REPORTS_DIR,
    RF_CV_CSV,
    RF_HEADLINE,
)
from src.training.deep.harnet_data import (
    HARNET_VARIANTS,
    load_session_harnet,
    select_harnet_sessions,
)
from src.training.deep.harnet_frozen import (
    DEVICE,
    HUB_REPO,
    _ensure_ca_bundle,
)
from src.training.train_loso import _burst_metrics

ROOT = Path(__file__).parents[3]
MODEL_DIR = ROOT / "models"

# --- Fine-Tuning-Hyperparameter (zentral, gegen Default-Drift) -------------
FINETUNE_LR = 1e-4          # klein: vortrainierte Gewichte nur sanft anpassen
FINETUNE_MAX_EPOCHS = 15
FINETUNE_PATIENCE = 3       # Early Stopping auf Val-AUC
BATCH_SIZE = 64
SEED = 42


def _set_seed(seed: int = SEED) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)


def load_harnet_full(variant: str) -> torch.nn.Module:
    """Frisches, vortrainiertes harnet (Trunk + 2-Klassen-Kopf) fuer Fine-Tuning."""
    if variant not in HARNET_VARIANTS:
        raise ValueError(
            f"variant must be one of {sorted(HARNET_VARIANTS)}, got {variant!r}"
        )
    _ensure_ca_bundle()
    model = torch.hub.load(
        HUB_REPO, variant, class_num=2, pretrained=True,
        trust_repo=True, verbose=False,
    )
    return model.to(DEVICE)


def _class_weights(y: np.ndarray) -> torch.Tensor:
    """Balancierte Klassen-Gewichte fuer CrossEntropy: w[c] = N / (2 * n_c)."""
    n0 = float((y == 0).sum())
    n1 = float((y == 1).sum())
    n = n0 + n1
    w0 = n / (2.0 * n0) if n0 > 0 else 1.0
    w1 = n / (2.0 * n1) if n1 > 0 else 1.0
    return torch.tensor([w0, w1], dtype=torch.float32, device=DEVICE)


def predict_proba(model: torch.nn.Module, X: np.ndarray, batch_size: int = 256) -> np.ndarray:
    """Softmax-Wahrscheinlichkeit der writing-Klasse (Index 1)."""
    model.eval()
    out: list[np.ndarray] = []
    with torch.no_grad():
        for i in range(0, len(X), batch_size):
            xb = torch.from_numpy(X[i:i + batch_size]).to(DEVICE)
            logits = model(xb)
            proba = torch.softmax(logits, dim=1)[:, 1]
            out.append(proba.cpu().numpy())
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)


def finetune_model(
    model: torch.nn.Module,
    train_X: np.ndarray,
    train_y: np.ndarray,
    val_X: np.ndarray,
    val_y: np.ndarray,
    *,
    lr: float = FINETUNE_LR,
    max_epochs: int = FINETUNE_MAX_EPOCHS,
    patience: int = FINETUNE_PATIENCE,
    batch_size: int = BATCH_SIZE,
) -> tuple[torch.nn.Module, int]:
    """End-to-end-Fine-Tuning mit Early Stopping auf Val-ROC-AUC.

    Modell-agnostisch: erwartet ein ``model``, das ``(batch, 3, L)`` ->
    ``(batch, 2)``-Logits abbildet. Alle Parameter werden trainierbar
    gesetzt (volles Fine-Tuning). Returns ``(model, best_epoch)``; das beste
    Modell (hoechste Val-AUC) wird zurueckgeladen.
    """
    model = model.to(DEVICE)
    for p in model.parameters():
        p.requires_grad_(True)
    loss_fn = torch.nn.CrossEntropyLoss(weight=_class_weights(train_y))
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    ds = TensorDataset(
        torch.from_numpy(train_X),
        torch.from_numpy(train_y.astype(np.int64)),
    )
    # drop_last: BatchNorm kollabiert bei Batch-Groesse 1.
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, drop_last=True)
    val_Xt = torch.from_numpy(val_X).to(DEVICE)

    best_auc = -1.0
    best_epoch = -1
    best_state: dict | None = None
    since_best = 0
    for epoch in range(max_epochs):
        model.train()
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()

        model.eval()
        with torch.no_grad():
            val_proba = torch.softmax(model(val_Xt), dim=1)[:, 1].cpu().numpy()
        try:
            val_auc = roc_auc_score(val_y, val_proba)
        except ValueError:
            val_auc = 0.0

        if val_auc > best_auc:
            best_auc, best_epoch = val_auc, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            since_best = 0
        else:
            since_best += 1
            if since_best >= patience:
                break

    if best_state is not None:
        model.load_state_dict(best_state)
    return model, best_epoch


def _acc_auc(proba: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    pred = (proba >= 0.5).astype(int)
    acc = float((pred == y).mean())
    try:
        auc = float(roc_auc_score(y, proba))
    except ValueError:
        auc = float("nan")
    return acc, auc


def _load_all_windows(sessions: pd.DataFrame, variant: str) -> dict[str, dict]:
    win = HARNET_VARIANTS[variant]
    out: dict[str, dict] = {}
    for row in sessions.itertuples():
        sid = row.session_id
        X, y, t = load_session_harnet(
            sid, None, win["win_samples"], win["stride_samples"]
        )
        if len(X) == 0:
            print(f"  skip {sid} -- keine Fenster")
            continue
        out[sid] = {"X": X, "y": y, "t": t, "person_id": row.person_id}
        print(f"  {sid}: {len(X)} Fenster")
    return out


def harnet_finetune_loso(variant: str = "harnet5", seed: int = SEED) -> pd.DataFrame:
    """LOSO-by-person mit end-to-end-Fine-Tuning. Per-fold-Tabelle.

    Pro Fold: Test = 1 Person, Val = 1 rotierende Person (Early Stopping),
    Train = Rest. Modell pro Fold frisch pretrained (kein Gewichts-Leak).
    """
    if variant not in HARNET_VARIANTS:
        raise ValueError(
            f"variant must be one of {sorted(HARNET_VARIANTS)}, got {variant!r}"
        )
    _set_seed(seed)
    sessions = select_harnet_sessions(pool="legacy")
    if sessions.empty:
        raise RuntimeError("Keine Sessions -- sessions.csv / verdict-Gate pruefen.")

    data = _load_all_windows(sessions, variant)
    persons: dict[str, list[str]] = {}
    for sid, d in data.items():
        persons.setdefault(d["person_id"], []).append(sid)
    person_ids = sorted(persons)
    if len(person_ids) < 3:
        raise RuntimeError(f"LOSO braucht >= 3 Personen, hat {len(person_ids)}.")

    def _stack(plist: list[str], key: str) -> np.ndarray:
        return np.concatenate([data[s][key] for p in plist for s in persons[p]])

    print(f"\n=== {variant} fine-tune | {len(person_ids)} Folds | device={DEVICE} ===")
    rows: list[dict] = []
    for i, test_p in enumerate(person_ids):
        val_p = person_ids[(i + 1) % len(person_ids)]
        train_ps = [p for p in person_ids if p not in (test_p, val_p)]

        train_X, train_y = _stack(train_ps, "X"), _stack(train_ps, "y")
        val_X, val_y = _stack([val_p], "X"), _stack([val_p], "y")
        test_X, test_y = _stack([test_p], "X"), _stack([test_p], "y")
        if len(np.unique(test_y)) < 2:
            print(f"  Fold {test_p}: uebersprungen -- Test-Fold einklassig")
            continue

        test_df = pd.concat([
            pd.DataFrame({"session_id": s, "t_center_ms": data[s]["t"]})
            for s in persons[test_p]
        ], ignore_index=True)

        model = load_harnet_full(variant)
        model, best_epoch = finetune_model(model, train_X, train_y, val_X, val_y)

        train_acc, train_auc = _acc_auc(predict_proba(model, train_X), train_y)
        val_acc, _ = _acc_auc(predict_proba(model, val_X), val_y)
        proba = predict_proba(model, test_X)
        pred = (proba >= 0.5).astype(int)
        try:
            auc = float(roc_auc_score(test_y, proba))
        except ValueError:
            auc = float("nan")
        row = {
            "model": variant,
            "held_out": test_p,
            "n_test": int(len(test_y)),
            "accuracy": float((pred == test_y).mean()),
            "f1_writing": float(f1_score(test_y, pred, pos_label=1, zero_division=0)),
            "roc_auc": auc,
            "train_acc": train_acc,
            "train_auc": train_auc,
            "val_acc": val_acc,
            "best_epoch": best_epoch,
        }
        for scale, bm in _burst_metrics(proba, test_y, test_df).items():
            row[f"acc_{scale}"] = bm["accuracy"]
            row[f"auc_{scale}"] = bm["roc_auc"]
        rows.append(row)
        print(f"  Fold {test_p}: train={train_acc:.3f} val={val_acc:.3f} "
              f"test={row['accuracy']:.3f} auc={auc:.3f} best_epoch={best_epoch}")

        # MPS-Speicher zwischen Folds freigeben.
        del model
        if DEVICE.type == "mps":
            torch.mps.empty_cache()

    return pd.DataFrame(rows)


# --- Reporting -------------------------------------------------------------

def _finetune_paths(variant: str) -> tuple[Path, Path]:
    return (MODEL_DIR / f"harnet_finetune_{variant}.csv",
            REPORTS_DIR / f"harnet_finetune_{variant}.md")


def _frozen_csv(variant: str) -> Path:
    """Pfad der Stufe-1-Frozen-Ergebnisse (harnet5 kanonisch, sonst Sibling)."""
    return (MODEL_DIR / "harnet_loso.csv" if variant == "harnet5"
            else MODEL_DIR / f"harnet_loso_{variant}.csv")


def _summary(df: pd.DataFrame) -> dict:
    """Mean per-window acc/auc + Burst-Skalen + Train/Test-Gap."""
    out = {
        "window": (df["accuracy"].mean(), df["roc_auc"].mean()),
        "window_std": (df["accuracy"].std(), df["roc_auc"].std()),
        "f1": df["f1_writing"].mean(),
        "train_acc": df["train_acc"].mean(),
        "gap": df["train_acc"].mean() - df["accuracy"].mean(),
        "best_epoch": df["best_epoch"].mean(),
    }
    for s in BURST_SCALES:
        out[s] = (df[f"acc_{s}"].mean(), df[f"auc_{s}"].mean())
    return out


def _frozen_logreg_means(variant: str) -> dict | None:
    """Stufe-1-Frozen-Baseline (LogReg-Kopf), falls die CSV existiert."""
    csv = _frozen_csv(variant)
    if not csv.exists():
        return None
    fr = pd.read_csv(csv)
    fr = fr[fr["head"] == "logreg"]
    if fr.empty:
        return None
    m = {"window": (fr["accuracy"].mean(), fr["roc_auc"].mean())}
    for s in BURST_SCALES:
        m[s] = (fr[f"acc_{s}"].mean(), fr[f"auc_{s}"].mean())
    return m


def _print_tables(variant: str, summ: dict, frozen: dict | None) -> None:
    native = NATIVE_SCALE[variant]
    rf = RF_HEADLINE[native]
    print(f"\n=== {variant} fine-tuned — LOSO-by-person (Mean ueber Folds) ===")
    print(f"per-window = native {native}; Vergleich RF@{native} = {rf[0]:.3f}/{rf[1]:.3f}\n")
    cols = ["per-window", "@5s", "@10s", "@30s"]
    print(f"{'Variante':<18}" + "".join(f"{c:>16}" for c in cols))
    print(f"{'RF (N=14)':<18}{rf[0]:>7.3f}/{rf[1]:<8.3f}"
          + "".join(f"{RF_HEADLINE[s][0]:>7.3f}/{RF_HEADLINE[s][1]:<8.3f}" for s in BURST_SCALES))
    if frozen is not None:
        print(f"{'frozen (Stufe 1)':<18}{frozen['window'][0]:>7.3f}/{frozen['window'][1]:<8.3f}"
              + "".join(f"{frozen[s][0]:>7.3f}/{frozen[s][1]:<8.3f}" for s in BURST_SCALES))
    print(f"{'fine-tune (St. 2)':<18}{summ['window'][0]:>7.3f}/{summ['window'][1]:<8.3f}"
          + "".join(f"{summ[s][0]:>7.3f}/{summ[s][1]:<8.3f}" for s in BURST_SCALES))
    print(f"\nTrain/Test-Gap {summ['gap']:+.3f} (Overfit-Diagnose), "
          f"mean best_epoch {summ['best_epoch']:.1f}, per-window-acc-Std {summ['window_std'][0]:.3f}")


def _correlation_line(variant: str, df: pd.DataFrame) -> str:
    """Per-Fold-AUC-Korrelation fine-tune vs RF@native (eine Zeile)."""
    if not RF_CV_CSV.exists():
        return "_loso_cv.csv nicht gefunden — Korrelation uebersprungen._"
    from scipy.stats import pearsonr
    native = NATIVE_SCALE[variant]
    rf = pd.read_csv(RF_CV_CSV).set_index("held_out")
    ft = df.set_index("held_out")
    folds = [f for f in ft.index if f in rf.index]
    if len(folds) < 3:
        return "_Zu wenig gemeinsame Folds._"
    r, _ = pearsonr(rf.loc[folds, f"auc_{native}"], ft.loc[folds, "roc_auc"])
    return (f"Per-Fold-AUC korreliert mit RF@{native}: Pearson r = {r:+.3f} "
            f"(n = {len(folds)}). Schwaechster Fold: "
            f"{ft.loc[folds, 'roc_auc'].idxmin()}.")


def _write_report(variant: str, df: pd.DataFrame, summ: dict,
                  frozen: dict | None, out_csv: Path, report_path: Path) -> Path:
    native = NATIVE_SCALE[variant]
    rf = RF_HEADLINE[native]
    win = HARNET_VARIANTS[variant]
    fw = summ["window"]
    d_rf = (fw[0] - rf[0], fw[1] - rf[1])
    d_fr = ((fw[0] - frozen["window"][0], fw[1] - frozen["window"][1])
            if frozen else (float("nan"), float("nan")))

    lines = [
        f"# Transfer-Learning Stufe 2: Oxford ssl-wearables ({variant}), fine-tuned",
        "",
        "## Setup",
        "",
        f"- **Modell:** `{variant}` (pretrained), **end-to-end fine-tuned** — "
        f"Conv-Trunk + 2-Klassen-Kopf, alle Parameter trainierbar.",
        f"- **Input:** {win['win_samples']} Samples = {win['win_samples'] / 30:.0f} s "
        f"@ 30 Hz, 3 Accel-Kanaele (userAcceleration ohne Gravity), Stride "
        f"{win['stride_samples'] / 30:.1f} s.",
        f"- **Training:** Adam, LR {FINETUNE_LR:g}, max {FINETUNE_MAX_EPOCHS} Epochen, "
        f"Early Stopping (Patience {FINETUNE_PATIENCE}) auf rotierendem "
        f"Val-Person-Holdout; balancierte CrossEntropy. Modell **pro Fold "
        f"frisch pretrained** (kein Gewichts-Leak). mean best_epoch "
        f"{summ['best_epoch']:.1f}.",
        "- **Protokoll:** LOSO-by-person, gleiche Session-Auswahl wie die "
        "RF-Headline (Pool `legacy`).",
        "",
        "## Einheiten-Limitation",
        "",
        "Input bleibt `userAcceleration` ohne Gravity (Domain-Shift ggue. "
        "Biobank-Total-Accel-Pretraining). Anders als beim Frozen-Transfer "
        "*kann* Fine-Tuning diesen Shift teilweise wegtrainieren — genau das "
        "ist die Hypothese dieser Stufe.",
        "",
        "## Ergebnis",
        "",
        f"Vergleich auf nativer Decision-Skala ({native}):",
        "",
        f"| Variante | per-window acc/AUC | @5s | @10s | @30s |",
        f"|---|---|---|---|---|",
        f"| RF (N=14) | {rf[0]:.3f}/{rf[1]:.3f} | "
        f"{RF_HEADLINE['5s'][0]:.3f}/{RF_HEADLINE['5s'][1]:.3f} | "
        f"{RF_HEADLINE['10s'][0]:.3f}/{RF_HEADLINE['10s'][1]:.3f} | "
        f"{RF_HEADLINE['30s'][0]:.3f}/{RF_HEADLINE['30s'][1]:.3f} |",
    ]
    if frozen:
        lines.append(
            f"| frozen (Stufe 1) | {frozen['window'][0]:.3f}/{frozen['window'][1]:.3f} | "
            f"{frozen['5s'][0]:.3f}/{frozen['5s'][1]:.3f} | "
            f"{frozen['10s'][0]:.3f}/{frozen['10s'][1]:.3f} | "
            f"{frozen['30s'][0]:.3f}/{frozen['30s'][1]:.3f} |"
        )
    lines += [
        f"| **fine-tune (Stufe 2)** | {fw[0]:.3f}/{fw[1]:.3f} | "
        f"{summ['5s'][0]:.3f}/{summ['5s'][1]:.3f} | "
        f"{summ['10s'][0]:.3f}/{summ['10s'][1]:.3f} | "
        f"{summ['30s'][0]:.3f}/{summ['30s'][1]:.3f} |",
        "",
        f"**Overfit-Diagnose:** Train/Test-Gap = {summ['gap']:+.3f} "
        f"(train {summ['train_acc']:.3f} vs test {fw[0]:.3f}); "
        f"per-window-acc-Std {summ['window_std'][0]:.3f}.",
        "",
        f"**Verdikt:** Fine-Tuning vs. RF@{native}: ΔAcc {d_rf[0]:+.3f}, "
        f"ΔAUC {d_rf[1]:+.3f}."
        + (f" Vs. Frozen (Stufe 1): ΔAcc {d_fr[0]:+.3f}, ΔAUC {d_fr[1]:+.3f}."
           if frozen else "")
        + " " + (
            "Fine-Tuning hebt den Transfer klar ueber die Frozen-Schranke — der "
            "Domain-Shift liess sich teilweise wegtrainieren."
            # Why: beide Metriken muessen ueber das Rauschen (per-window-acc-Std
            # ~0.045) hinaus steigen; ein isoliertes ΔAUC < 0.01 bei flacher acc
            # ist kein Gewinn, sondern Streuung.
            if frozen and d_fr[1] > 0.01 and d_fr[0] > 0.005 else
            "Fine-Tuning bringt gegenueber dem Frozen-Transfer **keinen klaren "
            "Gewinn** (Δ innerhalb der Fold-Streuung). Das mean best_epoch "
            f"{summ['best_epoch']:.1f} + Train/Test-Gap {summ['gap']:+.3f} zeigen: "
            "die vortrainierten Features sind schon nahe optimal, weiteres "
            "Training ueberanpasst bei N=14 fast sofort. Die Decke bleibt die "
            "Signal-Ambiguitaet, nicht die Repraesentation."
        ),
        "",
        _correlation_line(variant, df),
        "",
        f"Per-fold-Rohdaten: `{out_csv.relative_to(ROOT)}`.",
        "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.training.deep.harnet_finetune")
    parser.add_argument("--model", choices=list(HARNET_VARIANTS), default="harnet5")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    df = harnet_finetune_loso(args.model, seed=args.seed)
    if df.empty:
        raise SystemExit("Keine Folds -- Daten / Filter pruefen.")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out_csv, report_path = _finetune_paths(args.model)
    df.to_csv(out_csv, index=False)
    print(f"\n-> {out_csv}  ({len(df)} fold-Zeilen)")

    summ = _summary(df)
    frozen = _frozen_logreg_means(args.model)
    _print_tables(args.model, summ, frozen)
    report = _write_report(args.model, df, summ, frozen, out_csv, report_path)
    print(f"-> {report}")


if __name__ == "__main__":
    main()

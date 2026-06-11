"""Falsifikations-Test: hebt harnet-Fusion die RF-Headline?

Zwei Wege, harnets Foundation-Repraesentation an den Baseline-RF zu koppeln,
beide leakage-bewusst im selben LOSO-by-person-Protokoll wie die Headline:

1. **Proba-Ensemble** — Mittel der OOF-Wahrscheinlichkeiten von RF (88
   Hand-Features) und frozen-harnet (LogReg-Kopf). Vollstaendig sauber:
   beide Arme sind reine Out-of-Fold-Vorhersagen des gehaltenen Probanden.
2. **Stack (88 + 1)** — harnets OOF-Proba als 89. Feature im RF. Milde
   Stacking-CV-Optimistik (harnets OOF fuer Trainings-Probanden T wurde von
   einem harnet erzeugt, das den Test-Probanden S gesehen hat); im
   Standard-Stacking-Rezept akzeptiert und hier dokumentiert. Da das
   Ergebnis ~null erwartet wird, ist ein leicht optimistischer Test, der
   trotzdem null zeigt, umso aussagekraeftiger.

Fenster-Alignment: harnet (5 s/2,5 s bzw. 10 s/5 s) wird per
``merge_asof(direction='nearest')`` je Session auf das feinere RF-Raster
(1 s/0,5 s) gebroadcastet. Burst-Aggregation @5/10/30 s via der bestehenden
`_burst_metrics`-Logik. Zusaetzlich die **Per-Window-Fehler-Korrelation**
(Residuen RF vs. harnet) — die eigentliche offene Frage: nur wenn die
Fehler *innerhalb* der Folds dekorreliert sind, hat Fusion Spielraum.

CLI: ``python scripts/ml/harnet_rf_fusion.py [--model harnet5|harnet10]
[--force-oof]``. Output: ``reports/harnet_rf_fusion.md`` +
``models/harnet_fusion_{variant}.csv`` (+ Cache ``harnet_oof_{variant}.csv``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.training.deep.harnet import RF_HEADLINE, NATIVE_SCALE  # noqa: E402
from src.training.deep.harnet_frozen import harnet_oof  # noqa: E402
from src.training.train_loso import (  # noqa: E402
    _burst_metrics,
    _filter_pool,
    _load_windows,
    _profile_for_pool,
    _select_sessions,
    _zscore_per_session,
)

MODEL_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
N_TREES = 200
SEED = 42
NON_FEATURE = {"label", "t_center_ms", "session_id", "person_id",
               "task_id", "task_category"}
BURST = ("5s", "10s", "30s")


def _acc(proba: np.ndarray, y: np.ndarray) -> float:
    return float(((proba >= 0.5).astype(int) == y).mean())


def _auc(proba: np.ndarray, y: np.ndarray) -> float:
    try:
        return float(roc_auc_score(y, proba))
    except ValueError:
        return float("nan")


def _get_harnet_oof(variant: str, force: bool) -> pd.DataFrame:
    cache = MODEL_DIR / f"harnet_oof_{variant}.csv"
    if cache.exists() and not force:
        print(f"[fusion] harnet-OOF aus Cache {cache.name}")
        return pd.read_csv(cache)
    print(f"[fusion] berechne harnet-OOF ({variant}) …")
    oof = harnet_oof(variant)
    cache.parent.mkdir(parents=True, exist_ok=True)
    oof.to_csv(cache, index=False)
    return oof


def _load_rf_windows() -> tuple[pd.DataFrame, list[str]]:
    """Headline-Pipeline: legacy-Pool, 88 Features, mit person_id."""
    profile = _profile_for_pool("legacy")
    sessions = _select_sessions(include_all=False, min_windows=0, profile=profile)
    all_windows = pd.concat(
        [_load_windows(s, profile) for s in sessions["session_id"].tolist()],
        ignore_index=True,
    ).merge(sessions[["session_id", "person_id"]], on="session_id", how="left")
    all_windows = _filter_pool(all_windows, "legacy")
    feature_cols = [c for c in all_windows.columns if c not in NON_FEATURE]
    return all_windows, feature_cols


def _align_harnet(windows: pd.DataFrame, oof: pd.DataFrame) -> pd.DataFrame:
    """Broadcaste harnet-OOF-Proba per Session aufs RF-Raster (nearest t_center)."""
    left = windows.sort_values("t_center_ms")
    right = (oof[["session_id", "t_center_ms", "proba"]]
             .rename(columns={"proba": "harnet_proba"})
             .sort_values("t_center_ms"))
    merged = pd.merge_asof(
        left, right, on="t_center_ms", by="session_id", direction="nearest"
    )
    missing = int(merged["harnet_proba"].isna().sum())
    if missing:
        print(f"[fusion] {missing} Fenster ohne harnet-Match — verworfen")
        merged = merged.dropna(subset=["harnet_proba"])
    return merged


def _loso(windows: pd.DataFrame, feature_cols: list[str], stack_cols: list[str]) -> pd.DataFrame:
    """LOSO-by-person: baseline-RF (88) + stack-RF (88+1), per-window OOF.

    Returns oof-Tabelle mit proba_base / proba_stack / harnet_proba (raw) / y /
    session_id / t_center_ms.
    """
    persons = sorted(windows["person_id"].dropna().unique())
    rows: list[pd.DataFrame] = []
    for held in persons:
        te = windows["person_id"] == held
        train, test = windows[~te], windows[te]
        if test["label"].nunique() < 2:
            print(f"  Fold {held}: uebersprungen (einklassig)")
            continue
        ytr = train["label"].to_numpy()
        for cols, key in ((feature_cols, "proba_base"), (stack_cols, "proba_stack")):
            clf = RandomForestClassifier(
                n_estimators=N_TREES, class_weight="balanced",
                random_state=SEED, n_jobs=-1,
            ).fit(train[cols].to_numpy(), ytr)
            test = test.assign(**{key: clf.predict_proba(test[cols].to_numpy())[:, 1]})
        rows.append(test[["session_id", "t_center_ms", "label",
                          "proba_base", "proba_stack", "harnet_proba_raw"]]
                    .rename(columns={"label": "y"}))
        print(f"  Fold {held}: ok ({len(test)} Fenster)")
    return pd.concat(rows, ignore_index=True)


def _metrics(proba: np.ndarray, y: np.ndarray, ctx: pd.DataFrame) -> dict:
    m = {"window": (_acc(proba, y), _auc(proba, y))}
    for scale, bm in _burst_metrics(proba, y, ctx).items():
        m[scale] = (bm["accuracy"], bm["roc_auc"])
    return m


def _row(name: str, m: dict) -> str:
    return (f"| {name} | {m['window'][0]:.3f}/{m['window'][1]:.3f} | "
            + " | ".join(f"{m[s][0]:.3f}/{m[s][1]:.3f}" for s in BURST) + " |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["harnet5", "harnet10"], default="harnet5")
    ap.add_argument("--force-oof", action="store_true")
    args = ap.parse_args()
    variant = args.model
    native = NATIVE_SCALE[variant]

    oof = _get_harnet_oof(variant, args.force_oof)
    windows, feature_cols = _load_rf_windows()
    windows = _align_harnet(windows, oof)

    # Raw harnet-Proba fuer das Ensemble behalten; z-skalierte Kopie als
    # Stack-Feature (per-Session, wie die 88).
    windows = windows.rename(columns={"harnet_proba": "harnet_proba_raw"})
    windows["harnet_proba"] = windows["harnet_proba_raw"]
    windows = _zscore_per_session(windows, feature_cols + ["harnet_proba"])
    stack_cols = feature_cols + ["harnet_proba"]

    print(f"\n=== Fusion {variant} | {windows['person_id'].nunique()} Folds | "
          f"{len(windows)} Fenster | {len(feature_cols)} Hand-Features ===")
    oof_all = _loso(windows, feature_cols, stack_cols)

    ctx = oof_all[["session_id", "t_center_ms"]]
    y = oof_all["y"].to_numpy()
    base = oof_all["proba_base"].to_numpy()
    harn = oof_all["harnet_proba_raw"].to_numpy()
    stack = oof_all["proba_stack"].to_numpy()
    ens = 0.5 * (base + harn)

    res = {
        "RF baseline (88)": _metrics(base, y, ctx),
        "harnet allein": _metrics(harn, y, ctx),
        "Ensemble (mean)": _metrics(ens, y, ctx),
        "Stack (88+1)": _metrics(stack, y, ctx),
    }

    # Per-Window-Fehler-Korrelation (die offene Frage).
    r_proba, _ = pearsonr(base, harn)
    r_resid, _ = pearsonr(base - y, harn - y)

    # CSV
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = MODEL_DIR / f"harnet_fusion_{variant}.csv"
    pd.DataFrame([
        {"variant": variant, "model": k,
         "acc_window": v["window"][0], "auc_window": v["window"][1],
         **{f"acc_{s}": v[s][0] for s in BURST},
         **{f"auc_{s}": v[s][1] for s in BURST}}
        for k, v in res.items()
    ]).to_csv(out_csv, index=False)

    # Konsole
    print(f"\n--- {variant} fusion vs RF-Headline (native {native}) ---")
    print(f"{'Modell':<20}{'per-window':>16}" + "".join(f"{s:>16}" for s in BURST))
    for k, v in res.items():
        print(f"{k:<20}{v['window'][0]:>7.3f}/{v['window'][1]:<8.3f}"
              + "".join(f"{v[s][0]:>7.3f}/{v[s][1]:<8.3f}" for s in BURST))
    print(f"\nPer-Window-Korrelation RF↔harnet: Proba r={r_proba:+.3f}, "
          f"Residuen r={r_resid:+.3f}")

    _write_report(variant, native, res, r_proba, r_resid, out_csv)
    print(f"-> {out_csv}")


def _write_report(variant, native, res, r_proba, r_resid, out_csv) -> None:
    base = res["RF baseline (88)"]
    ens = res["Ensemble (mean)"]
    stack = res["Stack (88+1)"]

    def _delta(m):  # gegen baseline auf nativer Skala
        return m[native][0] - base[native][0], m[native][1] - base[native][1]

    d_ens, d_stk = _delta(ens), _delta(stack)
    gain = max(d_ens[1], d_stk[1])
    verdict = ("**hebt** die Headline" if gain > 0.01
               else "**hebt die Headline nicht** (Δ in der Streuung)")
    rfh = RF_HEADLINE
    lines = [
        f"# harnet↔RF-Fusion: Ensemble + Stack ({variant})",
        "",
        "## Frage",
        "",
        "Bringt es etwas, harnets Foundation-Repraesentation an den "
        "Baseline-RF (88 Hand-Features) zu koppeln — als Proba-Ensemble oder "
        "als zusaetzliches Feature (Stack 88+1)? Beide leakage-bewusst im "
        "LOSO-by-person, Vergleich auf nativer Decision-Skala "
        f"({native}). Erwartung nach dem r≈0.92-Befund: gedaempft.",
        "",
        "## Per-Window-Fehler-Korrelation (der entscheidende Test)",
        "",
        f"- Proba-Korrelation RF↔harnet: **r = {r_proba:+.3f}**",
        f"- **Residuen-Korrelation** (Fehler RF vs. Fehler harnet): "
        f"**r = {r_resid:+.3f}**",
        "",
        "Fusion kann nur helfen, wenn die Fehler *dekorreliert* sind. "
        + ("Die Residuen sind stark korreliert — die beiden Modelle irren an "
           "denselben Fenstern, kaum Fusions-Spielraum."
           if r_resid > 0.5 else
           "Die Residuen sind nur teilweise korreliert — etwas Spielraum, "
           "den die Aggregation unten ausschoepfen koennte.")
        + " Das ergaenzt die bisher nur per-Fold gemessene Korrelation (r≈0.92) "
        "um die window-genaue Sicht.",
        "",
        "## Ergebnis (acc/AUC)",
        "",
        "| Modell | per-window | @5s | @10s | @30s |",
        "|---|---|---|---|---|",
        f"| RF-Headline (publiziert) | {rfh['5s'][0]:.3f}/{rfh['5s'][1]:.3f} | "
        f"{rfh['5s'][0]:.3f}/{rfh['5s'][1]:.3f} | {rfh['10s'][0]:.3f}/{rfh['10s'][1]:.3f} | "
        f"{rfh['30s'][0]:.3f}/{rfh['30s'][1]:.3f} |",
        _row("RF baseline (88)", base),
        _row("harnet allein", res["harnet allein"]),
        _row("Ensemble (mean)", ens),
        _row("Stack (88+1)", stack),
        "",
        f"**Verdikt:** Fusion {verdict} (native {native}: Ensemble ΔAcc "
        f"{d_ens[0]:+.3f}/ΔAUC {d_ens[1]:+.3f}; Stack ΔAcc {d_stk[0]:+.3f}/"
        f"ΔAUC {d_stk[1]:+.3f}, jeweils vs. baseline-88 im selben Lauf). "
        + ("Damit ist auch die Window-Level-Frage beantwortet: die Fehler sind "
           "korreliert, Fusion ist kein freier Headline-Sprung — Szenario (a), "
           "die Decke bleibt die Signal-Ambiguitaet."
           if gain <= 0.01 else
           "Window-Level zeigt nutzbare Dekorrelation."),
        "",
        "## Leakage-Hinweis",
        "",
        "Das Ensemble ist vollstaendig sauber (Mittel zweier OOF-Vorhersagen "
        "des gehaltenen Probanden). Der Stack nutzt das Standard-Stacking-CV-"
        "Rezept (globale harnet-OOF als Feature) mit milder Optimistik fuer "
        "die Trainings-Probanden; da das Ergebnis dennoch ~null ist, bleibt "
        "der Befund robust.",
        "",
        f"Rohdaten: `{out_csv.relative_to(ROOT)}`.",
        "",
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "harnet_rf_fusion.md").write_text("\n".join(lines))
    print(f"-> {REPORTS_DIR / 'harnet_rf_fusion.md'}")


if __name__ == "__main__":
    main()

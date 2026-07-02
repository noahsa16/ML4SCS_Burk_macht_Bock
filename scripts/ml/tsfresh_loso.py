"""tsfresh-LOSO gegen die 88-Feature-RF-Baseline (N=20 legacy, 1-s-Fenster).

Extrahiert die EfficientFCParameters-Bank (~780 Features/Kanal x 6 Kanaele)
aus rohen 1-s-IMU-Fenstern und faehrt LOSO-by-person mit RF 200 Trees +
Per-Session-Z-Score (identisches Protokoll wie die Headline).

Der eigentliche Erkenntniswert ist das **Feature-Ranking**, nicht die
Headline: entweder validiert die 800er-Bank die Hand-88 (Top-Features sind
Duplikate) oder ein Exot (Sample-Entropie, Time-Reversal-Asymmetrie, CID)
rankt hoch — dann fehlt den 88 eine Familie. Deshalb speichert der Lauf:

- ``data/processed/tsfresh_features.parquet`` + ``..._meta.csv`` (Cache —
  Re-Analysen ohne 2-h-Re-Extraktion)
- ``models/tsfresh_cv.csv`` (significance-kompatibel) + ``tsfresh_oof.csv``
  (per-window, t_center_ms fuer Marker-FPR-Nachtests)
- ``models/tsfresh_importances.csv`` (mean RF-Importance ueber Folds, Top 50)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from src.features.windows import smooth_labels  # noqa: E402
from src.training.train_loso import _select_sessions  # noqa: E402

IMU_COLS = ["ax", "ay", "az", "rx", "ry", "rz"]
WIN_SEC = 1.0
STRIDE_SEC = 0.5
MAX_GAP_MS = 2500
LABEL_THRESH = 0.6
MAX_WINDOWS_PER_SESSION = 1000
FEATURES_CACHE = ROOT / "data" / "processed" / "tsfresh_features.parquet"
META_CACHE = ROOT / "data" / "processed" / "tsfresh_features_meta.csv"
BASELINE = "RF-88 @1s (N=20): acc 0.869 +/- 0.032 | AUC 0.946"


def _build_windows(merged: pd.DataFrame, fs: float) -> pd.DataFrame:
    win = int(WIN_SEC * fs)
    stride = int(STRIDE_SEC * fs)
    merged = merged.sort_values("ts", kind="stable").reset_index(drop=True)
    merged["label_writing"] = smooth_labels(
        merged["label_writing"].values, merged["ts"].values, MAX_GAP_MS)
    rows = []
    for start in range(0, len(merged) - win + 1, stride):
        chunk = merged.iloc[start:start + win]
        rows.append({
            "start": start,
            "label": int(chunk["label_writing"].mean() >= LABEL_THRESH),
            "t_center_ms": float(chunk["ts"].iloc[win // 2]),
        })
    return pd.DataFrame(rows)


def _to_tsfresh_long(merged: pd.DataFrame, windows: pd.DataFrame, fs: float) -> pd.DataFrame:
    """Long-Format fuer extract_features; nutzt die FINALE window_id-Spalte."""
    win = int(WIN_SEC * fs)
    merged = merged.sort_values("ts", kind="stable").reset_index(drop=True)
    records = []
    for _, row in windows.iterrows():
        wid = int(row["window_id"])
        chunk = merged.iloc[int(row["start"]):int(row["start"]) + win]
        for t_idx, (_, s) in enumerate(chunk.iterrows()):
            for col in IMU_COLS:
                records.append({"id": wid, "time": t_idx, "variable": col,
                                "value": s[col]})
    return pd.DataFrame(records)


def _load_pool() -> tuple[pd.DataFrame, pd.DataFrame]:
    sessions = _select_sessions(include_all=False, min_windows=50, profile="50hz")
    print(f"Pool: {len(sessions)} sessions, {sessions.person_id.nunique()} persons")
    all_windows, all_long = [], []
    offset = 0
    for _, sess in sessions.iterrows():
        sid = sess["session_id"]
        legacy = ROOT / "data" / "processed" / f"{sid}_merged_legacy.csv"
        native = ROOT / "data" / "processed" / f"{sid}_merged.csv"
        src = legacy if legacy.exists() else native
        if not src.exists():
            print(f"  skip {sid} (no merged CSV)")
            continue
        merged = pd.read_csv(src)
        if "ts" not in merged.columns:
            print(f"  skip {sid} (no ts column)")
            continue
        windows = _build_windows(merged, fs=50.0)
        if len(windows) > MAX_WINDOWS_PER_SESSION:
            windows = (windows.groupby("label", group_keys=False)
                       .apply(lambda g: g.sample(
                           min(len(g), MAX_WINDOWS_PER_SESSION // 2),
                           random_state=42), include_groups=True)
                       .sort_values("start").reset_index(drop=True))
        # Why: window_id MUSS nach dem Subsampling vergeben werden — die
        # tsfresh-IDs entstehen aus derselben Spalte; eine Vergabe vor dem
        # Sampling erzeugt ID-Kollisionen zwischen Sessions und mappt
        # Features auf fremde Labels (Feature/Label-Scramble).
        windows["window_id"] = offset + np.arange(len(windows))
        windows["session_id"] = sid
        windows["person_id"] = sess["person_id"]
        all_windows.append(windows)
        all_long.append(_to_tsfresh_long(merged, windows, fs=50.0))
        offset += len(windows)
        print(f"  {sid}: {len(windows)} windows")
    return (pd.concat(all_windows, ignore_index=True),
            pd.concat(all_long, ignore_index=True))


def _zscore_per_session(features: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Headline-Protokoll: jede Session mit den EIGENEN Stats normalisieren
    (train wie test — vgl. _zscore_per_session in train_loso)."""
    out = features.copy()
    for sid in meta["session_id"].unique():
        idx = meta.loc[meta["session_id"] == sid, "window_id"].values
        block = out.loc[idx]
        sigma = block.std().replace(0, 1.0)
        out.loc[idx] = (block - block.mean()) / sigma
    return out


def main() -> None:
    if FEATURES_CACHE.exists() and META_CACHE.exists():
        features = pd.read_parquet(FEATURES_CACHE)
        meta = pd.read_csv(META_CACHE)
        print(f"Cache: {features.shape} aus {FEATURES_CACHE.name}")
    else:
        from tsfresh import extract_features
        from tsfresh.feature_extraction import EfficientFCParameters
        from tsfresh.utilities.dataframe_functions import impute

        meta, all_long = _load_pool()
        print(f"\nTotal windows: {len(meta)}")
        print("Extracting tsfresh features (EfficientFCParameters), ~2 h ...")
        features = extract_features(
            all_long, column_id="id", column_sort="time",
            column_kind="variable", column_value="value",
            default_fc_parameters=EfficientFCParameters(),
            n_jobs=4, disable_progressbar=False, chunksize=50,
        )
        impute(features)
        features = features.astype(np.float32).sort_index()
        features.columns = [str(c) for c in features.columns]
        # Why: der Cache-Write darf den 40-min-Extraktions-Ertrag nie killen
        # (2026-07-02: fehlendes pyarrow crashte hier und verlor die Matrix).
        try:
            features.to_parquet(FEATURES_CACHE)
            print(f"Feature matrix: {features.shape} -> {FEATURES_CACHE}")
        except Exception as e:
            fallback = FEATURES_CACHE.with_suffix(".pkl")
            features.to_pickle(fallback)
            print(f"Parquet fehlgeschlagen ({e}) — Pickle-Fallback: {fallback}")
        meta.to_csv(META_CACHE, index=False)

    features = _zscore_per_session(features, meta)

    persons = meta["person_id"].unique()
    cv_rows, oof_rows = [], []
    importances = np.zeros(features.shape[1])
    n_folds = 0
    for person in persons:
        te = meta["person_id"] == person
        y_train = meta.loc[~te, "label"].values
        y_test = meta.loc[te, "label"].values
        if len(np.unique(y_test)) < 2:
            print(f"  skip {person} (single class in test)")
            continue
        X_train = features.loc[meta.loc[~te, "window_id"].values].values
        X_test = features.loc[meta.loc[te, "window_id"].values].values

        clf = RandomForestClassifier(n_estimators=200, class_weight="balanced",
                                     n_jobs=-1, random_state=42)
        clf.fit(X_train, y_train)
        proba = clf.predict_proba(X_test)[:, 1]
        importances += clf.feature_importances_
        n_folds += 1

        acc = accuracy_score(y_test, (proba >= 0.5).astype(int))
        auc = roc_auc_score(y_test, proba)
        cv_rows.append({"held_out": person, "accuracy": acc, "roc_auc": auc})
        oof_rows.append(pd.DataFrame({
            "person_id": person,
            "session_id": meta.loc[te, "session_id"].values,
            "t_center_ms": meta.loc[te, "t_center_ms"].values,
            "label": y_test, "proba_cal": proba,
        }))
        print(f"  {person}: acc={acc:.3f}  AUC={auc:.3f}")

    cv = pd.DataFrame(cv_rows)
    cv.to_csv(ROOT / "models" / "tsfresh_cv.csv", index=False)
    pd.concat(oof_rows, ignore_index=True).to_csv(
        ROOT / "models" / "tsfresh_oof.csv", index=False)
    imp = (pd.DataFrame({"feature": features.columns,
                         "importance": importances / max(n_folds, 1)})
           .sort_values("importance", ascending=False))
    imp.head(50).to_csv(ROOT / "models" / "tsfresh_importances.csv", index=False)

    print(f"\n{'='*50}")
    print(f"tsfresh LOSO  acc={cv['accuracy'].mean():.3f} +/- {cv['accuracy'].std(ddof=0):.3f}  "
          f"AUC={cv['roc_auc'].mean():.3f} +/- {cv['roc_auc'].std(ddof=0):.3f}")
    print(f"Baseline      {BASELINE}")
    print("\nTop 20 Features (mean RF-Importance ueber Folds):")
    for _, r in imp.head(20).iterrows():
        print(f"  {r.importance:.4f}  {r.feature}")
    print("\n-> models/tsfresh_{cv,oof,importances}.csv")


if __name__ == "__main__":
    main()

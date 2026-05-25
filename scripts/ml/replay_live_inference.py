"""Replay a session's watch samples through LiveInference and compare to
its trained-on-disk labels.

Diagnostic for "live inference is worse than offline benchmark". Two flavors:
  - "honest" mode: replay S033 (model was trained on it). Should match
    the offline accuracy near-perfectly. If it doesn't, the inference
    path is broken (feature extraction, buffer, fs estimate).
  - "cross-session" mode: replay any other Noah session (e.g. S032, S010).
    Tests generalisation. If S033 matches but S010 tanks, the issue is
    out-of-distribution at deployment, not inference plumbing.

Output: per-window prediction vs. label, accuracy/AUC over the session.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.server.inference import LiveInference  # noqa: E402

DATA = ROOT / "data"


def _load_watch(session_id: str) -> pd.DataFrame:
    p = DATA / "raw" / "watch" / f"{session_id}_watch.csv"
    df = pd.read_csv(p).dropna(subset=["ax", "ay", "az", "rx", "ry", "rz", "ts"])
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def _load_window_labels(session_id: str) -> pd.DataFrame:
    p = DATA / "processed" / f"{session_id}_windows.csv"
    df = pd.read_csv(p)
    return df[["t_center_ms", "label"]].sort_values("t_center_ms").reset_index(drop=True)


def main(session_id: str = "S033") -> None:
    print(f"Replaying {session_id} through LiveInference …")
    watch = _load_watch(session_id)
    print(f"  watch rows: {len(watch)}")
    truth = _load_window_labels(session_id)
    print(f"  window labels: {len(truth)}")

    live = LiveInference()
    loaded = live.load_default_model()
    if loaded is None:
        raise SystemExit("no model loaded")
    print(f"  model: {loaded.name}")
    print(f"  trained_fs_hz: {live._bundle.get('sample_rate_hz')}")

    # Feed all samples into the buffer, then sweep through with a 500ms
    # stride producing one prediction per stride (matches training's
    # window=1s/stride=0.5s).
    n_samples = len(watch)
    fs_observed_ms_per_sample = float(
        (watch["ts"].iloc[-1] - watch["ts"].iloc[0]) / (n_samples - 1)
    )
    print(f"  median dt: {np.median(np.diff(watch['ts'])):.1f} ms  "
          f"  observed fs: {1000/fs_observed_ms_per_sample:.1f} Hz")

    # The buffer in live mode is a deque(maxlen=240). We need a similar
    # ring-buffer behaviour. Feed samples one-by-one; after each ~500ms
    # of new samples, call predict() and record.
    samples_per_stride = max(1, int(round(0.5 * 1000 / fs_observed_ms_per_sample)))
    pred_proba: list[float] = []
    pred_t_center_ms: list[int] = []

    print(f"  stride: {samples_per_stride} samples (≈ 0.5 s)")

    # Monkey-patch the stale-buffer guard for the replay (samples are
    # historical so live-time freshness would always fail).
    import time as _t
    fake_now_ms = [int(_t.time() * 1000)]
    real_time = _t.time
    def fake_time():
        return fake_now_ms[0] / 1000.0
    _t.time = fake_time
    try:
        for i, row in watch.iterrows():
            sample_ts = int(row["ts"])
            fake_now_ms[0] = sample_ts + 100  # one tick ahead, well within stale gate
            live.append_sample(
                sample_ts,
                float(row["ax"]), float(row["ay"]), float(row["az"]),
                float(row["rx"]), float(row["ry"]), float(row["rz"]),
            )
            if (i + 1) % samples_per_stride == 0:
                out = live.predict()
                if out is None:
                    continue
                if out.get("rate_mismatch"):
                    continue
                pred_proba.append(out["proba"])
                pred_t_center_ms.append(sample_ts - 500)
    finally:
        _t.time = real_time

    if not pred_proba:
        raise SystemExit("no predictions generated — check fs / buffer length")

    print(f"\n  generated {len(pred_proba)} predictions")

    # Align predictions to truth windows by nearest t_center_ms.
    pred_df = pd.DataFrame({
        "t_center_ms": pred_t_center_ms,
        "proba": pred_proba,
    })
    pred_df["t_center_ms"] = pred_df["t_center_ms"].astype("int64")
    truth["t_center_ms"] = truth["t_center_ms"].astype("int64")
    merged = pd.merge_asof(
        pred_df.sort_values("t_center_ms"),
        truth.sort_values("t_center_ms"),
        on="t_center_ms",
        tolerance=400,
        direction="nearest",
    ).dropna(subset=["label"])
    print(f"  aligned to truth: {len(merged)} pairs")

    if len(merged) < 10:
        raise SystemExit("not enough aligned pairs")

    y = merged["label"].to_numpy()
    p = merged["proba"].to_numpy()
    pred = (p >= 0.5).astype(int)

    print(f"\n=== {session_id} replay metrics ===")
    print(f"  accuracy   : {accuracy_score(y, pred):.3f}")
    print(f"  f1(writing): {f1_score(y, pred, zero_division=0):.3f}")
    try:
        print(f"  roc auc    : {roc_auc_score(y, p):.3f}")
    except ValueError:
        print(f"  roc auc    : n/a (single class)")
    print(f"  mean proba writing: {p[y==1].mean():.3f}")
    print(f"  mean proba idle   : {p[y==0].mean():.3f}")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "S033"
    main(sid)

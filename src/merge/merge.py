"""Watch + Pen zu einem watch-basierten gelabelten Dataset zusammenführen.

Ablauf in ``merge_watch_pen()``:

  1. Rohe CSVs einlesen
  2. δ schätzen (via :mod:`src.alignment`)
  3. Wenn σ ≤ -2 (Confidence ok): pen.local_ts_ms += δ·1000
     Wenn σ > -2 (flache Kurve): δ verwerfen, ohne Shift weitermachen
  4. ``pd.merge_asof`` mit **Watch als Basis**, Pen-Aktivität als Label:
     - innerhalb ±``label_tol_ms`` der nächste Pen-``dot_type`` ∈
       {PEN_DOWN, PEN_MOVE} → ``label_writing = 1``
     - sonst → ``label_writing = 0`` (umfasst auch Pen-Lücken, in denen
       der Pen gar nichts berichtet → "nicht schreiben")
  5. δ und σ als ``df.attrs`` für Downstream-Diagnose anhängen

Output: 1 Zeile pro Watch-Sample (alle Watch-Spalten + ``label_writing``).
"""

import csv
import datetime as dt
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from src.alignment import (
    DEFAULT_PARAMS,
    PenMatchResult,
    match_pen_data,
    reconstruct_watch_wall_clock,
    strokes_from_dot_types,
)
from .prep import load_csv

WRITING_DOT_TYPES = ("PEN_DOWN", "PEN_MOVE")

# Override hooks for tests; production resolves under data/.
_MARKERS_DIR_OVERRIDE: Path | None = None
_SESSIONS_CSV_OVERRIDE: Path | None = None
_SESSION_FROM_PATH = re.compile(r"^(S\d+)_(?:pen|watch)(?:_[a-z0-9]+)?\.csv$")

# Why: Watch-Spill kann Samples einer FRÜHEREN Session in die aktuelle
# nachliefern (S093: 8.925 Samples, davon 4.651 aus der abgebrochenen S092).
# Sie tragen die aktive session_id (der Server stempelt sie beim Ingest), sind
# aber an ihrer Capture-`ts` erkennbar. Toleranz 60 s = dieselbe Konstante wie
# data_outside_session_window; die ts-Achse ist NTP-nah (<100 ms Skew), über
# den gesamten Korpus liegt zwischen legitimen Samples (frühestens 0,08 s NACH
# Start) und Spill (ab 209 s davor) ein leeres Band.
PRE_SESSION_TOL_MS = 60_000
MAX_PRE_SESSION_DROP_FRACTION = 0.20

# Why: |coarse δ| ab hier gilt als Randtreffer der Grid-Suche (Suchraum ±20 s,
# ein Coarse-Schritt Sicherheitsabstand) — siehe Kommentar in merge_watch_pen.
_DELTA_EDGE_SEC = (
    DEFAULT_PARAMS["coarse_end_delta_sec"] - DEFAULT_PARAMS["coarse_step_sec"]
)

# Why: Plausibilitätsgrenze für δ. Pen-`local_ts_ms` und Watch-`ts` werden beide
# gegen die Wall-Clock gestempelt (Server bzw. NTP-nahe Watch) — ein Versatz von
# über 5 s ist physikalisch kein Uhrenproblem, sondern ein Suchartefakt.
# Empirie (Korpus-Audit 2026-08-08, 44 Sessions mit auswertbarem δ): 37 liegen
# bei |δ| ≤ 5 s, die meisten bei ~0. Von den vier Sessions mit großem
# angewandtem δ waren zwei nachweislich Artefakte — S094 (AUC 0,941 statt 0,997)
# und S062 (AUC 0,393 statt 0,999) — und keine einzige nachweislich echt.
_DELTA_PLAUSIBLE_SEC = 5.0

log = logging.getLogger(__name__)


def _markers_dir() -> Path:
    if _MARKERS_DIR_OVERRIDE is not None:
        return _MARKERS_DIR_OVERRIDE
    return Path(__file__).parents[2] / "data" / "raw" / "markers"


def _sessions_csv() -> Path:
    if _SESSIONS_CSV_OVERRIDE is not None:
        return _SESSIONS_CSV_OVERRIDE
    return Path(__file__).parents[2] / "data" / "sessions.csv"


def _session_start_ms(session_id: str | None) -> float | None:
    """start_time der Session als Epoch-ms, oder None wenn nicht auflösbar.

    sessions.csv ist server-owned und gitignored — auf einem frischen Clone
    fehlt sie. None heißt dann "nicht filtern", nie "alles verwerfen".
    """
    if not session_id:
        return None
    path = _sessions_csv()
    if not path.exists():
        return None
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("session_id") != session_id:
                    continue
                start = (row.get("start_time") or "").strip()
                if not start:
                    return None
                return dt.datetime.fromisoformat(start).timestamp() * 1000.0
    except (OSError, ValueError):
        return None
    return None


def _drop_pre_session_samples(
    raw_watch: pd.DataFrame,
    watch_path: str | Path,
) -> tuple[pd.DataFrame, int]:
    """Verwirft Watch-Samples, deren Capture-``ts`` vor dem Session-Start liegt.

    No-op ohne ``ts``-Spalte oder ohne auflösbare ``start_time``. Ein Verwurf
    über ``MAX_PRE_SESSION_DROP_FRACTION`` bricht ab, statt still einen (fast)
    leeren Frame zurückzugeben — ein Ganz-Session-Spill-Drain (S052/S053) ist
    ein Aufnahmefehler, den der Merge nicht kaschieren darf.
    """
    if "ts" not in raw_watch.columns or raw_watch.empty:
        return raw_watch, 0

    session_id = _session_id_from_path(watch_path)
    start_ms = _session_start_ms(session_id)
    if start_ms is None:
        log.info("pre-session filter skipped for %s (no resolvable start_time)",
                 session_id or Path(watch_path).name)
        return raw_watch, 0

    ts = pd.to_numeric(raw_watch["ts"], errors="coerce")
    stale = ts < (start_ms - PRE_SESSION_TOL_MS)
    n_dropped = int(stale.sum())
    if n_dropped == 0:
        return raw_watch, 0

    fraction = n_dropped / len(raw_watch)
    if fraction > MAX_PRE_SESSION_DROP_FRACTION:
        raise ValueError(
            f"{session_id}: pre-session filter would drop {n_dropped} of "
            f"{len(raw_watch)} samples ({fraction:.1%}) — that is a spill-drain "
            f"recording, not a session. Refusing to merge."
        )

    lead_sec = (start_ms - float(ts[stale].min())) / 1000.0
    log.warning("%s: dropped %d pre-session samples (%.2f%%, oldest %.1fs before start)",
                session_id, n_dropped, fraction * 100, lead_sec)
    return raw_watch[~stale], n_dropped


def _session_id_from_path(p: str | Path) -> str | None:
    m = _SESSION_FROM_PATH.match(Path(p).name)
    return m.group(1) if m else None


def estimate_pen_imu_offset(
    raw_pen: pd.DataFrame,
    raw_watch: pd.DataFrame,
) -> PenMatchResult | None:
    """Run the variance-based pen↔IMU alignment on raw CSVs.

    Returns a ``PenMatchResult`` (delta_sec + diagnostics) or None if the
    inputs are too small to align. The caller decides whether to trust
    the returned δ — ``sigma_minimal_variance < -2`` is a reasonable
    threshold (the Swiss reference uses the same heuristic).
    """
    if "local_ts_ms" not in raw_pen.columns or "local_ts_ms" not in raw_watch.columns:
        return None

    pen_ts = pd.to_datetime(
        pd.to_numeric(raw_pen["local_ts_ms"], errors="coerce"),
        unit="ms", utc=True,
    )
    if "ts" not in raw_watch.columns:
        return None
    watch_ts = reconstruct_watch_wall_clock(raw_watch)

    pen_for_match = pd.DataFrame({
        "timestamp": pen_ts,
        "dot_type": raw_pen.get("dot_type", ""),
        "x": pd.to_numeric(raw_pen.get("x"), errors="coerce"),
        "y": pd.to_numeric(raw_pen.get("y"), errors="coerce"),
    }).dropna(subset=["timestamp"])
    pen_strokes = strokes_from_dot_types(pen_for_match)
    if pen_strokes.empty:
        return None

    watch_for_match = pd.DataFrame({
        "timestamp": watch_ts,
        "ax": pd.to_numeric(raw_watch.get("ax"), errors="coerce"),
        "ay": pd.to_numeric(raw_watch.get("ay"), errors="coerce"),
        "az": pd.to_numeric(raw_watch.get("az"), errors="coerce"),
    }).dropna().sort_values("timestamp").reset_index(drop=True)
    if len(watch_for_match) < 50:
        return None

    return match_pen_data(watch_for_match, pen_strokes)


def merge_watch_pen(
    pen_path: str | Path,
    watch_path: str | Path,
    label_tol_ms: int = 40,
    align_clocks: bool = True,
    sigma_threshold: float = -2.0,
) -> pd.DataFrame:
    """Watch-base merge: jedes Watch-Sample bekommt ein Label.

    Pen-Lücken (kein Pen-Sample in ±``label_tol_ms``) → label 0. Das ist
    die Grundlage für den Writing-Detektor, der auf der Watch allein läuft.

    Standard-Toleranz 40 ms = ~2× Watch-Periode bei 50 Hz; kleine Jitter
    werden geschluckt, aber echte Pen-freie Phasen bleiben Label 0.

    Result-DataFrame trägt ``pen_clock_offset_sec`` und ``pen_clock_sigma``
    als ``df.attrs`` für Diagnose.
    """
    raw_pen = load_csv(pen_path)
    raw_watch = load_csv(watch_path)
    # Why: vor der δ-Suche filtern — Spill-Samples liegen ausserhalb des
    # Suchfensters und verfälschen sonst nur die Varianz-Statistik; ausserdem
    # blähen sie die Zeitspanne auf, aus der windows.py fs schätzt (S093:
    # 87,97 statt 99,53 Hz = 12 % Fehler auf allen Spektral-/Jerk-Features).
    raw_watch, pre_session_dropped = _drop_pre_session_samples(raw_watch, watch_path)

    delta_sec = 0.0
    sigma = float("nan")
    delta_rejected: str | None = None
    if align_clocks:
        result = estimate_pen_imu_offset(raw_pen, raw_watch)
        if result is not None and np.isfinite(result.sigma_minimal_variance):
            sigma = result.sigma_minimal_variance
            if sigma <= sigma_threshold:
                # Why: σ misst die TIEFE der Varianz-Senke, nicht ob sie im
                # Suchraum liegt. Fällt J(δ) monoton zum Rand, liefert argmin
                # den Randwert — mit formal gutem σ. S094 (2026-08-08) gab
                # δ = +18,2 s bei σ = −2,19, über einen weiteren Suchraum
                # dagegen δ = −27,15 s: zwei Antworten, beide am Rand, J(0)
                # sogar ein Maximum. Angewandt kostete das ΔAUC 0,997 → 0,941.
                # Ein Randtreffer ist kein Alignment; dann lieber δ = 0.
                #
                # Geprüft wird die COARSE-Stufe, nicht das finale δ: sie
                # entscheidet, ob das Minimum überhaupt im Suchraum liegt. Die
                # Fine-Suche verfeinert nur ±5 s um den Coarse-Treffer und
                # rutscht dabei kosmetisch nach innen (S094: coarse 20,0 →
                # fine 18,2). Ein Guard auf `delta_sec` greift deshalb nicht.
                if abs(result.coarse_delta_sec) >= _DELTA_EDGE_SEC:
                    delta_rejected = "edge_of_search"
                    log.warning(
                        "δ = %+.2fs verworfen: Coarse-Minimum %+.2fs liegt am "
                        "Rand des Suchraums (±%.0fs) trotz σ = %.2f — "
                        "Merge läuft mit δ = 0.",
                        result.delta_sec, result.coarse_delta_sec,
                        DEFAULT_PARAMS["coarse_end_delta_sec"], sigma,
                    )
                elif abs(result.delta_sec) > _DELTA_PLAUSIBLE_SEC:
                    delta_rejected = "implausible_magnitude"
                    log.warning(
                        "δ = %+.2fs verworfen: jenseits der Plausibilitäts-"
                        "grenze von %.0fs (σ = %.2f) — Merge läuft mit δ = 0.",
                        result.delta_sec, _DELTA_PLAUSIBLE_SEC, sigma,
                    )
                else:
                    delta_sec = result.delta_sec

    if "local_ts_ms" not in raw_watch.columns:
        raise ValueError("Watch CSV is missing local_ts_ms — cannot align.")
    if "local_ts_ms" not in raw_pen.columns:
        raise ValueError("Pen CSV is missing local_ts_ms — legacy log not supported.")

    watch = raw_watch.copy()
    watch["local_ts_ms"] = pd.to_numeric(watch["local_ts_ms"], errors="coerce")
    # Why: Join-Achse muss exakt die Achse sein, gegen die δ optimiert wurde
    # (match_pen_data nutzt reconstruct_watch_wall_clock = per-Sample `ts`).
    # local_ts_ms ist Batch-Ankunftszeit: alle Samples eines POSTs teilen
    # einen Wert (Labels batch-quantisiert), und Spill-Drain-Strecken kommen
    # Minuten verspätet an (S043: 5,3 % der Samples >2,5 s, max 13,6 s —
    # Forensik 2026-06-12). Fallback auf local_ts_ms nur ohne ts-Spalte.
    if "ts" in watch.columns:
        wall = pd.to_numeric(watch["ts"], errors="coerce")
        watch["_wall_ms"] = wall.fillna(watch["local_ts_ms"])
    else:
        watch["_wall_ms"] = watch["local_ts_ms"]
    # Why: stable sort preserves arrival order on exact-tie timestamps.
    # Unstable sort scrambled feature inputs in a way live inference
    # doesn't replicate -> 2026-05-25 diagnosis of the live-vs-offline
    # accuracy gap.
    watch = watch.dropna(subset=["_wall_ms"]).sort_values("_wall_ms", kind="stable")
    watch["_wall_ms"] = watch["_wall_ms"].astype(float)
    # Why: Spill-Re-Delivery kann ein bereits geliefertes Sample erneut
    # einspeisen — gleicher Capture-ts und identische Achsen, nur andere
    # Ankunfts-Metadaten. Deduplizieren auf (ts + Achsen) verhindert, dass
    # Doppel-Samples Fenster und Schreibzeit überbewerten; keep="first" behält
    # die ursprüngliche Lieferung. ts allein ist kein Duplikat-Schlüssel: zwei
    # verschiedene Samples teilen bei ms-Auflösung gelegentlich denselben ts.
    _dup_cols = [c for c in ("ts", "ax", "ay", "az", "rx", "ry", "rz", "gx", "gy", "gz")
                 if c in watch.columns]
    if _dup_cols:
        watch = watch.drop_duplicates(subset=_dup_cols, keep="first")

    pen = raw_pen.copy()
    pen["_wall_ms"] = (
        pd.to_numeric(pen["local_ts_ms"], errors="coerce") + delta_sec * 1000.0
    )
    pen = pen.dropna(subset=["_wall_ms"]).sort_values("_wall_ms", kind="stable")
    pen["_wall_ms"] = pen["_wall_ms"].astype(float)
    pen["pen_writing"] = pen["dot_type"].isin(WRITING_DOT_TYPES).astype(int)
    pen_slim = pen[["_wall_ms", "pen_writing"]]

    merged = pd.merge_asof(
        watch,
        pen_slim,
        on="_wall_ms",
        tolerance=float(label_tol_ms),
        direction="nearest",
    )
    # Why: kein Pen-Sample in Toleranz → fillna(0) heisst "nicht schreiben".
    merged["label_writing"] = merged["pen_writing"].fillna(0).astype(int)
    merged = merged.drop(columns=["pen_writing"]).reset_index(drop=True)
    merged.attrs["pen_clock_offset_sec"] = delta_sec
    merged.attrs["pen_clock_sigma"] = sigma
    merged.attrs["pre_session_dropped"] = pre_session_dropped
    if delta_rejected:
        merged.attrs["pen_clock_delta_rejected"] = delta_rejected

    # Why: Study Mode emits per-session task markers; sessions without a
    # markers CSV (legacy + non-study) merge unchanged for backward-compat.
    session_id = _session_id_from_path(pen_path) or _session_id_from_path(watch_path)
    if session_id is not None:
        markers_path = _markers_dir() / f"{session_id}_markers.csv"
        if markers_path.exists():
            markers = pd.read_csv(markers_path)
            boundaries = markers[markers["event"].isin(
                ["task_start", "task_end", "abort", "study_end"]
            )].copy()
            boundaries["timestamp_ms"] = boundaries["timestamp_ms"].astype("int64")
            boundaries = boundaries.sort_values("timestamp_ms").reset_index(drop=True)

            intervals: list[dict] = []
            active: dict | None = None
            for _, row in boundaries.iterrows():
                if row["event"] == "task_start":
                    active = {
                        "start": int(row["timestamp_ms"]),
                        "task_id": row.get("task_id", ""),
                        "task_category": row.get("task_category", ""),
                    }
                elif row["event"] in ("task_end", "abort", "study_end") and active is not None:
                    active["end"] = int(row["timestamp_ms"])
                    intervals.append(active)
                    active = None

            merged["task_id"] = pd.NA
            merged["task_category"] = pd.NA
            # Why: Marker tragen Server-Wall-Clock; die Watch-`ts`-Achse ist
            # NTP-nah (<100 ms Skew) — für Minuten-lange Task-Blöcke exakt
            # genug, und anders als local_ts_ms nicht durch Spill verzerrt.
            for iv in intervals:
                mask = (
                    (merged["_wall_ms"] >= iv["start"])
                    & (merged["_wall_ms"] < iv["end"])
                )
                merged.loc[mask, "task_id"] = iv["task_id"]
                merged.loc[mask, "task_category"] = iv["task_category"]

    return merged.drop(columns=["_wall_ms"])

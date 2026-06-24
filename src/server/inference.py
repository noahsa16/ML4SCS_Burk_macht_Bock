"""Live writing-detection inference fuer den Focus-Tracker.

Stateless Singleton der ein Modell laedt, einen Rolling-Sample-Buffer
fuehrt und auf Anfrage eine Schreib-Wahrscheinlichkeit liefert.

Datenfluss:
    routes/watch.py POST /watch (pro Sample)
        -> live.append_sample(ts_ms, ax, ay, az, rx, ry, rz)
    broadcast._status_loop (1 Hz Tick)
        -> live.predict() -> dict | None -> WS-Payload['live_inference']

Feature-Paritaet zum Training: wir rufen _window_features() aus
src.features.windows direkt auf. Dasselbe was im Trainings-CSV-Pfad
laeuft, also keine Drift-Quelle.

Modellwahl: rf_noah.joblib (personalisiert) wenn vorhanden, sonst
rf_all.joblib (generisch). Erlaubt schmerzfreien Toggle spaeter.

Optionaler Per-User-Z-Score: wenn das Joblib zscore_mu/sigma traegt,
werden Features vor predict mit diesen festen Statistiken normiert.
rf_noah hat aktuell None (datengetriebene Entscheidung) - der Code
bleibt aber generisch fuer kuenftige Modelle.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from src.evaluation.hmm import OnlineForwardFilter
from src.features.gravity import GRAVITY_FEATURE_NAMES, _gravity_window_features
from src.features.windows import _window_features

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"

# Why: rf_all (LOSO-Headline) ist auf per-Session-z-gescorten Features
# trainiert und traegt KEIN eingebackenes mu/sigma. Live bekaeme es rohe
# Features und saegte systematisch falsch vorher (Distribution-Mismatch wie
# beim Sort-Stability-Bug: AUC plausibel, Accuracy kollabiert). Es ist von
# einem legitimen no-zscore-Modell (rf_noah) am Bundle nicht unterscheidbar,
# also gehoert es weder in die Auto-Fallback-Kette noch in den Picker. Nur
# rf_noah (no-zscore) + rf_all_live (baked mu/sigma) sind live-deploybar.
_DEFAULT_MODEL_PATHS = (
    MODELS / "rf_noah.joblib",
    MODELS / "rf_all_live.joblib",
)

# Why: nur Modelle, die als Live-Inferenz gemeint sind, sollen im UI-Picker
# auftauchen. rf_S007 / rf_S013 sind Within-Session-Debug-Artefakte und
# wuerden den Picker verschmutzen. rf_all ist bewusst ausgeschlossen (siehe
# _DEFAULT_MODEL_PATHS: nicht live-tauglich). Diese Liste ist die Whitelist.
_USER_FACING_MODEL_NAMES = frozenset({"rf_noah", "rf_all_live"})

# Why: kausaler HMM-Post-Processor auf der Live-Proba. Die 2x2-Übergangsmatrix
# + Prior beschreiben die Label-Dynamik (Klebrigkeit der Schreib-/Idle-Phasen),
# nicht den RF -> ein File deckt rf_noah wie rf_all_live ab (kein Retraining).
# Offline hebt das den RF-1s acc 0.881 -> 0.905 (reports/hmm_postprocess.md);
# live glättet es die Schreibzeit-Entscheidung mit ~16 s adaptivem Gedächtnis.
HMM_LIVE_PATH = MODELS / "hmm_live.json"

WINDOW_SEC = 1.0
SPARKLINE_MAXLEN = 60  # 1 min of 1-s-ticks
BUFFER_MAXLEN = 240    # 2 s headroom @ 120 Hz worst case
# Why: wenn der juengste Sample aelter ist als das, gilt der Buffer als
# kalt - keine Inferenz auf veralteten Daten (z.B. nach Stream-Stopp).
STALE_BUFFER_MS = 1500


class LiveInference:
    """Loaded model + rolling IMU buffer + recent proba history."""

    def __init__(self) -> None:
        self._bundle: Optional[dict] = None
        self._loaded_from: Optional[Path] = None
        # Rows: (ts_ms, ax, ay, az, rx, ry, rz, gx, gy, gz)
        # gx/gy/gz are CoreMotion gravity (Modern pool); NaN for Legacy
        # 6-channel streams. Keeping gravity in the SAME tuple guarantees
        # per-sample alignment under any reorder — the structural fix for
        # the sort-stability bug class (siehe reports/sort_stability_bug.md).
        self._buffer: deque[tuple] = deque(maxlen=BUFFER_MAXLEN)
        self._proba_history: deque[tuple[int, float]] = deque(maxlen=SPARKLINE_MAXLEN)
        # Cumulative writing time today, reset by date change in predict().
        self._today_date: Optional[str] = None
        self._today_writing_seconds: float = 0.0
        # Sandbox-Load (Web-Cockpit): ein Run-Joblib temporär, ohne Whitelist
        # und ohne Headline-Überschreibung. Reines Label-Flag.
        self._sandbox: bool = False
        # Kausaler HMM-Filter auf der Live-Proba. Lazy aus HMM_LIVE_PATH; None
        # wenn das File fehlt (graceful fallback auf die rohe Entscheidung).
        # _hmm_tried verhindert wiederholte Lade-Versuche bei fehlendem File.
        self._hmm: Optional[OnlineForwardFilter] = None
        self._hmm_tried: bool = False

    def load_default_model(self) -> Optional[Path]:
        for path in _DEFAULT_MODEL_PATHS:
            if path.exists():
                return self.load_model(path)
        log.warning("live inference: no model found in %s", MODELS)
        return None

    def load_model(self, path: Path) -> Optional[Path]:
        if not path.exists():
            log.warning("live inference: model not found at %s", path)
            return None
        self._bundle = joblib.load(path)
        self._loaded_from = path
        self._sandbox = False
        # Modell-Wechsel = neue Proba-Dynamik -> HMM-Zustand verwerfen, damit der
        # Prior des alten Modells nicht in die Entscheidungen des neuen blutet.
        self._reset_hmm()
        log.info(
            "live inference: loaded %s person=%s rate=%s n=%s",
            path.name,
            self._bundle.get("person_id"),
            self._bundle.get("sample_rate_hz"),
            self._bundle.get("n_windows"),
        )
        return path

    def load_sandbox(self, path: Path) -> bool:
        """Lädt ein beliebiges Run-Joblib temporär (ohne Whitelist).

        Für den Demo-Live-Test eines frisch trainierten Modells, ohne die
        kanonische Headline zu überschreiben. ``model_id`` meldet 'sandbox';
        der Rolling-Buffer wird geleert (sauberer Neustart wie beim regulären
        Modell-Swap).
        """
        if self.load_model(path) is None:
            return False
        self._sandbox = True
        self.clear_buffer()
        return True

    @staticmethod
    def list_available() -> list[dict]:
        """Discover models in models/ that the live picker should offer."""
        out: list[dict] = []
        for path in sorted(MODELS.glob("rf_*.joblib")):
            if path.stem not in _USER_FACING_MODEL_NAMES:
                continue
            try:
                bundle = joblib.load(path)
            except Exception:  # noqa: BLE001
                log.exception("failed to read %s", path)
                continue
            out.append({
                "id": path.stem,
                "path": str(path),
                "person_id": bundle.get("person_id"),
                "sample_rate_hz": bundle.get("sample_rate_hz"),
                "trained_on": bundle.get("trained_on"),
                "n_windows": bundle.get("n_windows"),
                "normalisation": bundle.get("normalisation",
                    "baked" if bundle.get("zscore_mu") else "none"),
                "note": bundle.get("note"),
            })
        return out

    def append_sample(
        self, ts_ms: int,
        ax: float, ay: float, az: float,
        rx: float, ry: float, rz: float,
        gx: Optional[float] = None,
        gy: Optional[float] = None,
        gz: Optional[float] = None,
    ) -> None:
        if None in (ax, ay, az, rx, ry, rz):
            return

        # Why: Legacy 6-channel streams omit gravity -> store NaN so the
        # tuple shape stays fixed (10 cols). A Modern model detects the NaN
        # and skips prediction (missing_channels) rather than predicting on
        # garbage; a Legacy model ignores the extra columns entirely.
        def _g(v: Optional[float]) -> float:
            return float(v) if v is not None else float("nan")

        self._buffer.append((int(ts_ms), float(ax), float(ay), float(az),
                             float(rx), float(ry), float(rz),
                             _g(gx), _g(gy), _g(gz)))

    def clear_buffer(self) -> None:
        self._buffer.clear()

    def _ensure_hmm(self) -> Optional[OnlineForwardFilter]:
        """Lazy-load the live HMM filter from HMM_LIVE_PATH (JSON, safe).

        Returns None when the params file is absent -> the caller falls back to
        the raw proba decision. _hmm_tried guards against re-reading a missing
        file on every tick.
        """
        if self._hmm is not None or self._hmm_tried:
            return self._hmm
        self._hmm_tried = True
        if not HMM_LIVE_PATH.exists():
            log.info("live inference: no HMM params at %s -> raw decision", HMM_LIVE_PATH)
            return None
        try:
            params = json.loads(HMM_LIVE_PATH.read_text(encoding="utf-8"))
            self._hmm = OnlineForwardFilter(params["transition"], params["priors"])
            log.info("live inference: HMM filter loaded (memory ~%ss)",
                     params.get("effective_memory_sec"))
        except (OSError, ValueError, KeyError):
            log.exception("live inference: failed to load HMM params")
            self._hmm = None
        return self._hmm

    def _reset_hmm(self) -> None:
        """Drop accumulated HMM state at stream gaps / model swaps."""
        if self._hmm is not None:
            self._hmm.reset()

    @property
    def model_id(self) -> Optional[str]:
        if self._sandbox:
            return "sandbox"
        return self._loaded_from.stem if self._loaded_from else None

    @property
    def model_meta(self) -> dict:
        if not self._bundle:
            return {"model_id": None}
        return {
            "model_id": self.model_id,
            "person_id": self._bundle.get("person_id"),
            "sample_rate_hz": self._bundle.get("sample_rate_hz"),
            "trained_on": self._bundle.get("trained_on"),
            "n_windows": self._bundle.get("n_windows"),
        }

    def _estimate_fs(self) -> float:
        if len(self._buffer) < 10:
            return 0.0
        ts_first = self._buffer[0][0]
        ts_last = self._buffer[-1][0]
        span_ms = ts_last - ts_first
        if span_ms <= 0:
            return 0.0
        return (len(self._buffer) - 1) * 1000.0 / span_ms

    def _extract_features(self, recent: list[tuple], fs_hz: float) -> dict[str, float]:
        """Compose the live feature vector exactly like build_windows does.

        88 dynamic features from the 6 IMU channels, plus the 4 gravity
        features when the window carries non-NaN gx/gy/gz. Slicing 1:7 vs
        7:10 keeps the IMU window at (N, 6) for _window_features regardless
        of the gravity columns.
        """
        imu = np.array([row[1:7] for row in recent], dtype=float)
        feats = _window_features(imu, fs_hz=fs_hz)
        grav = np.array([row[7:10] for row in recent], dtype=float)
        if not np.isnan(grav).any():
            feats.update(_gravity_window_features(
                pd.DataFrame(grav, columns=["gx", "gy", "gz"])
            ))
        return feats

    def predict(self) -> Optional[dict]:
        if self._bundle is None:
            if self.load_default_model() is None:
                return None

        if len(self._buffer) < 10:
            return None

        now_ms = int(time.time() * 1000)
        latest_ts = self._buffer[-1][0]
        if now_ms - latest_ts > STALE_BUFFER_MS:
            # Stream-Lücke: HMM-Zustand verwerfen, sonst klebt der Prior von vor
            # der Pause in der nächsten Phase (stateful-Caveat). Dann kalt zurück.
            self._reset_hmm()
            return None

        fs = self._estimate_fs()
        if fs <= 0:
            return None

        # Why: das Modell wurde bei einer bestimmten Sample-Rate trainiert
        # (rf_noah = 100 Hz). Bei deutlicher Abweichung verschieben sich
        # spektrale Feature-Verteilungen, ohne dass der RF einen Fehler
        # signalisiert -- predict() gaebe scheinbar valide Wahrscheinlichkeiten
        # auf out-of-distribution Daten zurueck. Lieber transparent skippen.
        trained_fs = self._bundle.get("sample_rate_hz")
        if trained_fs and abs(fs - trained_fs) / trained_fs > 0.2:
            self._reset_hmm()  # kein gültiges Emission-Signal -> Zustand verwerfen
            return {
                "writing": False,
                "proba": 0.0,
                "model_id": self.model_id,
                "person_id": self._bundle.get("person_id"),
                "fs_hz": round(fs, 1),
                "trained_fs_hz": trained_fs,
                "rate_mismatch": True,
                "today_writing_seconds": round(self._today_writing_seconds, 1),
            }

        n_window = max(8, int(round(WINDOW_SEC * fs)))
        if len(self._buffer) < n_window:
            return None

        recent = list(self._buffer)[-n_window:]
        feature_cols = self._bundle["feature_cols"]
        is_modern = set(GRAVITY_FEATURE_NAMES).issubset(feature_cols)

        # Why: ein Modern-Modell (92 Features) braucht motion.gravity. Wenn
        # der Stream keine Gravity liefert (Legacy-Watch -> NaN), wuerden die
        # 4 Gravity-Features NaN sein und predict() gaebe Garbage zurueck.
        # Transparent skippen, analog zum rate_mismatch-Guard.
        if is_modern and np.isnan(
            np.array([row[7:10] for row in recent], dtype=float)
        ).any():
            self._reset_hmm()  # kein gültiges Emission-Signal -> Zustand verwerfen
            return {
                "writing": False,
                "proba": 0.0,
                "model_id": self.model_id,
                "person_id": self._bundle.get("person_id"),
                "fs_hz": round(fs, 1),
                "missing_channels": True,
                "today_writing_seconds": round(self._today_writing_seconds, 1),
            }

        feats = self._extract_features(recent, fs_hz=fs)
        x = np.array([feats[c] for c in feature_cols], dtype=float)

        mu = self._bundle.get("zscore_mu")
        sigma = self._bundle.get("zscore_sigma")
        if mu is not None and sigma is not None:
            mu_vec = np.array([mu[c] for c in feature_cols], dtype=float)
            sig_vec = np.array([sigma[c] for c in feature_cols], dtype=float)
            x = (x - mu_vec) / sig_vec

        clf = self._bundle["model"]
        proba = float(clf.predict_proba(x.reshape(1, -1))[0, 1])

        # Why: die rohe 1-s-Proba bleibt für die instantane Pille + Intensität
        # (sofort reaktiv). Der kausale HMM-Filter glättet sie zur Schreibzeit-
        # ENTSCHEIDUNG (writing) — dort liegt der Genauigkeitsgewinn fürs
        # Zeit-Tracking. Fehlt das Param-File, fällt writing auf proba>=0.5
        # zurück. proba_hmm wird mitgesendet (UI/Debug), aber nicht geloggt.
        hmm = self._ensure_hmm()
        if hmm is not None:
            proba_hmm = hmm.step(proba)
            writing = proba_hmm >= 0.5
        else:
            proba_hmm = None
            writing = proba >= 0.5

        self._proba_history.append((now_ms, proba))
        self._tick_daily_aggregate(writing)

        payload = {
            "writing": writing,
            "proba": round(proba, 3),
            "model_id": self.model_id,
            "person_id": self._bundle.get("person_id"),
            "fs_hz": round(fs, 1),
            "window_samples": n_window,
            "today_writing_seconds": round(self._today_writing_seconds, 1),
        }
        if proba_hmm is not None:
            payload["proba_hmm"] = round(proba_hmm, 3)
        return payload

    def _tick_daily_aggregate(self, writing: bool) -> None:
        # Why: ein Tick = 1 s Window-Decision. Ueber den Tag aufsummiert ist
        # das die "Focus today"-Zahl. Datums-Wechsel resettet, ohne Persistenz
        # ueber Server-Restart (das ist Task 5 mit dem CSV-Log).
        today = time.strftime("%Y-%m-%d")
        if self._today_date != today:
            self._today_date = today
            self._today_writing_seconds = 0.0
        if writing:
            self._today_writing_seconds += WINDOW_SEC

    def sparkline(self) -> list[dict]:
        return [{"t": t, "p": round(p, 3)} for t, p in self._proba_history]


live = LiveInference()

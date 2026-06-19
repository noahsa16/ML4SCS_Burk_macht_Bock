"""Live-Trainings-Lauf: State-Machine + Subprozess + psutil-Sampling.

Genau EIN Lauf gleichzeitig. Der Runner läuft als asyncio-Subprozess mit
--emit-json (Muster wie pen_proc.py); der stdout-Reader parst JSON-Events und
aktualisiert den State, der über den bestehenden WS-Tick gebroadcastet wird.

Die reine Event-Verarbeitung (_on_started/_handle_event/snapshot) ist
FastAPI-/Subprozess-frei und damit unit-testbar.
"""
from __future__ import annotations

import asyncio
import json
import signal
import sys
import time

import psutil

from src.training import registry
from . import training_runs


def _build_cmd(model: str, pool: str, by: str, zscore: bool, run_dir,
               burst_scales: str | None = None,
               window_sec: float | None = None,
               max_gap_ms: float | None = None) -> list[str]:
    """Subprozess-Kommando je nach Runner der Modell-Familie (isoliert testbar).

    Klassische Modelle teilen ``src.training.train_loso`` (--model, voller
    Parametersatz). Deep-Sequenz-Modelle teilen ``src.training.deep`` und
    laufen mit festem 1-s-Input, person-LOSO und festen 5/10/30-Burst-Skalen —
    ``by`` / ``burst_scales`` / ``window_sec`` gelten dort nicht (rohe
    Sequenzen) und werden bewusst nicht durchgereicht.
    """
    if registry.get(model).runner == "src.training.deep":
        cmd = [sys.executable, "-u", "-m", "src.training.deep",
               "--emit-json", "--model", model, "--pool", pool,
               "--run-dir", str(run_dir)]
        # Why: Deep-Z-Score-Default ist AUS -- nur das opt-in-Flag durchreichen.
        if zscore:
            cmd.append("--zscore")
        if max_gap_ms is not None:
            cmd += ["--max-gap-ms", str(max_gap_ms)]
        return cmd

    cmd = [sys.executable, "-u", "-m", "src.training.train_loso",
           "--emit-json", "--model", model, "--pool", pool, "--by", by,
           "--run-dir", str(run_dir)]
    if not zscore:
        cmd.append("--no-zscore")
    # Why: "" is meaningful (only the 1 s base) — pass it through; None means
    # "use the CLI default 5,10,30" so we omit the flag entirely.
    if burst_scales is not None:
        cmd += ["--burst-scales", burst_scales]
    # Feature-Build-Parameter: None = Backend-Default (gecachte 1s/2500-Windows).
    if window_sec is not None:
        cmd += ["--window-sec", str(window_sec)]
    if max_gap_ms is not None:
        cmd += ["--max-gap-ms", str(max_gap_ms)]
    return cmd


class TrainingRun:
    # Grace nach SIGINT, bevor der Runner hart gekillt wird. Kurz genug, dass
    # ein Stop sich sofort anfühlt; lang genug, dass ein SIGINT-ehrender Runner
    # noch ein graceful run_end (partial) emittieren kann. In Tests überschrieben.
    _stop_grace_sec = 8.0

    # Uhr für die Laufzeit-Messung; in Tests durch eine deterministische
    # Funktion ersetzbar, damit _handle_event ohne echte Zeit prüfbar bleibt.
    _clock = staticmethod(time.monotonic)

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = "idle"            # idle | running | done | error
        self.stopping = False          # True ab Stop-Request bis Terminal-Phase
        self.model: str | None = None
        self.pool: str | None = None
        self.run_id: str | None = None
        self.fold = 0
        self.n = 0
        self.folds: list[dict] = []
        self.confusion = {"tn": 0, "fp": 0, "fn": 0, "tp": 0}
        self.summary: dict = {}
        self.log: list[str] = []
        self.error: str | None = None
        self.hw = {"cpu_pct": 0.0, "ram_gb": 0.0}
        self.partial = False
        # Laufzeit-Messung: pro-Fold-Sekunden + Gesamtzeit, persistiert bei
        # Terminal-Phase (timing.json) → speist die datengetriebene Schätzung.
        self.fold_secs: list[dict] = []
        self.total_sec: float | None = None
        self._run_t0: float | None = None
        self._fold_t0: float | None = None
        self._run_dir = None
        # Deep-Modelle: echte Per-Epochen-Loss/Val-AUC des aktuellen Folds.
        self.epoch: int | None = None
        self.epoch_loss: float | None = None
        self.loss_hist: list[dict] = []
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None

    def is_busy(self) -> bool:
        return self.phase == "running"

    # ---- event handling (pure, unit-testable) ----
    def _on_started(self, model: str, pool: str, run_id: str) -> None:
        self.reset()
        self.phase = "running"
        self.model, self.pool, self.run_id = model, pool, run_id
        self._run_t0 = self._clock()

    def _handle_event(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "run_start":
            self.n = int(ev.get("n_folds", self.n))
        elif t == "fold_start":
            self.fold = int(ev.get("idx", self.fold))
            self._fold_t0 = self._clock()
            # Jeder Fold trainiert frisch → Loss-Verlauf pro Fold neu.
            self.loss_hist = []
            self.epoch = None
            self.epoch_loss = None
        elif t == "epoch":
            self.epoch = int(ev.get("epoch", 0))
            self.epoch_loss = float(ev.get("loss", 0.0))
            self.loss_hist.append({"epoch": self.epoch, "loss": self.epoch_loss,
                                   "val_auc": float(ev.get("val_auc", 0.0))})
        elif t == "fold_end":
            self.fold = int(ev.get("idx", self.fold))
            self.n = int(ev.get("n", self.n))
            self.folds.append({k: ev.get(k) for k in
                               ("idx", "person", "acc", "auc", "f1")})
            if self._fold_t0 is not None:
                self.fold_secs.append({"person": ev.get("person"),
                                       "sec": self._clock() - self._fold_t0})
                self._fold_t0 = None
            c = ev.get("confusion") or {}
            for k in self.confusion:
                self.confusion[k] += int(c.get(k, 0))
            self.log.append(
                f"Fold {ev.get('idx')} {ev.get('person')} · "
                f"acc={ev.get('acc')} auc={ev.get('auc')}")
        elif t == "run_end":
            self.partial = bool(ev.get("partial", False))
            self.summary = {k: ev.get(k) for k in
                            ("mean_acc", "std_acc", "auc", "f1", "burst",
                             "out_dir", "n_done")}
            if self._run_t0 is not None:
                self.total_sec = self._clock() - self._run_t0
            self.phase = "done"
        elif t == "error":
            self.error = str(ev.get("message", "unknown"))
            self.phase = "error"

    def _persist_timing(self) -> None:
        """Schreibt timing.json, sobald fertige Folds vorliegen. Läufe ohne
        einen einzigen fertigen Fold (sofort gestoppt) werden übersprungen,
        damit keine Null-Dauer den Schätz-Pool verfälscht."""
        if self._run_dir is None or not self.fold_secs:
            return
        total = self.total_sec
        if total is None and self._run_t0 is not None:
            total = self._clock() - self._run_t0
        training_runs.write_timing(self._run_dir, self.fold_secs, total)

    def snapshot(self) -> dict:
        # Läuft → live verstrichene Zeit; terminal → eingefrorene Gesamtzeit.
        if self.phase == "running" and self._run_t0 is not None:
            elapsed = self._clock() - self._run_t0
        else:
            elapsed = self.total_sec
        return {
            "phase": self.phase, "model": self.model, "pool": self.pool,
            "run_id": self.run_id, "fold": self.fold, "n": self.n,
            "folds": self.folds, "confusion": self.confusion,
            "summary": self.summary, "partial": self.partial,
            "error": self.error, "hw": self.hw, "stopping": self.stopping,
            "elapsed_sec": elapsed, "epoch": self.epoch,
            "epoch_loss": self.epoch_loss, "loss_hist": self.loss_hist,
            "log": self.log[-8:],
        }

    # ---- subprocess lifecycle ----
    async def start(self, model: str, pool: str, by: str = "person",
                    zscore: bool = True,
                    burst_scales: str | None = None,
                    window_sec: float | None = None,
                    max_gap_ms: float | None = None) -> dict:
        if self.is_busy():
            return {"error": "busy"}
        run_id = training_runs.new_run_id(model, pool)
        rdir = training_runs.run_dir(run_id)
        training_runs.write_config(
            rdir, {"model": model, "pool": pool, "by": by, "zscore": zscore,
                   "burst_scales": burst_scales, "window_sec": window_sec,
                   "max_gap_ms": max_gap_ms})
        self._on_started(model, pool, run_id)
        self._run_dir = rdir
        cmd = _build_cmd(model, pool, by, zscore, rdir,
                         burst_scales=burst_scales, window_sec=window_sec,
                         max_gap_ms=max_gap_ms)
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(training_runs.ROOT),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        self._reader = asyncio.create_task(self._read(self._proc))
        return {"ok": True, "run_id": run_id}

    async def _read(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        try:
            ps = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:
            ps = None
        while True:
            try:
                line = await proc.stdout.readline()
            except ValueError:
                # asyncio StreamReader 64 KB line limit — drain + continue.
                await proc.stdout.read(65536)
                continue
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if text.startswith("{"):
                try:
                    self._handle_event(json.loads(text))
                except json.JSONDecodeError:
                    pass
            if ps is not None:
                try:
                    self.hw = {"cpu_pct": ps.cpu_percent(interval=None),
                               "ram_gb": ps.memory_info().rss / 1e9}
                except psutil.NoSuchProcess:
                    pass
        rc = await proc.wait()
        # Runner endete ohne run_end (run_end setzt sonst phase=done).
        if self.phase == "running":
            if self.stopping:
                # Why: vom Nutzer gestoppt → sauberer partial-Done statt "error",
                # auch wenn der Runner via Kill endete (SIGINT nicht geehrt).
                self.partial = True
                self.phase = "done"
            elif rc != 0:
                self.error = f"runner exited with code {rc}"
                self.phase = "error"
        # Why: auch partial/fehlgeschlagene Läufe tragen gültige Fold-Dauern bei
        # (fertige Folds sind echte Samples) — _persist_timing no-opt sonst.
        self._persist_timing()
        self.stopping = False

    async def stop(self) -> dict:
        """Stop mit Eskalation: SIGINT (Runner finalisiert fertige Folds als
        partial run_end) → nach ``_stop_grace_sec`` hart killen, falls der
        Runner SIGINT nicht (rechtzeitig) ehrt. ``stopping`` flippt sofort, damit
        der nächste WS-Tick „wird gestoppt…" zeigt (kein toter Klick)."""
        if self._proc and self._proc.returncode is None:
            self.stopping = True
            self._proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._proc.wait(),
                                       timeout=self._stop_grace_sec)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        return {"ok": True}


run = TrainingRun()

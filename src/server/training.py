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

import psutil

from . import training_runs


class TrainingRun:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.phase = "idle"            # idle | running | done | error
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
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None

    def is_busy(self) -> bool:
        return self.phase == "running"

    # ---- event handling (pure, unit-testable) ----
    def _on_started(self, model: str, pool: str, run_id: str) -> None:
        self.reset()
        self.phase = "running"
        self.model, self.pool, self.run_id = model, pool, run_id

    def _handle_event(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "run_start":
            self.n = int(ev.get("n_folds", self.n))
        elif t == "fold_start":
            self.fold = int(ev.get("idx", self.fold))
        elif t == "fold_end":
            self.fold = int(ev.get("idx", self.fold))
            self.n = int(ev.get("n", self.n))
            self.folds.append({k: ev.get(k) for k in
                               ("idx", "person", "acc", "auc", "f1")})
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
            self.phase = "done"
        elif t == "error":
            self.error = str(ev.get("message", "unknown"))
            self.phase = "error"

    def snapshot(self) -> dict:
        return {
            "phase": self.phase, "model": self.model, "pool": self.pool,
            "run_id": self.run_id, "fold": self.fold, "n": self.n,
            "folds": self.folds, "confusion": self.confusion,
            "summary": self.summary, "partial": self.partial,
            "error": self.error, "hw": self.hw,
            "log": self.log[-8:],
        }

    # ---- subprocess lifecycle ----
    async def start(self, model: str, pool: str, by: str = "person") -> dict:
        if self.is_busy():
            return {"error": "busy"}
        run_id = training_runs.new_run_id(model, pool)
        rdir = training_runs.run_dir(run_id)
        training_runs.write_config(rdir, {"model": model, "pool": pool, "by": by})
        self._on_started(model, pool, run_id)
        cmd = [sys.executable, "-u", "-m", "src.training.train_loso",
               "--emit-json", "--model", model, "--pool", pool, "--by", by,
               "--run-dir", str(rdir)]
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
        if rc != 0 and self.phase == "running":
            self.error = f"runner exited with code {rc}"
            self.phase = "error"

    async def stop(self) -> dict:
        """Graceful: SIGINT → Runner finalisiert fertige Folds (partial run_end)."""
        if self._proc and self._proc.returncode is None:
            self._proc.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=20)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
        return {"ok": True}


run = TrainingRun()

"""
WebSocket-Broadcasting und der 1-Sekunden-Status-Loop.

_broadcast() schickt eine Nachricht an alle verbundenen Clients.
_status_loop() läuft als asyncio-Task und sendet jede Sekunde den
aktuellen Status — inklusive Sample-Raten und Chart-Puffer-Update.
"""

import asyncio
import time
from typing import Any

from fastapi import WebSocket

from .csv_io import _pen_last_dot, _pen_sample_count
from .state import state
from .status import _status_payload


async def _broadcast(msg: dict):
    """Sendet msg an alle verbundenen WebSocket-Clients. Tote Verbindungen werden still entfernt."""
    dead = set()
    for ws in list(state.ws_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    state.ws_clients -= dead


async def _status_loop():
    """
    Läuft dauerhaft (als asyncio.Task) und macht jede Sekunde drei Dinge:
      1. Sample-Raten für Pen und Watch neu berechnen
      2. Den Chart-Puffer mit einem aggregierten Datenpunkt befüllen
      3. Den aktuellen Status an alle WS-Clients broadcasten
    """
    while True:
        await asyncio.sleep(1.0)
        sid = state.active["session_id"] if state.active else None
        pen_samples = _pen_sample_count(sid) if sid else 0
        last_pen_dot = _pen_last_dot(sid) if sid else None

        now = time.time()

        # Pen-Rate: Differenz der Dot-Anzahl seit letztem Tick
        pen_elapsed = max(0.001, now - state.last_pen_rate_check)
        state.pen_rate_hz = max(0.0, (pen_samples - state.last_pen_count_for_rate) / pen_elapsed)
        state.last_pen_count_for_rate = pen_samples
        state.last_pen_rate_check = now

        # Watch-Rate: analog über watch_total_sample_count
        watch_elapsed = max(0.001, now - state.last_watch_rate_check)
        state.watch_rate_hz = max(
            0.0,
            (state.watch_total_sample_count - state.last_watch_count_for_rate) / watch_elapsed,
        )
        state.last_watch_count_for_rate = state.watch_total_sample_count
        state.last_watch_rate_check = now

        # Neuen Pen-Dot ins sample_log schreiben, wenn er sich geändert hat
        if last_pen_dot:
            key = (
                last_pen_dot.get("local_ts_ms"),
                last_pen_dot.get("timestamp"),
                last_pen_dot.get("x"),
                last_pen_dot.get("y"),
                last_pen_dot.get("dot_type"),
            )
            if key != state.last_pen_log_key:
                state.last_pen_log_key = key
                state.last_pen_dot = last_pen_dot
                state.append_sample("pen", {
                    "dot_type": last_pen_dot.get("dot_type"),
                    "x": last_pen_dot.get("x"),
                    "y": last_pen_dot.get("y"),
                    "pressure": last_pen_dot.get("pressure"),
                    "timestamp": last_pen_dot.get("timestamp"),
                    "local_ts_ms": last_pen_dot.get("local_ts_ms"),
                })

        pen_writing = (
            last_pen_dot.get("dot_type") in ("PEN_DOWN", "PEN_MOVE")
            if last_pen_dot else False
        )

        # Chart-Puffer: ein aggregierter Punkt pro Sekunde (Mittelwert des Fensters)
        if state.active:
            acc_mag = (
                sum(state.chart_window_acc_mags) / len(state.chart_window_acc_mags)
                if state.chart_window_acc_mags else 0.0
            )
            gyro_mag = (
                sum(state.chart_window_gyro_mags) / len(state.chart_window_gyro_mags)
                if state.chart_window_gyro_mags else 0.0
            )
            state.chart_buffer.append({
                "t": int(time.time() * 1000),
                "mag": round(acc_mag, 3),  # backward-compat key für ältere Dashboards
                "acc_mag": round(acc_mag, 3),
                "gyro_mag": round(gyro_mag, 3),
                "pen_writing": pen_writing,
            })
            if len(state.chart_buffer) > 60:
                state.chart_buffer = state.chart_buffer[-60:]
        state.chart_window_acc_mags = []
        state.chart_window_gyro_mags = []

        await _broadcast(_status_payload(pen_samples=pen_samples, last_pen_dot=last_pen_dot))

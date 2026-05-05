"""
Globaler Server-State.

SessionState hält den gesamten In-Memory-Zustand des Servers:
aktive Session, WebSocket-Clients, letzte Sensorwerte, Chart-Puffer, etc.

append_event() und append_sample() sind Methoden statt Standalone-Funktionen,
damit alle anderen Module nur `from .state import state` brauchen und kein
Zirkel-Import zwischen state ↔ csv_io entsteht.
"""

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket


@dataclass
class ActiveSession:
    session_id: str
    person_id: str
    description: str
    start_time: str


class SessionState:
    def __init__(self):
        self.active: Optional[ActiveSession] = None
        self.pen_proc = None
        self.pen_log_task: Optional[Any] = None
        self.pen_session_id: Optional[str] = None
        self.watch_sample_count: int = 0
        self.watch_total_sample_count: int = 0
        self.server_start: float = time.time()
        self.ws_clients: set[WebSocket] = set()
        self.ws_client_meta: dict[int, dict[str, Any]] = {}
        self.last_watch_time: float = 0.0
        self.last_watch_status_time: float = 0.0
        self.chart_buffer: list[dict] = []
        self.chart_window_acc_mags: list[float] = []
        self.chart_window_gyro_mags: list[float] = []
        self.event_log: deque[dict[str, Any]] = deque(maxlen=220)
        self.sample_log: deque[dict[str, Any]] = deque(maxlen=140)
        self.last_watch_sample: Optional[dict[str, Any]] = None
        self.last_watch_packet: Optional[dict[str, Any]] = None
        self.watch_config_rate_hz: Optional[float] = None
        self.watch_batch_rate_hz: Optional[float] = None
        self.watch_rate_hz: float = 0.0
        self.watch_sequence_last: Optional[int] = None
        self.watch_sequence_gaps: int = 0
        self.watch_phone_latency_ms: Optional[int] = None
        self.watch_server_latency_ms: Optional[int] = None
        self.watch_clock_skew_ms: Optional[int] = None
        self.last_watch_rate_check: float = time.time()
        self.last_watch_count_for_rate: int = 0
        self.last_pen_dot: Optional[dict[str, Any]] = None
        self.last_pen_log_key: Optional[tuple] = None
        self.pen_rate_hz: float = 0.0
        self.last_pen_rate_check: float = time.time()
        self.last_pen_count_for_rate: int = 0
        self.watch_command: dict[str, Any] = {
            "command": None,
            "ok": None,
            "at": None,
            "detail": "No command sent yet",
        }

    def reset_for_session(self) -> None:
        """Zero out all per-session counters and buffers. Call before setting state.active."""
        self.watch_sample_count = 0
        self.chart_buffer = []
        self.chart_window_acc_mags = []
        self.chart_window_gyro_mags = []
        self.last_watch_sample = None
        self.last_watch_packet = None
        self.watch_sequence_last = None
        self.watch_sequence_gaps = 0
        self.watch_phone_latency_ms = None
        self.watch_server_latency_ms = None
        self.watch_clock_skew_ms = None
        self.last_pen_dot = None
        self.last_pen_log_key = None
        self.sample_log.clear()

    def append_event(self, source: str, level: str, message: str, data: Optional[dict] = None) -> None:
        entry: dict[str, Any] = {
            "ts": int(time.time() * 1000),
            "source": source,
            "level": level,
            "message": message,
        }
        if data:
            entry["data"] = data
        self.event_log.append(entry)

    def append_sample(self, source: str, data: dict[str, Any]) -> None:
        self.sample_log.append({
            "ts": int(time.time() * 1000),
            "source": source,
            "data": data,
        })


state = SessionState()

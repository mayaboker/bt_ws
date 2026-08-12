"""Non-blocking per-cycle CSV recorder for GLIDE control diagnostics."""

from __future__ import annotations

import csv
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from loguru import logger as log


CSV_HEADER = (
    "time_monotonic_ns", "glide_phase", "frame_id", "control_valid",
    "reason", "abort_reason", "dx_norm", "dy_norm",
    "vx_setpoint_m_s", "vx_measured_m_s", "vy_setpoint_m_s",
    "vy_measured_m_s", "altitude_m", "distance_to_target_m",
    "roll_deg", "pitch_deg", "yaw_deg", "throttle_rc",
)


@dataclass(frozen=True)
class GlideDiagnosticSample:
    time_monotonic_ns: int
    glide_phase: str
    frame_id: int | None
    control_valid: bool
    reason: str | None
    abort_reason: str | None
    dx_norm: float | None
    dy_norm: float | None
    vx_setpoint_m_s: float
    vx_measured_m_s: float | None
    vy_setpoint_m_s: float
    vy_measured_m_s: float
    altitude_m: float
    distance_to_target_m: float | None
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    throttle_rc: int

    def row(self) -> tuple[object, ...]:
        return tuple(getattr(self, name) for name in CSV_HEADER)


class NullGlideDiagnosticRecorder:
    def start(self) -> None:
        return

    def record(self, sample: GlideDiagnosticSample) -> None:
        return

    def stop(self, timeout: float | None = 2.0) -> None:
        return


class GlideDiagnosticRecorder:
    def __init__(
        self,
        path: str | Path,
        *,
        flush_interval_s: float = 1.0,
        queue_size: int = 3000,
    ) -> None:
        if flush_interval_s <= 0.0 or queue_size <= 0:
            raise ValueError("recorder flush interval and queue size must be positive")
        self.path = Path(path)
        self.flush_interval_s = float(flush_interval_s)
        self.dropped_samples = 0
        self._queue: queue.Queue[GlideDiagnosticSample] = queue.Queue(queue_size)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._file: TextIO | None = None
        self._writer: csv.writer | None = None
        self._enabled = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not self.path.exists() or self.path.stat().st_size == 0
            self._file = self.path.open("a", encoding="utf-8", newline="")
            self._writer = csv.writer(self._file)
            if write_header:
                self._writer.writerow(CSV_HEADER)
                self._file.flush()
        except OSError as exc:
            log.error("Failed to start GLIDE diagnostic recorder at {}: {}", self.path, exc)
            self._close()
            return
        self._stop_event.clear()
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="glide-diagnostic-recorder"
        )
        self._thread.start()

    def record(self, sample: GlideDiagnosticSample) -> None:
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(sample)
        except queue.Full:
            self.dropped_samples += 1

    def stop(self, timeout: float | None = 2.0) -> None:
        self._enabled = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self.dropped_samples:
            log.warning("GLIDE diagnostic recorder dropped {} sample(s)", self.dropped_samples)

    def _run(self) -> None:
        last_flush = time.monotonic()
        try:
            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    sample = self._queue.get(timeout=0.05)
                except queue.Empty:
                    sample = None
                if sample is not None and self._writer is not None:
                    self._writer.writerow(sample.row())
                now = time.monotonic()
                if self._file is not None and now - last_flush >= self.flush_interval_s:
                    self._file.flush()
                    last_flush = now
        except BaseException as exc:
            log.exception("GLIDE diagnostic recorder failed: {}", exc)
        finally:
            self._close()

    def _close(self) -> None:
        if self._file is not None:
            self._file.flush()
            self._file.close()
        self._file = None
        self._writer = None

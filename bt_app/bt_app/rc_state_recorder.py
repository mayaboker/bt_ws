"""Asynchronous CSV recorder for outgoing RC state and channel snapshots.

``RcStateRecorder`` is intended for flight diagnostics.  ``record`` performs
only validation and a non-blocking queue write; a daemon writer thread writes
rows and flushes them periodically, so the control loop is not delayed by
filesystem I/O.  Each row contains a monotonic timestamp, the
``RobotState`` name, and the eight RC channel values (``ch1`` through
``ch8``).

The recorder owns the file between :meth:`start` and :meth:`stop`.  It creates
the parent directory and writes the CSV header when the file is new or empty.
Samples submitted before ``start`` or after ``stop`` are ignored.  If the
bounded queue is full, or a sample has the wrong channel count, the sample is
dropped and ``dropped_samples`` is incremented.  Use ``NullRcStateRecorder``
when recording is disabled; it has the same lifecycle API and performs no I/O.

Typical usage::

    from bt_app.common import RobotState
    from bt_app.rc_state_recorder import RcStateRecorder

    recorder = RcStateRecorder(
        "logs/rc_state.csv",
        flush_interval_s=0.5,
        queue_size=1000,
    )
    recorder.start()
    try:
        recorder.record(RobotState.GLIDE, [1500, 1500, 1660, 1500,
                                           1500, 1500, 1500, 2000])
    finally:
        recorder.stop()  # drains queued samples before closing the file

The resulting CSV has this shape::

    time_monotonic_ns,state,ch1,ch2,ch3,ch4,ch5,ch6,ch7,ch8
    1234567890,GLIDE,1500,1500,1660,1500,1500,1500,1500,2000
"""

from __future__ import annotations

import csv
import queue
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from loguru import logger as log

from bt_app.common import RobotState


CSV_HEADER = (
    "time_monotonic_ns",
    "state",
    "ch1",
    "ch2",
    "ch3",
    "ch4",
    "ch5",
    "ch6",
    "ch7",
    "ch8",
)
CHANNEL_COUNT = 8


class NullRcStateRecorder:
    def start(self) -> None:
        return

    def record(self, state: RobotState, channels: Sequence[int]) -> None:
        return

    def stop(self, timeout: float | None = 2.0) -> None:
        return


class RcStateRecorder:
    def __init__(
        self,
        path: str | Path,
        *,
        flush_interval_s: float = 1.0,
        queue_size: int = 1000,
    ) -> None:
        self.path = Path(path)
        self.flush_interval_s = flush_interval_s
        self.dropped_samples = 0
        self._queue: queue.Queue[tuple[int, str, tuple[int, ...]]] = queue.Queue(
            maxsize=queue_size
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._file: TextIO | None = None
        self._writer: csv.writer | None = None
        self._enabled = False
        self._last_error: BaseException | None = None

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
            self._last_error = exc
            self._enabled = False
            log.error("Failed to start RC state recorder at {}: {}", self.path, exc)
            self._close_file()
            return

        self._stop_event.clear()
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="rc-state-recorder",
        )
        self._thread.start()

    def record(self, state: RobotState, channels: Sequence[int]) -> None:
        if not self._enabled:
            return
        if len(channels) != CHANNEL_COUNT:
            self.dropped_samples += 1
            return

        state_name = getattr(state, "name", str(state))
        sample = (
            time.monotonic_ns(),
            state_name,
            tuple(int(channel) for channel in channels),
        )
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
            log.warning("RC state recorder dropped {} sample(s)", self.dropped_samples)

    def _run(self) -> None:
        last_flush = time.monotonic()
        try:
            while not self._stop_event.is_set() or not self._queue.empty():
                try:
                    sample = self._queue.get(timeout=0.1)
                except queue.Empty:
                    sample = None

                if sample is not None:
                    self._write_sample(sample)

                now = time.monotonic()
                if now - last_flush >= self.flush_interval_s:
                    self._flush()
                    last_flush = now
            self._flush()
        except BaseException as exc:
            self._last_error = exc
            self._enabled = False
            log.exception("RC state recorder writer failed: {}", exc)
        finally:
            self._close_file()

    def _write_sample(self, sample: tuple[int, str, tuple[int, ...]]) -> None:
        writer = self._writer
        if writer is None:
            return

        timestamp_ns, state_name, channels = sample
        writer.writerow((timestamp_ns, state_name, *channels))

    def _flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def _close_file(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self._writer = None

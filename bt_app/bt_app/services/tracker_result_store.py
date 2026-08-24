"""Thread-safe handoff of raw visual tracker observations."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from bt_msgs import TrackerResultMessage


@dataclass(frozen=True, slots=True)
class TrackerObservation:
    result: TrackerResultMessage
    received_at_s: float


class TrackerResultStore:
    """Retain the newest raw tracker result for the control-loop thread."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: TrackerObservation | None = None

    @property
    def latest_observation(self) -> TrackerObservation | None:
        with self._lock:
            return self._latest

    def process_tracker_result(self, result: TrackerResultMessage) -> None:
        observation = TrackerObservation(result=result, received_at_s=self._clock())
        with self._lock:
            current = self._latest
            if (
                current is not None
                and result.tracker_id == current.result.tracker_id
                and result.frame_id <= current.result.frame_id
            ):
                return
            self._latest = observation

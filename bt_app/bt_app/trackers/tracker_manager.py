from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from bt_app.comm.gst_bridge import VisualDetectionMessage


@dataclass(frozen=True)
class TrackerSnapshot:
    tracker_id: str
    detection: VisualDetectionMessage
    received_at_s: float


class TrackerManager:
    """Keep the most recently received result from any tracker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_result: TrackerSnapshot | None = None

    def update_tracker(
        self,
        tracker_id: str,
        result: VisualDetectionMessage,
        *,
        received_at_s: float | None = None,
    ) -> TrackerSnapshot:
        """Atomically replace the retained result with the newest value."""
        snapshot = TrackerSnapshot(
            tracker_id=tracker_id,
            detection=result,
            received_at_s=(
                time.monotonic() if received_at_s is None else float(received_at_s)
            ),
        )
        with self._lock:
            self._last_result = snapshot
        return snapshot

    def get_result(self) -> TrackerSnapshot | None:
        """Return the latest snapshot without removing it."""
        with self._lock:
            return self._last_result

    def clear(self) -> None:
        """Atomically discard the retained snapshot."""
        with self._lock:
            self._last_result = None

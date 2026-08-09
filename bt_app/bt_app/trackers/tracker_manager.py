from __future__ import annotations

import threading
from typing import Any


TrackerResult = tuple[str, Any]


class TrackerManager:
    """Keep the most recently received result from any tracker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_result: TrackerResult | None = None

    def update_tracker(self, tracker_id: str, result: Any) -> None:
        """Atomically replace the retained result with the newest value."""
        with self._lock:
            self._last_result = (tracker_id, result)

    def get_result(self) -> TrackerResult | None:
        """Return the latest ``(tracker_id, result)`` without removing it."""
        with self._lock:
            return self._last_result

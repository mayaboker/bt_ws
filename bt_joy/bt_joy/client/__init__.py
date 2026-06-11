"""Joystick client-side reading, mapping, and UDP sending."""

from __future__ import annotations

import time


class LogThrottle:
    """Small monotonic-time log throttle keyed by event name."""

    def __init__(self) -> None:
        self._last_log_at: dict[str, float] = {}

    def should_log(self, key: str, interval_s: float) -> bool:
        now = time.monotonic()
        last_log_at = self._last_log_at.get(key)
        if last_log_at is not None and now - last_log_at < interval_s:
            return False

        self._last_log_at[key] = now
        return True

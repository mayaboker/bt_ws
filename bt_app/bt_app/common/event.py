from collections.abc import Callable
from threading import Lock
from typing import Any


class Event:
    """Thread-safe callback event."""

    def __init__(self) -> None:
        self._callbacks: list[Callable[..., None]] = []
        self._lock = Lock()

    def __iadd__(self, callback: Callable[..., None]) -> "Event":
        with self._lock:
            self._callbacks.append(callback)
        return self

    def __isub__(self, callback: Callable[..., None]) -> "Event":
        with self._lock:
            self._callbacks = [cb for cb in self._callbacks if cb != callback]
        return self

    def emit(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            callbacks = tuple(self._callbacks)

        for callback in callbacks:
            callback(*args, **kwargs)

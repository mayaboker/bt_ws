from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

from loguru import logger


K = TypeVar("K")
V = TypeVar("V")


class Event(Generic[K, V]):
    """Small thread-safe callback event for non-Qt model notifications.

    Generic over (name, value) so subscribers receive both parameters.
    """

    def __init__(self) -> None:
        self._subscribers: list[Callable[[K, V], None]] = []
        self._lock = Lock()

    def subscribe(self, callback: Callable[[K, V], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def emit(self, name: K, value: V) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)

        for callback in subscribers:
            try:
                callback(name, value)
            except Exception as exc:
                logger.exception(
                    "Parameter callback {} failed for {}={}: {}",
                    getattr(callback, "__qualname__", repr(callback)),
                    name,
                    value,
                    exc,
                )

from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar


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
            callback(name, value)
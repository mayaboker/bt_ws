from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar


T = TypeVar("T")


class Event(Generic[T]):
    """Small thread-safe callback event for non-Qt model notifications."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[T], None]] = []
        self._lock = Lock()

    def subscribe(self, callback: Callable[[T], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def emit(self, value: T) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)

        for callback in subscribers:
            callback(value)


from .random_data_model import RandomDataModel

__all__ = ["Event", "RandomDataModel"]


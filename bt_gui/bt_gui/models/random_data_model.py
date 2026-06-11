from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock

from . import Event


@dataclass
class RandomDataModel:
    values_changed: Event[tuple[str, str, str]] = field(default_factory=Event)
    _values: tuple[str, str, str] = ("", "", "")
    _lock: Lock = field(default_factory=Lock)

    def set_values(self, values: tuple[str, str, str]) -> None:
        with self._lock:
            self._values = values

        self.values_changed.emit(values)

    def values(self) -> tuple[str, str, str]:
        with self._lock:
            return self._values


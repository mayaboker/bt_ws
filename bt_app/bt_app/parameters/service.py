from __future__ import annotations

from typing import Any

from bt_app.parameters.models import ParameterLimits
from bt_app.parameters.storage import ParameterStorage
from bt_app.parameters.event import Event

class ParameterService:
    def __init__(self, storage: ParameterStorage) -> None:
        self._storage = storage
        self.on_parameter_changed = Event[str, Any]()

    def list(self, full: bool = False) -> list[str] | list[dict[str, Any]]:
        return self._storage.list(full=full)

    def declare(
        self,
        name: str,
        default: Any,
        limits: ParameterLimits | dict[str, Any] | None = None,
        value_type: type | str | None = None,
    ) -> Any:
        return self._storage.declare(name, default, limits, value_type)

    def dump(self) -> str:
        return self._storage.dump_yaml()

    def dump_values(self) -> dict[str, Any]:
        return self._storage.dump()

    def save(self) -> str:
        return self._storage.save()

    def describe(self) -> dict[str, dict[str, Any]]:
        return self._storage.describe()

    def get(self, name: str) -> Any:
        return self._storage.get(name)

    def set(self, name: str, value: Any) -> Any:
        self.on_parameter_changed.emit(name, value)
        return self._storage.set(name, value)

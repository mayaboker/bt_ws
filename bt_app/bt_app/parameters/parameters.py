from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from bt_app.parameters.models import ParameterLimits
from bt_app.parameters.service import ParameterService
from bt_app.parameters.storage import ParameterStorage


class Parameters:
    def __init__(
        self,
        yaml_path: str | Path | None = None,
    ) -> None:
        if yaml_path is None:
            storage = ParameterStorage({})
        else:
            logger.info(f"Loading parameters from {yaml_path}")
            storage = ParameterStorage.from_yaml(yaml_path)

        self.service = ParameterService(storage)
        self.on_parameter_changed = self.service.on_parameter_changed

    def declare(
        self,
        name: str,
        default: Any,
        limits: ParameterLimits | dict[str, Any] | None = None,
        value_type: type | str | None = None,
    ) -> Any:
        return self.service.declare(name, default, limits, value_type)

    def get(self, name: str) -> Any:
        return self.service.get(name)

    def set(self, name: str, value: Any) -> Any:
        return self.service.set(name, value)

    def list(self, full: bool = False) -> list[str] | list[dict[str, Any]]:
        return self.service.list(full=full)

    def dump(self) -> str:
        return self.service.dump()

    def dump_values(self) -> dict[str, Any]:
        return self.service.dump_values()

    def save(self) -> str:
        return self.service.save()

    def describe(self) -> dict[str, dict[str, Any]]:
        return self.service.describe()

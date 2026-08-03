from __future__ import annotations

from pathlib import Path
import os
import tempfile
from threading import RLock
from typing import Any

import yaml

from bt_app.parameters.models import ParameterDefinition, ParameterLimits


class ParameterStorage:
    def __init__(
        self,
        definitions: dict[str, ParameterDefinition],
        source_path: str | Path | None = None,
    ) -> None:
        self._definitions = definitions
        self._source_path = Path(source_path) if source_path is not None else None
        self._lock = RLock()
        self._values = {
            name: definition.default for name, definition in definitions.items()
        }

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ParameterStorage":
        yaml_path = Path(path)
        with yaml_path.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}

        raw_parameters = config.get("parameters", config)
        if not isinstance(raw_parameters, dict):
            raise ValueError("Parameter YAML must contain a mapping")

        definitions = {
            name: ParameterDefinition.from_config(name, definition_config)
            for name, definition_config in raw_parameters.items()
        }
        return cls(definitions, source_path=yaml_path)

    def list(self, full: bool = False) -> list[str] | list[dict[str, Any]]:
        with self._lock:
            names = list(self._definitions)
            if not full:
                return names

            return [
                {
                    "name": name,
                    "type": self._definitions[name].type_name,
                    "limits": self._limits_as_dict(self._definitions[name]),
                }
                for name in names
            ]

    def declare(
        self,
        name: str,
        default: Any,
        limits: ParameterLimits | dict[str, Any] | None = None,
        value_type: type | str | None = None,
    ) -> Any:
        with self._lock:
            if name in self._definitions:
                raise ValueError(f"Parameter already declared: {name}")

            if isinstance(limits, ParameterLimits):
                parameter_limits = limits
            else:
                parameter_limits = ParameterLimits.from_config(limits)

            self._definitions[name] = ParameterDefinition.from_values(
                name=name,
                default=default,
                value_type=value_type,
                limits=parameter_limits,
            )
            self._values[name] = default
            return default

    def dump(self) -> dict[str, Any]:
        with self._lock:
            return {name: self._values[name] for name in self._definitions}

    def dump_yaml(self) -> str:
        return yaml.safe_dump(self.dump(), sort_keys=False)

    def save(self) -> str:
        if self._source_path is None:
            raise RuntimeError("No parameter YAML source file; no file saved")

        with self._lock:
            config = {
                "parameters": {
                    name: self._definition_as_config(name, self._definitions[name])
                    for name in self._definitions
                }
            }
        yaml_text = yaml.safe_dump(config, sort_keys=False)
        self._write_text_atomic(self._source_path, yaml_text)
        return f"Saved parameters to {self._source_path}"

    def describe(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                name: {
                    "default": definition.default,
                    "type": definition.type_name,
                    "value": self._values[name],
                    "limits": self._limits_as_dict(definition),
                }
                for name, definition in self._definitions.items()
            }

    def snapshot(self) -> tuple[tuple[str, str, Any], ...]:
        with self._lock:
            return tuple(
                (name, definition.type_name, self._values[name])
                for name, definition in self._definitions.items()
            )

    def get(self, name: str) -> Any:
        with self._lock:
            self._require_defined(name)
            return self._values[name]

    def set(self, name: str, value: Any) -> Any:
        with self._lock:
            self._require_defined(name)
            self._definitions[name].validate(value)
            self._values[name] = value
            return value

    @staticmethod
    def _write_text_atomic(path: Path, text: str) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            os.fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _require_defined(self, name: str) -> None:
        if name not in self._definitions:
            raise KeyError(f"Unknown parameter: {name}")

    def _limits_as_dict(self, definition: ParameterDefinition) -> dict[str, Any]:
        return {
            "min": definition.limits.minimum,
            "max": definition.limits.maximum,
            "options": list(definition.limits.options)
            if definition.limits.options is not None
            else None,
        }

    def _definition_as_config(
        self,
        name: str,
        definition: ParameterDefinition,
    ) -> dict[str, Any]:
        config = {
            "type": definition.type_name,
            "default": self._values[name],
        }

        limits = {
            key: value
            for key, value in self._limits_as_dict(definition).items()
            if value is not None
        }
        if limits:
            config["limits"] = limits

        return config

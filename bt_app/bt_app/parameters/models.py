from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_PARAMETER_TYPES = {
    "bool": bool,
    "float": float,
    "int": int,
    "str": str,
}


@dataclass(frozen=True)
class ParameterLimits:
    minimum: int | float | None = None
    maximum: int | float | None = None
    options: tuple[Any, ...] | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "ParameterLimits":
        if not config:
            return cls()

        options = config.get("options")
        if options is not None and not isinstance(options, list):
            raise ValueError("limits.options must be a list")

        return cls(
            minimum=config.get("min"),
            maximum=config.get("max"),
            options=tuple(options) if options is not None else None,
        )

    def validate(self, name: str, value: Any) -> None:
        if self.options is not None and value not in self.options:
            raise ValueError(f"{name} must be one of {list(self.options)}")

        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{name} must be >= {self.minimum}")

        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{name} must be <= {self.maximum}")


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    default: Any
    value_type: type
    limits: ParameterLimits

    @classmethod
    def from_config(cls, name: str, config: dict[str, Any]) -> "ParameterDefinition":
        if "default" not in config:
            raise ValueError(f"Parameter {name} is missing a default value")

        value_type = cls._resolve_type(name, config.get("type"), config["default"])
        definition = cls(
            name=name,
            default=config["default"],
            value_type=value_type,
            limits=ParameterLimits.from_config(config.get("limits")),
        )
        definition.validate(definition.default)
        return definition

    @classmethod
    def from_values(
        cls,
        name: str,
        default: Any,
        limits: ParameterLimits,
        value_type: type | str | None = None,
    ) -> "ParameterDefinition":
        resolved_type = cls._resolve_type(name, value_type, default)
        definition = cls(
            name=name,
            default=default,
            value_type=resolved_type,
            limits=limits,
        )
        definition.validate(default)
        return definition

    @staticmethod
    def _resolve_type(name: str, configured_type: type | str | None, default: Any) -> type:
        if isinstance(configured_type, type):
            return configured_type

        if isinstance(configured_type, str):
            try:
                return SUPPORTED_PARAMETER_TYPES[configured_type]
            except KeyError as exc:
                supported = ", ".join(sorted(SUPPORTED_PARAMETER_TYPES))
                raise ValueError(
                    f"{name} has unsupported type {configured_type!r}. "
                    f"Supported types: {supported}"
                ) from exc

        return type(default)

    def validate(self, value: Any) -> None:
        if not self._matches_type(value):
            raise TypeError(
                f"{self.name} must be {self.type_name}, got {type(value).__name__}"
            )

        self.limits.validate(self.name, value)

    def _matches_type(self, value: Any) -> bool:
        if self.value_type is float:
            return isinstance(value, (float, int)) and not isinstance(value, bool)

        if self.value_type is int:
            return isinstance(value, int) and not isinstance(value, bool)

        return isinstance(value, self.value_type)

    @property
    def type_name(self) -> str:
        for name, value_type in SUPPORTED_PARAMETER_TYPES.items():
            if self.value_type is value_type:
                return name
        return self.value_type.__name__

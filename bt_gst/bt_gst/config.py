from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from loguru import logger
import yaml

config_logger = logger.bind(component="bt_gst.config")


class ConfigError(ValueError):
    """Raised when an app config cannot be loaded or validated."""


@dataclass(frozen=True)
class FileSourceConfig:
    path: Path
    type: str = "file"


@dataclass(frozen=True)
class CameraSourceConfig:
    device: str
    type: str = "camera"


@dataclass(frozen=True)
class SimulationSourceConfig:
    topic: str
    type: str = "simulation"


SourceConfig: TypeAlias = FileSourceConfig | CameraSourceConfig | SimulationSourceConfig


@dataclass(frozen=True)
class AppConfig:
    source: SourceConfig | None = None


def load_config(path: Path) -> AppConfig:
    config_logger.trace("loading config path={}", path)
    try:
        raw_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        config_logger.debug("config read failed path={} error={}", path, exc)
        raise ConfigError(f"config file could not be read: {path}") from exc
    except yaml.YAMLError as exc:
        config_logger.debug("config YAML parse failed path={} error={}", path, exc)
        raise ConfigError(f"config file is not valid YAML: {path}") from exc

    if raw_config is None:
        config_logger.trace("config is empty path={}", path)
        return AppConfig()
    if not isinstance(raw_config, dict):
        config_logger.debug("config root is not mapping type={}", type(raw_config).__name__)
        raise ConfigError("config root must be a mapping")

    return app_config_from_mapping(raw_config)


def app_config_from_mapping(raw_config: dict[str, Any]) -> AppConfig:
    config_logger.trace("mapping app config keys={}", sorted(raw_config.keys()))
    raw_source = raw_config.get("source")
    if raw_source is None:
        return AppConfig()
    if not isinstance(raw_source, dict):
        config_logger.debug("config source is not mapping type={}", type(raw_source).__name__)
        raise ConfigError("config source must be a mapping")
    return AppConfig(source=source_config_from_mapping(raw_source))


def source_config_from_mapping(raw_source: dict[str, Any]) -> SourceConfig:
    source_type = raw_source.get("type")
    config_logger.trace("mapping source config source_type={}", source_type)
    if not isinstance(source_type, str) or not source_type:
        config_logger.debug("config source.type missing or invalid value={!r}", source_type)
        raise ConfigError("config source.type is required")

    if source_type == "file":
        return FileSourceConfig(path=_required_path(raw_source, "path", source_type))
    if source_type == "camera":
        return CameraSourceConfig(
            device=_required_string(raw_source, "device", source_type)
        )
    if source_type == "simulation":
        return SimulationSourceConfig(
            topic=_required_string(raw_source, "topic", source_type)
        )

    config_logger.debug("unsupported source type source_type={}", source_type)
    raise ConfigError(f"unsupported source type: {source_type}")


def merge_config(base: AppConfig | None, overrides: AppConfig) -> AppConfig:
    config_logger.trace("merging config base={!r} overrides={!r}", base, overrides)
    if base is None:
        return overrides
    if overrides.source is not None:
        return AppConfig(source=overrides.source)
    return base


def validate_config(config: AppConfig) -> AppConfig:
    config_logger.trace("validating config config={!r}", config)
    if config.source is None:
        config_logger.debug("config validation failed reason=missing-source")
        raise ConfigError("source config is required")
    return config


def _required_string(raw_source: dict[str, Any], field: str, source_type: str) -> str:
    value = raw_source.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"source.{field} is required for {source_type} source")
    return value


def _required_path(raw_source: dict[str, Any], field: str, source_type: str) -> Path:
    return Path(_required_string(raw_source, field, source_type))

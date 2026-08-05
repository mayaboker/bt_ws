from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeAlias

from loguru import logger
import yaml

config_logger = logger.bind(component="bt_gst.config")


class ConfigError(ValueError):
    """Raised when an app config cannot be loaded or validated."""


DEFAULT_FILE_RATE = 20
DEFAULT_SIMULATION_RATE = 30


@dataclass(frozen=True)
class FileSourceConfig:
    path: Path
    rate: int = DEFAULT_FILE_RATE
    type: str = "file"

    @property
    def framerate(self) -> int:
        return self.rate


@dataclass(frozen=True)
class CameraSourceConfig:
    device: str
    type: str = "camera"


@dataclass(frozen=True)
class SimulationSourceConfig:
    topic: str
    rate: int = DEFAULT_SIMULATION_RATE
    type: str = "simulation"


SourceConfig: TypeAlias = FileSourceConfig | CameraSourceConfig | SimulationSourceConfig


@dataclass(frozen=True)
class FileSourceConfigOverrides:
    path: Path | None = None
    rate: int | None = None
    type: str = "file"


@dataclass(frozen=True)
class CameraSourceConfigOverrides:
    device: str | None = None
    type: str = "camera"


@dataclass(frozen=True)
class SimulationSourceConfigOverrides:
    topic: str | None = None
    rate: int | None = None
    type: str = "simulation"


SourceConfigOverride: TypeAlias = (
    FileSourceConfigOverrides | CameraSourceConfigOverrides | SimulationSourceConfigOverrides
)
SourceOverride: TypeAlias = SourceConfig | SourceConfigOverride

DEFAULT_VIDEO_LOCAL = True
DEFAULT_CODEC = "h264"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000
DEFAULT_MTU = 1200
SUPPORTED_CODECS = frozenset({DEFAULT_CODEC})


@dataclass(frozen=True)
class DetectorConfig:
    enabled: bool = False
    low_h: int = 0
    low_s: int = 100
    low_v: int = 100
    high_h: int = 10
    high_s: int = 255
    high_v: int = 255


@dataclass(frozen=True)
class DetectorConfigOverrides:
    enabled: bool | None = None
    low_h: int | None = None
    low_s: int | None = None
    low_v: int | None = None
    high_h: int | None = None
    high_s: int | None = None
    high_v: int | None = None


@dataclass(frozen=True)
class AppConfig:
    source: SourceConfig | None = None
    detector: DetectorConfig = DetectorConfig()
    video_local: bool = DEFAULT_VIDEO_LOCAL
    codec: str = DEFAULT_CODEC
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    mtu: int = DEFAULT_MTU


@dataclass(frozen=True)
class AppConfigOverrides:
    source: SourceOverride | None = None
    detector: DetectorConfigOverrides | None = None
    video_local: bool | None = None
    codec: str | None = None
    host: str | None = None
    port: int | None = None
    mtu: int | None = None


def load_config(path: Path) -> AppConfig:
    return resolve_config(AppConfig(), load_config_overrides(path))


def load_config_overrides(path: Path) -> AppConfigOverrides:
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
        return AppConfigOverrides()
    if not isinstance(raw_config, dict):
        config_logger.debug("config root is not mapping type={}", type(raw_config).__name__)
        raise ConfigError("config root must be a mapping")

    return app_config_overrides_from_mapping(raw_config)


def app_config_from_mapping(raw_config: dict[str, Any]) -> AppConfig:
    return resolve_config(AppConfig(), app_config_overrides_from_mapping(raw_config))


def app_config_overrides_from_mapping(raw_config: dict[str, Any]) -> AppConfigOverrides:
    config_logger.trace("mapping app config keys={}", sorted(raw_config.keys()))
    raw_source = raw_config.get("source")
    source = None
    if raw_source is None:
        source = None
    elif not isinstance(raw_source, dict):
        config_logger.debug("config source is not mapping type={}", type(raw_source).__name__)
        raise ConfigError("config source must be a mapping")
    else:
        source = source_config_from_mapping(raw_source)

    raw_detector = raw_config.get("detector")
    detector = None
    if raw_detector is not None:
        if not isinstance(raw_detector, dict):
            raise ConfigError("detector must be a mapping")
        detector = DetectorConfigOverrides(
            enabled=_optional_bool(raw_detector, "enabled"),
            low_h=_optional_int(raw_detector, "low_h"),
            low_s=_optional_int(raw_detector, "low_s"),
            low_v=_optional_int(raw_detector, "low_v"),
            high_h=_optional_int(raw_detector, "high_h"),
            high_s=_optional_int(raw_detector, "high_s"),
            high_v=_optional_int(raw_detector, "high_v"),
        )

    return AppConfigOverrides(
        source=source,
        detector=detector,
        video_local=_optional_bool(raw_config, "video_local"),
        codec=_optional_string(raw_config, "codec"),
        host=_optional_string(raw_config, "host"),
        port=_optional_int(raw_config, "port"),
        mtu=_optional_int(raw_config, "mtu"),
    )


def source_config_from_mapping(raw_source: dict[str, Any]) -> SourceConfig:
    source_type = raw_source.get("type")
    config_logger.trace("mapping source config source_type={}", source_type)
    if not isinstance(source_type, str) or not source_type:
        config_logger.debug("config source.type missing or invalid value={!r}", source_type)
        raise ConfigError("config source.type is required")

    if source_type == "file":
        rate = _optional_file_rate(raw_source)
        if rate <= 0:
            raise ConfigError("source.rate must be greater than 0")
        return FileSourceConfig(
            path=_required_path(raw_source, "path", source_type),
            rate=rate,
        )
    if source_type == "camera":
        return CameraSourceConfig(
            device=_required_string(raw_source, "device", source_type)
        )
    if source_type == "simulation":
        rate = _optional_simulation_rate(raw_source)
        if rate <= 0:
            raise ConfigError("source.rate must be greater than 0")
        return SimulationSourceConfig(
            topic=_required_string(raw_source, "topic", source_type),
            rate=rate,
        )

    config_logger.debug("unsupported source type source_type={}", source_type)
    raise ConfigError(f"unsupported source type: {source_type}")


def resolve_config(
    defaults: AppConfig | None = None,
    *overrides: AppConfigOverrides,
) -> AppConfig:
    config = defaults if defaults is not None else AppConfig()
    config_logger.trace("resolving config defaults={!r} overrides={!r}", config, overrides)
    for override in overrides:
        config = AppConfig(
            source=_resolve_source_config(config.source, override.source),
            detector=_resolve_detector_config(config.detector, override.detector),
            video_local=(
                override.video_local
                if override.video_local is not None
                else config.video_local
            ),
            codec=override.codec if override.codec is not None else config.codec,
            host=override.host if override.host is not None else config.host,
            port=override.port if override.port is not None else config.port,
            mtu=override.mtu if override.mtu is not None else config.mtu,
        )
    return config


def _resolve_detector_config(
    current: DetectorConfig,
    override: DetectorConfigOverrides | None,
) -> DetectorConfig:
    if override is None:
        return current
    return DetectorConfig(
        enabled=override.enabled if override.enabled is not None else current.enabled,
        low_h=override.low_h if override.low_h is not None else current.low_h,
        low_s=override.low_s if override.low_s is not None else current.low_s,
        low_v=override.low_v if override.low_v is not None else current.low_v,
        high_h=override.high_h if override.high_h is not None else current.high_h,
        high_s=override.high_s if override.high_s is not None else current.high_s,
        high_v=override.high_v if override.high_v is not None else current.high_v,
    )


def merge_config(
    base: AppConfig | None,
    overrides: AppConfigOverrides | AppConfig,
) -> AppConfig:
    config_logger.trace("merging config base={!r} overrides={!r}", base, overrides)
    if isinstance(overrides, AppConfig):
        overrides = AppConfigOverrides(
            source=overrides.source,
            detector=DetectorConfigOverrides(
                enabled=overrides.detector.enabled,
                low_h=overrides.detector.low_h,
                low_s=overrides.detector.low_s,
                low_v=overrides.detector.low_v,
                high_h=overrides.detector.high_h,
                high_s=overrides.detector.high_s,
                high_v=overrides.detector.high_v,
            ),
        )
    return resolve_config(base or AppConfig(), overrides)


def _resolve_source_config(
    current: SourceConfig | None,
    override: SourceOverride | None,
) -> SourceConfig | None:
    if override is None:
        return current
    if isinstance(override, SourceConfig):
        return override
    if isinstance(override, FileSourceConfigOverrides):
        path = override.path
        rate = override.rate
        if isinstance(current, FileSourceConfig):
            path = path if path is not None else current.path
            rate = rate if rate is not None else current.rate
        if path is None:
            return current
        return FileSourceConfig(
            path=path,
            rate=rate if rate is not None else DEFAULT_FILE_RATE,
        )
    if isinstance(override, CameraSourceConfigOverrides):
        device = override.device
        if isinstance(current, CameraSourceConfig):
            device = device if device is not None else current.device
        if device is None:
            return current
        return CameraSourceConfig(device=device)
    if isinstance(override, SimulationSourceConfigOverrides):
        topic = override.topic
        rate = override.rate
        if isinstance(current, SimulationSourceConfig):
            topic = topic if topic is not None else current.topic
            rate = rate if rate is not None else current.rate
        if topic is None:
            return current
        return SimulationSourceConfig(
            topic=topic,
            rate=rate if rate is not None else DEFAULT_SIMULATION_RATE,
        )
    return override


def validate_config(config: AppConfig) -> AppConfig:
    config_logger.trace("validating config config={!r}", config)
    if config.source is None:
        config_logger.debug("config validation failed reason=missing-source")
        raise ConfigError("source config is required")
    if isinstance(config.source, FileSourceConfig):
        if isinstance(config.source.rate, bool) or not isinstance(
            config.source.rate,
            int,
        ):
            raise ConfigError("source.rate must be an int")
        if config.source.rate <= 0:
            raise ConfigError("source.rate must be greater than 0")
    if isinstance(config.source, SimulationSourceConfig):
        if isinstance(config.source.rate, bool) or not isinstance(
            config.source.rate,
            int,
        ):
            raise ConfigError("source.rate must be an int")
        if config.source.rate <= 0:
            raise ConfigError("source.rate must be greater than 0")
    if config.codec not in SUPPORTED_CODECS:
        raise ConfigError(f"unsupported codec: {config.codec}")
    if isinstance(config.port, bool) or not isinstance(config.port, int):
        raise ConfigError("port must be an int")
    if not 1 <= config.port <= 65535:
        raise ConfigError("port must be between 1 and 65535")
    if isinstance(config.mtu, bool) or not isinstance(config.mtu, int):
        raise ConfigError("mtu must be an int")
    if config.mtu <= 0:
        raise ConfigError("mtu must be greater than 0")
    _validate_detector_config(config.detector)
    return config


def _validate_detector_config(detector: DetectorConfig) -> None:
    if not isinstance(detector.enabled, bool):
        raise ConfigError("detector.enabled must be a bool")
    limits = {
        "low_h": 179,
        "high_h": 179,
        "low_s": 255,
        "high_s": 255,
        "low_v": 255,
        "high_v": 255,
    }
    for field, maximum in limits.items():
        value = getattr(detector, field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"detector.{field} must be an int")
        if not 0 <= value <= maximum:
            raise ConfigError(f"detector.{field} must be between 0 and {maximum}")
    for low, high in (("low_h", "high_h"), ("low_s", "high_s"), ("low_v", "high_v")):
        if getattr(detector, low) > getattr(detector, high):
            raise ConfigError(f"detector.{low} must not exceed detector.{high}")


def _required_string(raw_source: dict[str, Any], field: str, source_type: str) -> str:
    value = raw_source.get(field)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"source.{field} is required for {source_type} source")
    return value


def _required_path(raw_source: dict[str, Any], field: str, source_type: str) -> Path:
    return Path(_required_string(raw_source, field, source_type))


def _optional_bool(raw_config: dict[str, Any], field: str) -> bool | None:
    if field not in raw_config:
        return None
    value = raw_config[field]
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be a bool")
    return value


def _optional_string(raw_config: dict[str, Any], field: str) -> str | None:
    if field not in raw_config:
        return None
    value = raw_config[field]
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _optional_int(raw_config: dict[str, Any], field: str) -> int | None:
    if field not in raw_config:
        return None
    value = raw_config[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field} must be an int")
    return value


def _optional_file_rate(raw_source: dict[str, Any]) -> int:
    if "rate" in raw_source:
        rate = _optional_int(raw_source, "rate")
        if rate is None:
            raise ConfigError("source.rate must be an int")
        return rate
    if "framerate" in raw_source:
        rate = _optional_int(raw_source, "framerate")
        if rate is None:
            raise ConfigError("source.framerate must be an int")
        return rate
    return DEFAULT_FILE_RATE


def _optional_simulation_rate(raw_source: dict[str, Any]) -> int:
    if "rate" in raw_source:
        rate = _optional_int(raw_source, "rate")
        if rate is None:
            raise ConfigError("source.rate must be an int")
        return rate
    if "framerate" in raw_source:
        rate = _optional_int(raw_source, "framerate")
        if rate is None:
            raise ConfigError("source.framerate must be an int")
        return rate
    return DEFAULT_SIMULATION_RATE

import shlex
from pathlib import Path

from loguru import logger

from bt_gst.config import (
    AppConfig,
    CameraSourceConfig,
    ConfigError,
    FileSourceConfig,
    SimulationSourceConfig,
    SourceConfig,
    validate_config,
)

pipeline_builder_logger = logger.bind(component="bt_gst.pipeline_builder")


class PipelineBuildError(RuntimeError):
    """Raised when a GStreamer pipeline cannot be built."""


def build_pipeline_description(config: AppConfig) -> str:
    source = validate_config(config).source
    pipeline_builder_logger.trace("building pipeline source={!r}", source)
    return build_source_pipeline_description(source)


def build_source_pipeline_description(source: SourceConfig) -> str:
    if isinstance(source, FileSourceConfig):
        return (
            f"filesrc location={_quote_path(source.path)} ! "
            "decodebin ! videoconvert ! autovideosink"
        )
    if isinstance(source, CameraSourceConfig):
        return (
            f"v4l2src device={shlex.quote(source.device)} ! "
            "videoconvert ! autovideosink"
        )
    if isinstance(source, SimulationSourceConfig):
        raise PipelineBuildError("simulation source pipeline is not implemented yet")
    raise ConfigError("source config is required")


def _quote_path(path: Path) -> str:
    return shlex.quote(str(path))

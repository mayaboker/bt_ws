import shlex
import sys
from pathlib import Path
from typing import Sequence

from loguru import logger

from bt_gst import __version__
from bt_gst.cli import RunCommand, ShowCommand, VersionCommand, parse_args
from bt_gst.config import (
    AppConfig,
    CameraSourceConfig,
    ConfigError,
    FileSourceConfig,
    SimulationSourceConfig,
    SourceConfig,
    load_config,
    merge_config,
    validate_config,
)

app_logger = logger.bind(component="bt_gst.app")


class AppError(RuntimeError):
    """Raised for user-facing application runtime errors."""


def main(argv: Sequence[str] | None = None) -> int:
    command = parse_args(argv)
    app_logger.trace("parsed command command={!r}", command)
    if isinstance(command, int):
        return command
    if isinstance(command, VersionCommand):
        print(__version__)
        return 0

    try:
        if isinstance(command, ShowCommand):
            config = resolve_command_config(command.config_path, command.overrides)
            print(build_pipeline_description(config.source))
            return 0
        if isinstance(command, RunCommand):
            config = resolve_command_config(command.config_path, command.overrides)
            run_config(config)
            return 0
    except (AppError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    raise RuntimeError(f"unsupported command: {command!r}")


def resolve_command_config(
    config_path: Path | None,
    overrides: AppConfig,
) -> AppConfig:
    app_logger.trace(
        "resolving command config config_path={} overrides={!r}",
        config_path,
        overrides,
    )
    base = load_config(config_path) if config_path is not None else None
    return validate_config(merge_config(base, overrides))


def run_config(config: AppConfig) -> None:
    source = validate_config(config).source
    app_logger.trace("run requested source={!r}", source)
    raise AppError(
        f"run is not implemented yet for {source.type} source; use 'show' to inspect the pipeline"
    )


def build_pipeline_description(source: SourceConfig | None) -> str:
    if isinstance(source, FileSourceConfig):
        return (
            f"filesrc location={_gst_quote_path(source.path)} ! "
            "decodebin ! videoconvert ! autovideosink"
        )
    if isinstance(source, CameraSourceConfig):
        return (
            f"v4l2src device={shlex.quote(source.device)} ! "
            "videoconvert ! autovideosink"
        )
    if isinstance(source, SimulationSourceConfig):
        return (
            f"simulation-source topic={shlex.quote(source.topic)} ! "
            "videoconvert ! autovideosink"
        )
    raise ConfigError("source config is required")


def _gst_quote_path(path: Path) -> str:
    return shlex.quote(str(path))


if __name__ == "__main__":
    raise SystemExit(main())

import sys
from pathlib import Path
from typing import Sequence

from loguru import logger

from bt_gst import __version__
from bt_gst.cli import RunCommand, ShowCommand, VersionCommand, parse_args
from bt_gst.config import (
    AppConfig,
    AppConfigOverrides,
    ConfigError,
    load_config_overrides,
    resolve_config,
    validate_config,
)
from bt_gst.pipeline_builder import PipelineBuildError, build_pipeline_description
from bt_gst.pipeline_runner import PipelineRunError, run_pipeline

app_logger = logger.bind(component="bt_gst.app")


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
            print(build_pipeline_description(config))
            return 0
        if isinstance(command, RunCommand):
            config = resolve_command_config(command.config_path, command.overrides)
            return run_config(config)
    except (ConfigError, PipelineBuildError, PipelineRunError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    raise RuntimeError(f"unsupported command: {command!r}")


def resolve_command_config(
    config_path: Path | None,
    overrides: AppConfigOverrides,
) -> AppConfig:
    app_logger.trace(
        "resolving command config config_path={} overrides={!r}",
        config_path,
        overrides,
    )
    yaml_overrides = (
        load_config_overrides(config_path)
        if config_path is not None
        else AppConfigOverrides()
    )
    return validate_config(resolve_config(AppConfig(), yaml_overrides, overrides))


def run_config(config: AppConfig) -> int:
    app_logger.trace("run requested config={!r}", config)
    return run_pipeline(config)


if __name__ == "__main__":
    raise SystemExit(main())

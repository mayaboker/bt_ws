import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import click
from loguru import logger

from bt_gst.config import (
    AppConfigOverrides,
    CameraSourceConfigOverrides,
    FileSourceConfigOverrides,
    SimulationSourceConfigOverrides,
)

cli_logger = logger.bind(component="bt_gst.cli")
LOG_LEVELS = ("TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass(frozen=True)
class VersionCommand:
    pass


@dataclass(frozen=True)
class ShowCommand:
    config_path: Path | None
    overrides: AppConfigOverrides


@dataclass(frozen=True)
class RunCommand:
    config_path: Path | None
    overrides: AppConfigOverrides


Command: TypeAlias = VersionCommand | ShowCommand | RunCommand | int


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Minimum Loguru log level.",
)
def _cli(log_level: str) -> None:
    """BT GStreamer command line utilities."""
    configure_logging(log_level)


def configure_logging(log_level: str) -> None:
    level = log_level.upper()
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | {name} | <level>{message}</level>",
    )
    cli_logger.debug("configured logging level={}", level)


@_cli.command()
def version() -> VersionCommand:
    """Print the bt-gst package version."""
    return VersionCommand()


def _source_options(command: object) -> object:
    command = click.option(
        "--path",
        "file_path",
        type=click.Path(dir_okay=False, path_type=Path),
        help="File source path.",
    )(command)
    command = click.option("--device", help="Camera device path.")(command)
    command = click.option("--topic", help="Simulation source topic.")(command)
    command = click.option(
        "-s",
        "--source",
        type=click.Choice(("simulation", "camera", "file")),
        help="Source type.",
    )(command)
    command = click.option(
        "-c",
        "--config",
        "config_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="YAML config path.",
    )(command)
    return command


def _build_cli_overrides(
    *,
    source: str | None,
    topic: str | None,
    device: str | None,
    file_path: Path | None,
) -> AppConfigOverrides:
    cli_logger.trace(
        "building CLI overrides source={} topic={} device={} file_path={}",
        source,
        topic,
        device,
        file_path,
    )
    if source is None:
        if topic is not None or device is not None or file_path is not None:
            cli_logger.debug("source options provided without source type")
            raise click.ClickException(
                "-s/--source is required when source options are provided"
            )
        return AppConfigOverrides()

    if source == "simulation":
        if topic is None:
            cli_logger.debug("simulation source missing topic")
            raise click.ClickException("--topic is required for simulation source")
        _reject_unused_source_options(source, device=device, file_path=file_path)
        return AppConfigOverrides(source=SimulationSourceConfigOverrides(topic=topic))

    if source == "camera":
        if device is None:
            cli_logger.debug("camera source missing device")
            raise click.ClickException("--device is required for camera source")
        _reject_unused_source_options(source, topic=topic, file_path=file_path)
        return AppConfigOverrides(source=CameraSourceConfigOverrides(device=device))

    if source == "file":
        if file_path is None:
            cli_logger.debug("file source missing path")
            raise click.ClickException("--path is required for file source")
        _reject_unused_source_options(source, topic=topic, device=device)
        return AppConfigOverrides(source=FileSourceConfigOverrides(path=file_path))

    raise click.ClickException(f"unsupported source type: {source}")


def _reject_unused_source_options(
    source: str,
    *,
    topic: str | None = None,
    device: str | None = None,
    file_path: Path | None = None,
) -> None:
    unused_options = []
    if topic is not None:
        unused_options.append("--topic")
    if device is not None:
        unused_options.append("--device")
    if file_path is not None:
        unused_options.append("--path")
    if unused_options:
        options = ", ".join(unused_options)
        cli_logger.debug("unused source options source={} options={}", source, options)
        raise click.ClickException(f"{options} cannot be used with {source} source")


@_cli.command()
@_source_options
def show(
    config_path: Path | None,
    source: str | None,
    topic: str | None,
    device: str | None,
    file_path: Path | None,
) -> ShowCommand:
    """Print the resolved GStreamer pipeline."""
    return ShowCommand(
        config_path=config_path,
        overrides=_build_cli_overrides(
            source=source,
            topic=topic,
            device=device,
            file_path=file_path,
        ),
    )


@_cli.command()
@_source_options
def run(
    config_path: Path | None,
    source: str | None,
    topic: str | None,
    device: str | None,
    file_path: Path | None,
) -> RunCommand:
    """Run the resolved GStreamer pipeline."""
    return RunCommand(
        config_path=config_path,
        overrides=_build_cli_overrides(
            source=source,
            topic=topic,
            device=device,
            file_path=file_path,
        ),
    )


def parse_args(args: Sequence[str] | None = None) -> Command:
    try:
        command = _cli.main(
            args=list(args) if args is not None else None,
            standalone_mode=False,
        )
        cli_logger.trace("parsed CLI command command={!r}", command)
        return command
    except click.ClickException as exc:
        cli_logger.debug("CLI parse failed error={}", exc)
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:
        cli_logger.trace("CLI exited exit_code={}", exc.exit_code)
        return exc.exit_code
    except click.Abort:
        cli_logger.debug("CLI aborted")
        click.echo("Aborted!", err=True)
        return 1

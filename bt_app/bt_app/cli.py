"""Command-line parser for the BT application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import click

from bt_app.errors import AppExitCode


LOG_LEVELS = (
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
)


class CommandName:
    VERSION = "version"
    ALIAS = "alias"
    DUMP_CONFIG = "dump_config"
    RUN = "run"


@dataclass(frozen=True)
class CliOptions:
    command: str
    config_path: Path | None = None
    log_level: str | None = None


class CliParseExit(Exception):
    def __init__(self, exit_code: int = AppExitCode.SUCCESS) -> None:
        super().__init__(exit_code)
        self.exit_code = exit_code


class CliParseError(Exception):
    def __init__(
        self,
        message: str,
        exit_code: int = AppExitCode.CLI_USAGE_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    help="Set diagnostic log verbosity.",
)
@click.pass_context
def _cli(ctx: click.Context, log_level: str | None) -> None:
    """BT application command group."""

    ctx.obj = {"log_level": _normalize_log_level(log_level)}


@_cli.command(CommandName.VERSION)
@click.pass_context
def version_command(ctx: click.Context) -> CliOptions:
    """Print the installed package version."""

    return _make_options(ctx, command=CommandName.VERSION)


@_cli.command(CommandName.ALIAS)
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to vehicle YAML configuration.",
)
@click.pass_context
def alias_command(ctx: click.Context, config_path: Path | None) -> CliOptions:
    """Print a Bash alias for running the BT application."""

    return _make_options(ctx, command=CommandName.ALIAS, config_path=config_path)


@_cli.command(CommandName.DUMP_CONFIG)
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to vehicle YAML configuration. Uses the packaged default when omitted.",
)
@click.pass_context
def dump_config_command(ctx: click.Context, config_path: Path | None) -> CliOptions:
    """Print the effective vehicle YAML configuration."""

    return _make_options(ctx, command=CommandName.DUMP_CONFIG, config_path=config_path)


@_cli.command(CommandName.RUN)
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to vehicle YAML configuration. Uses the packaged default when omitted.",
)
@click.pass_context
def run_command(ctx: click.Context, config_path: Path | None) -> CliOptions:
    """Run the BT application."""

    return _make_options(ctx, command=CommandName.RUN, config_path=config_path)


def _make_options(ctx: click.Context, **kwargs: object) -> CliOptions:
    return CliOptions(log_level=_context_log_level(ctx), **kwargs)


def _context_log_level(ctx: click.Context) -> str | None:
    if not isinstance(ctx.obj, dict):
        return None
    value = ctx.obj.get("log_level")
    return None if value is None else str(value)


def _normalize_log_level(log_level: str | None) -> str | None:
    return None if log_level is None else log_level.upper()


def parse_cli_args(args: Sequence[str] | None = None) -> CliOptions:
    """Parse command-line arguments into a `CliOptions` value."""

    try:
        result = _cli.main(args=args, prog_name="bt-app", standalone_mode=False)
    except click.exceptions.Exit as exc:
        raise CliParseExit(exc.exit_code) from exc
    except click.ClickException as exc:
        raise CliParseError(str(exc), exc.exit_code) from exc
    if result is None or result == 0:
        raise CliParseExit(0)
    if not isinstance(result, CliOptions):
        raise CliParseError("failed to parse command")
    return result

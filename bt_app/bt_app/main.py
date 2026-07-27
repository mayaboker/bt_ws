"""Application entrypoint and command dispatcher for bt-app."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import MISSING, asdict, fields
from importlib import metadata
import logging
from pathlib import Path
import shlex
import sys

import yaml

try:
    from loguru import logger
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

from bt_app.cli import CliOptions, CliParseError, CliParseExit, CommandName, LOG_LEVELS
from bt_app.cli import parse_cli_args
from bt_app.errors import AppExitCode, AppStartupError
from bt_app._version import __version__
from bt_app.vehicle_config import VehicleConfig


DEFAULT_VEHICLE_CONFIG_PATH = Path(__file__).parent.parent.joinpath(
    "config", "vehicle_config.yaml"
)


def main(args: Sequence[str] | None = None, standalone_mode: bool = True) -> None:
    try:
        options = parse_cli_args(args)
    except CliParseExit as exc:
        _handle_exit(exc.exit_code, standalone_mode)
        return
    except CliParseError as exc:
        _configure_logging("INFO")
        _handle_error(exc.message, exc.exit_code, standalone_mode)
        return

    config = None
    if options.command in {CommandName.DUMP_CONFIG, CommandName.RUN}:
        try:
            config = build_vehicle_config(options)
        except AppStartupError as exc:
            _configure_logging(options.log_level or "INFO")
            _handle_error(str(exc), exc.exit_code, standalone_mode)
            return

    _configure_logging(
        config.log_level if config is not None else options.log_level or "INFO"
    )
    try:
        dispatch_command(options, config)
    except AppStartupError as exc:
        _handle_error(str(exc), exc.exit_code, standalone_mode)


def dispatch_command(options: CliOptions, config: VehicleConfig | None = None) -> None:
    if options.command == CommandName.VERSION:
        print(_package_version())
        return
    if options.command == CommandName.ALIAS:
        print(build_alias_output(options.config_path))
        return
    if options.command == CommandName.DUMP_CONFIG:
        print(yaml.safe_dump(asdict(config), sort_keys=False), end="")
        return
    if options.command == CommandName.RUN:
        from bt_app.app import App

        if config is None:
            raise RuntimeError("run command requires vehicle config")
        App(config=config).run()
        return
    raise RuntimeError(f"unknown command: {options.command}")


def build_alias_output(config_path: object | None = None) -> str:
    alias_line = build_alias_line(config_path)
    append_line = f"echo {shlex.quote(alias_line)} >> ~/.bashrc"
    return (
        "For current shell:\n"
        f"{alias_line}\n"
        "For persistent shell (~/.bashrc):\n"
        f"{append_line}"
    )


def build_alias_line(config_path: object | None = None) -> str:
    command_parts = ["uv", "run", "bt-app", "run"]
    if config_path is not None:
        command_parts.extend(["-c", str(config_path)])
    command = shlex.join(command_parts)
    return f"alias start_bt_app={shlex.quote(command)}"


def build_vehicle_config(options: CliOptions) -> VehicleConfig:
    config = _load_default_vehicle_config()
    _merge_vehicle_config_yaml(config, options.config_path)
    _apply_cli_overrides(config, options)
    return config


def _load_default_vehicle_config() -> VehicleConfig:
    config = VehicleConfig()
    for config_field in fields(VehicleConfig):
        if config_field.default is not MISSING:
            setattr(config, config_field.name, config_field.default)
        elif config_field.default_factory is not MISSING:
            setattr(config, config_field.name, config_field.default_factory())
    return config


def _merge_vehicle_config_yaml(
    config: VehicleConfig,
    config_path: str | Path | None = None,
) -> None:
    yaml_path = Path(config_path) if config_path is not None else DEFAULT_VEHICLE_CONFIG_PATH
    if not yaml_path.is_absolute():
        yaml_path = Path.cwd().joinpath(yaml_path)
    if not yaml_path.exists():
        if config_path is not None:
            raise AppStartupError(f"Vehicle config not found: {yaml_path}")
        return

    try:
        with yaml_path.open("r", encoding="utf-8") as config_file:
            config_data = yaml.safe_load(config_file) or {}
    except Exception as exc:
        raise AppStartupError(
            f"Failed to load vehicle config from {yaml_path}: {exc}"
        ) from exc
    if not isinstance(config_data, dict):
        raise AppStartupError(
            f"Failed to load vehicle config from {yaml_path}: expected YAML mapping"
        )
    config_fields = {field.name for field in fields(VehicleConfig)}
    for key, value in config_data.items():
        if key in config_fields:
            setattr(config, key, value)


def _apply_cli_overrides(config: VehicleConfig, options: CliOptions) -> None:
    if options.log_level is not None:
        config.log_level = options.log_level


def _package_version() -> str:
    try:
        return metadata.version("bt-app")
    except metadata.PackageNotFoundError:
        return __version__


def _configure_logging(log_level: str) -> None:
    level = log_level.upper()
    if level not in LOG_LEVELS:
        level = "INFO"
    if hasattr(logger, "remove") and hasattr(logger, "add"):
        logger.remove()
        logger.add(
            sys.stderr,
            level=level,
            format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {module}:{line} | {message}",
        )
        return
    logger.setLevel(getattr(logging, level, logging.INFO))


def _handle_error(
    message: str,
    exit_code: int | AppExitCode,
    standalone_mode: bool,
) -> None:
    if not standalone_mode:
        raise RuntimeError(message)
    logger.error(message)
    raise SystemExit(int(exit_code))


def _handle_exit(exit_code: int | AppExitCode, standalone_mode: bool) -> None:
    if not standalone_mode:
        raise CliParseExit(int(exit_code))
    raise SystemExit(int(exit_code))


if __name__ == "__main__":
    main()

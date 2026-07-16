"""Application entrypoint and command dispatcher for bt-app."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import MISSING, asdict, fields
from importlib import metadata
import logging
from pathlib import Path
import sys

import yaml

try:
    from loguru import logger
except ModuleNotFoundError:  # pragma: no cover - exercised only in minimal envs
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

from bt_app.cli import CliOptions, CliParseError, CliParseExit, CommandName, LOG_LEVELS
from bt_app.cli import parse_cli_args
from bt_app.errors import AppStartupError
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
        config = build_vehicle_config(options)

    _configure_logging(
        config.log_level if config is not None else options.log_level or "INFO"
    )
    try:
        dispatch_command(options, config)
    except AppStartupError as exc:
        _handle_error(str(exc), 1, standalone_mode)


def dispatch_command(options: CliOptions, config: VehicleConfig | None = None) -> None:
    if options.command == CommandName.VERSION:
        print(_package_version())
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
    if not yaml_path.exists():
        return

    with yaml_path.open("r", encoding="utf-8") as config_file:
        config_data = yaml.safe_load(config_file) or {}
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
        return "0.0.1"


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


def _handle_error(message: str, exit_code: int, standalone_mode: bool) -> None:
    if not standalone_mode:
        raise RuntimeError(message)
    logger.error(message)
    raise SystemExit(exit_code)


def _handle_exit(exit_code: int, standalone_mode: bool) -> None:
    if not standalone_mode:
        raise CliParseExit(exit_code)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

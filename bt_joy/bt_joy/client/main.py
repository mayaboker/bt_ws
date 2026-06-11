"""Command-line entry point for bt_joy."""

from __future__ import annotations

from dataclasses import replace
from importlib import resources
from pathlib import Path
import sys

import click
from loguru import logger
import yaml

from bt_joy import __version__
from bt_joy.client.calibrate import run_calibration
from bt_joy.client.config import JoyConfig
from bt_joy.client.config import load_config, load_mapping
from bt_joy.client.joystick import JoystickNameMismatchError, JoystickOpenError
from bt_joy.client.runner import run


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  bt-joy --host 192.168.1.50 --port 9000\n"
        "  bt-joy --config /etc/bt-joy/client.yaml --mapping ./xbox.yaml --host 192.168.1.50\n"
        "  bt-joy --host 192.168.1.50 --port 9000 --print-config > client.yaml"
    )
)
@click.option(
    "-c",
    "--config",
    type=click.Path(dir_okay=False, path_type=str),
    help="Path to external joystick client configuration YAML. Uses the packaged example if omitted.",
)
@click.option(
    "--mapping",
    type=click.Path(dir_okay=False, path_type=str),
    help="Override joystick channel mapping YAML from the client config.",
)
@click.option("--device", help="Override joystick device path, for example /dev/input/js0.")
@click.option("--host", help="Override UDP destination host.")
@click.option("--port", type=int, help="Override UDP destination port.")
@click.option("--poll-hz", type=float, help="Override joystick polling rate.")
@click.option(
    "--print-config",
    is_flag=True,
    help="Print the effective client YAML config to stdout and exit. Use shell redirect to save it.",
)
@click.option(
    "--calibration",
    is_flag=True,
    help="Interactively calibrate joystick inputs and write output/joy/default*.yaml files.",
)
@click.option(
    "--keepalive-interval",
    default=None,
    type=float,
    help="Override seconds between UDP keepalive requests. Use 0 to disable.",
)
@click.option(
    "--keepalive-timeout",
    default=None,
    type=float,
    help="Override seconds to wait before logging a missing keepalive response.",
)
@click.option(
    "--joystick-reconnect-interval",
    default=None,
    type=float,
    help="Override seconds to wait before retrying a missing or disconnected joystick.",
)
@click.option(
    "--log-mapping",
    is_flag=True,
    help="Log raw joystick state and mapped channel values before sending UDP.",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"]),
    help="Log verbosity for --log-mapping.",
)
@click.version_option(__version__, prog_name="bt-joy")
def main(
    config: str | None,
    mapping: str | None,
    device: str | None,
    host: str | None,
    port: int | None,
    poll_hz: float | None,
    print_config: bool,
    calibration: bool,
    keepalive_interval: float | None,
    keepalive_timeout: float | None,
    joystick_reconnect_interval: float | None,
    log_mapping: bool,
    log_level: str,
) -> None:
    """Run the bt_joy command."""
    joy_config, config_file, mapping_file = _load_config(config, mapping)

    if device:
        joy_config = replace(joy_config, device=device)
    if poll_hz:
        joy_config = replace(joy_config, poll_hz=poll_hz)
    if keepalive_interval is not None:
        joy_config = replace(joy_config, keepalive_interval=keepalive_interval)
    if keepalive_timeout is not None:
        joy_config = replace(joy_config, keepalive_timeout=keepalive_timeout)
    if joystick_reconnect_interval is not None:
        joy_config = replace(joy_config, joystick_reconnect_interval=joystick_reconnect_interval)
    if host or port:
        udp = replace(
            joy_config.udp,
            host=host or joy_config.udp.host,
            port=port if port is not None else joy_config.udp.port,
        )
        joy_config = replace(joy_config, udp=udp)

    if print_config:
        click.echo(_dump_client_config_yaml(joy_config, mapping_file), nl=False)
        return

    if calibration:
        client_path, mapping_path = run_calibration(joy_config)
        click.echo(f"Wrote {client_path}")
        click.echo(f"Wrote {mapping_path}")
        return

    _configure_logging(log_level)
    logger.info("bt-joy verson: {}", __version__)
    logger.info("config file full path: {}", config_file)
    if mapping_file is not None:
        logger.info("mapping file full path: {}", mapping_file)
    try:
        run(
            joy_config,
            log_mapping=log_mapping,
            keepalive_interval=joy_config.keepalive_interval,
            keepalive_timeout=joy_config.keepalive_timeout,
        )
    except JoystickOpenError as exc:
        logger.error("{}", exc)
        raise click.ClickException(
            f"{exc}. Check --device or the device setting in {config_file}."
        ) from exc
    except JoystickNameMismatchError as exc:
        logger.error("{}", exc)
        raise click.ClickException(
            f"{exc}. Update expected_name in {config_file}, or use the correct --device."
        ) from exc


def _load_config(config: str | None, mapping: str | None):
    if config:
        config_path = Path(config).expanduser().resolve(strict=False)
        joy_config = load_config(config_path)
        return _load_mapping(joy_config, config_path, mapping)

    config_ref = resources.files("bt_joy.examples").joinpath("default.yaml")
    with resources.as_file(config_ref) as config_path:
        resolved_config_path = Path(config_path).resolve()
        joy_config = load_config(resolved_config_path)
        return _load_mapping(joy_config, resolved_config_path, mapping)


def _load_mapping(joy_config, config_path: Path, mapping: str | None):
    mapping_path = _resolve_mapping_path(mapping, joy_config.mapping, config_path)
    if mapping_path is None:
        return joy_config, str(config_path), None

    channels = load_mapping(mapping_path)
    return replace(joy_config, channels=channels), str(config_path), str(mapping_path)


def _resolve_mapping_path(
    mapping_override: str | None,
    configured_mapping: str | None,
    config_path: Path,
) -> Path | None:
    if mapping_override:
        return Path(mapping_override).expanduser().resolve(strict=False)
    if configured_mapping is None:
        return None

    mapping_path = Path(configured_mapping).expanduser()
    if not mapping_path.is_absolute():
        mapping_path = config_path.parent / mapping_path
    return mapping_path.resolve(strict=False)


def _dump_client_config_yaml(joy_config: JoyConfig, mapping_file: str | None) -> str:
    data = {
        "device": joy_config.device,
        "expected_name": joy_config.expected_name,
        "mapping": mapping_file or joy_config.mapping,
        "poll_hz": joy_config.poll_hz,
        "keepalive_interval": joy_config.keepalive_interval,
        "keepalive_timeout": joy_config.keepalive_timeout,
        "joystick_reconnect_interval": joy_config.joystick_reconnect_interval,
        "keepalive_rtt_warning": {
            "enabled": joy_config.keepalive_rtt_warning.enabled,
            "threshold_ms": joy_config.keepalive_rtt_warning.threshold_ms,
            "window_s": joy_config.keepalive_rtt_warning.window_s,
            "count": joy_config.keepalive_rtt_warning.count,
            "cooldown_s": joy_config.keepalive_rtt_warning.cooldown_s,
        },
        "axes": joy_config.axes,
        "buttons": joy_config.buttons,
        "udp": {
            "host": joy_config.udp.host,
            "port": joy_config.udp.port,
        },
    }
    return yaml.safe_dump(data, sort_keys=False)


def _configure_logging(log_level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {module}:{line} | {message}",
    )


if __name__ == "__main__":
    main()

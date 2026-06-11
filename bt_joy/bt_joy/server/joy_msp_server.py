"""UDP joystick server with pluggable output adapters."""

from __future__ import annotations

import errno
import sys
from dataclasses import replace
from pathlib import Path

import click
from loguru import logger
import yaml

from bt_joy import __version__
from bt_joy.server.adapters.crossfire import CrossfireOutputAdapter
from bt_joy.server.adapters.msp import MspOutputAdapter, StartupProbeError, _read_startup_info
from bt_joy.server.config import MspServerConfig, load_config
from bt_joy.server.controller import JoystickController
from bt_joy.server.msp import SerialMspTransport, TcpMspTransport
from bt_joy.server.udp_server import run_udp_server


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  bt-joy-msp-server --output serial --serial-device /dev/ttyUSB0 --baudrate 115200\n"
        "  bt-joy-msp-server --output serial --serial-device /dev/ttyUSB0 --status-interval 1.0\n"
        "  bt-joy-msp-server --adapter crossfire --print-config > crossfire-server.yaml\n"
    )
)
@click.option(
    "-c",
    "--config",
    type=click.Path(dir_okay=False, path_type=str),
    help="Path to joystick server YAML config.",
)
@click.option(
    "--adapter",
    type=click.Choice(["msp", "crossfire"]),
    help="Override output adapter. crossfire is currently a placeholder.",
)
@click.option("--listen-host", help="Override UDP host/interface to bind.")
@click.option("--listen-port", type=int, help="Override UDP port to bind.")
@click.option(
    "--output",
    "output_kind",
    type=click.Choice(["tcp", "serial"]),
    help="Override MSP output transport.",
)
@click.option("--tcp-host", help="Override MSP TCP host.")
@click.option("--tcp-port", type=int, help="Override MSP TCP port.")
@click.option(
    "--serial-device",
    type=click.Path(path_type=Path),
    help="Override MSP serial device, for example /dev/ttyUSB0.",
)
@click.option("--baudrate", type=int, help="Override MSP serial baudrate.")
@click.option("--rc-rate-hz", type=float, help="Override MSP_SET_RAW_RC repeat rate.")
@click.option(
    "--status-interval",
    type=float,
    help="Override seconds between MSP_STATUS_EX reads. Use 0 to disable status reads.",
)
@click.option("--status-timeout", type=float, help="Override MSP_STATUS_EX read timeout.")
@click.option(
    "--rc-read-interval",
    type=float,
    help="Override seconds between MSP_RC reads. Use 0 to disable RC reads.",
)
@click.option("--rc-read-timeout", type=float, help="Override MSP_RC read timeout.")
@click.option(
    "--altitude-interval",
    type=float,
    help="Override seconds between MSP_ALTITUDE reads. Use 0 to disable altitude reads.",
)
@click.option("--altitude-timeout", type=float, help="Override MSP_ALTITUDE read timeout.")
@click.option("--udp-timeout", type=float, help="Override UDP receive timeout.")
@click.option(
    "--failsafe-joystick-timeout",
    type=float,
    help="Override seconds without joystick data before failsafe. Use 0 to disable joystick monitor.",
)
@click.option(
    "--print-config",
    is_flag=True,
    help="Print the effective server YAML config to stdout and exit. Use shell redirect to save it.",
)
@click.option(
    "--log-level",
    type=click.Choice(["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"]),
    help="Override log verbosity.",
)
@click.version_option(__version__, prog_name="bt-joy-msp-server")
def main(
    config: str | None,
    adapter: str | None,
    listen_host: str | None,
    listen_port: int | None,
    output_kind: str | None,
    tcp_host: str | None,
    tcp_port: int | None,
    serial_device: Path | None,
    baudrate: int | None,
    rc_rate_hz: float | None,
    status_interval: float | None,
    status_timeout: float | None,
    rc_read_interval: float | None,
    rc_read_timeout: float | None,
    altitude_interval: float | None,
    altitude_timeout: float | None,
    udp_timeout: float | None,
    failsafe_joystick_timeout: float | None,
    print_config: bool,
    log_level: str | None,
) -> None:
    """Receive bt_joy UDP packets and forward channels through an output adapter."""
    server_config = _load_server_config(config)
    server_config = _apply_cli_overrides(
        server_config,
        adapter=adapter,
        listen_host=listen_host,
        listen_port=listen_port,
        output_kind=output_kind,
        tcp_host=tcp_host,
        tcp_port=tcp_port,
        serial_device=serial_device,
        baudrate=baudrate,
        rc_rate_hz=rc_rate_hz,
        status_interval=status_interval,
        status_timeout=status_timeout,
        rc_read_interval=rc_read_interval,
        rc_read_timeout=rc_read_timeout,
        altitude_interval=altitude_interval,
        altitude_timeout=altitude_timeout,
        udp_timeout=udp_timeout,
        failsafe_joystick_timeout=failsafe_joystick_timeout,
        log_level=log_level,
    )
    if print_config:
        click.echo(_dump_server_config_yaml(server_config), nl=False)
        return

    _configure_logging(server_config.log_level)
    _validate_server_config(server_config)
    output_adapter = _make_output_adapter(server_config)

    logger.info("bt-joy-msp-server {}", __version__)
    logger.info("server config: {}", Path(config).resolve() if config is not None else "defaults")
    logger.info("listening for joystick UDP on udp://{}:{}", server_config.listen_host, server_config.listen_port)
    logger.info("output adapter: {}", server_config.adapter)
    logger.info("output: {}", _describe_output(server_config))

    try:
        with output_adapter as opened_adapter:
            opened_adapter.startup_check()
            controller = JoystickController(
                opened_adapter,
                state_store=getattr(opened_adapter, "state_store", None),
                takeoff_automation_config=server_config.takeoff_automation,
            )
            run_udp_server(
                controller=controller,
                listen_host=server_config.listen_host,
                listen_port=server_config.listen_port,
                udp_timeout=server_config.udp_timeout,
                failsafe_joystick_timeout=server_config.failsafe_joystick_timeout,
            )
    except StartupProbeError as exc:
        logger.error("MSP startup probe failed: {}", exc)
        raise click.ClickException(f"MSP startup probe failed: {exc}") from exc
    except OSError as exc:
        if server_config.adapter != "msp" or not _is_connection_refused(exc):
            raise
        output = _describe_output(server_config)
        logger.error("MSP output connection refused: {} ({})", output, exc)
        raise click.ClickException(f"MSP output connection refused: {output}") from exc


def _load_server_config(config: str | None) -> MspServerConfig:
    if config is None:
        return MspServerConfig()
    return load_config(config)


def _apply_cli_overrides(
    server_config: MspServerConfig,
    adapter: str | None,
    listen_host: str | None,
    listen_port: int | None,
    output_kind: str | None,
    tcp_host: str | None,
    tcp_port: int | None,
    serial_device: Path | None,
    baudrate: int | None,
    rc_rate_hz: float | None,
    status_interval: float | None,
    status_timeout: float | None,
    rc_read_interval: float | None,
    rc_read_timeout: float | None,
    altitude_interval: float | None,
    altitude_timeout: float | None,
    udp_timeout: float | None,
    failsafe_joystick_timeout: float | None,
    log_level: str | None,
) -> MspServerConfig:
    updates = {}
    if adapter is not None:
        updates["adapter"] = adapter
    if listen_host is not None:
        updates["listen_host"] = listen_host
    if listen_port is not None:
        updates["listen_port"] = listen_port
    if output_kind is not None:
        updates["output"] = output_kind
    if tcp_host is not None:
        updates["tcp_host"] = tcp_host
    if tcp_port is not None:
        updates["tcp_port"] = tcp_port
    if serial_device is not None:
        updates["serial_device"] = serial_device
    if baudrate is not None:
        updates["baudrate"] = baudrate
    if rc_rate_hz is not None:
        updates["rc_rate_hz"] = rc_rate_hz
    if status_interval is not None:
        updates["status_interval"] = status_interval
    if status_timeout is not None:
        updates["status_timeout"] = status_timeout
    if rc_read_interval is not None:
        updates["rc_read_interval"] = rc_read_interval
    if rc_read_timeout is not None:
        updates["rc_read_timeout"] = rc_read_timeout
    if altitude_interval is not None:
        updates["altitude_interval"] = altitude_interval
    if altitude_timeout is not None:
        updates["altitude_timeout"] = altitude_timeout
    if udp_timeout is not None:
        updates["udp_timeout"] = udp_timeout
    if failsafe_joystick_timeout is not None:
        updates["failsafe_joystick_timeout"] = failsafe_joystick_timeout
    if log_level is not None:
        updates["log_level"] = log_level
    return replace(server_config, **updates)


def _dump_server_config_yaml(server_config: MspServerConfig) -> str:
    data = {
        "adapter": server_config.adapter,
        "listen_host": server_config.listen_host,
        "listen_port": server_config.listen_port,
        "output": server_config.output,
        "serial_device": None if server_config.serial_device is None else str(server_config.serial_device),
        "baudrate": server_config.baudrate,
        "rc_rate_hz": server_config.rc_rate_hz,
        "failsafe_channels": list(server_config.failsafe_channels),
        "tcp_host": server_config.tcp_host,
        "tcp_port": server_config.tcp_port,
        "status_interval": server_config.status_interval,
        "status_timeout": server_config.status_timeout,
        "rc_read_interval": server_config.rc_read_interval,
        "rc_read_timeout": server_config.rc_read_timeout,
        "altitude_interval": server_config.altitude_interval,
        "altitude_timeout": server_config.altitude_timeout,
        "startup_probe_attempts": server_config.startup_probe_attempts,
        "startup_probe_interval": server_config.startup_probe_interval,
        "udp_timeout": server_config.udp_timeout,
        "failsafe_joystick_timeout": server_config.failsafe_joystick_timeout,
        "takeoff_automation": {
            "enabled": server_config.takeoff_automation.enabled,
            "require_manual_arm": server_config.takeoff_automation.require_manual_arm,
            "trigger_channel": server_config.takeoff_automation.trigger_channel,
            "arm_channel": server_config.takeoff_automation.arm_channel,
            "trigger_on": server_config.takeoff_automation.trigger_on,
            "arm_on": server_config.takeoff_automation.arm_on,
            "target_altitude_m": server_config.takeoff_automation.target_altitude_m,
            "target_tolerance_m": server_config.takeoff_automation.target_tolerance_m,
            "throttle_base": server_config.takeoff_automation.throttle_base,
            "throttle_min": server_config.takeoff_automation.throttle_min,
            "throttle_max": server_config.takeoff_automation.throttle_max,
            "pid_kp": server_config.takeoff_automation.pid_kp,
            "pid_ki": server_config.takeoff_automation.pid_ki,
            "pid_kd": server_config.takeoff_automation.pid_kd,
            "pid_integral_limit": server_config.takeoff_automation.pid_integral_limit,
        },
        "log_level": server_config.log_level,
    }
    return yaml.safe_dump(data, sort_keys=False)


def _make_output_adapter(config: MspServerConfig):
    if config.adapter == "crossfire":
        return CrossfireOutputAdapter()

    transport = _make_transport(
        config.output,
        config.tcp_host,
        config.tcp_port,
        config.serial_device,
        config.baudrate,
    )
    return MspOutputAdapter(transport, config)


def _make_transport(
    output_kind: str,
    tcp_host: str,
    tcp_port: int,
    serial_device: Path | None,
    baudrate: int,
):
    if output_kind == "tcp":
        return TcpMspTransport(tcp_host, tcp_port)
    if serial_device is None:
        raise click.UsageError("--serial-device is required when --output serial")
    return SerialMspTransport(str(serial_device), baudrate)


def _validate_server_config(config: MspServerConfig) -> None:
    _validate_failsafe_config(config)
    _validate_rc_config(config)
    _validate_takeoff_automation_config(config)
    if config.adapter == "msp":
        _validate_startup_probe_config(config)
    elif config.adapter != "crossfire":
        raise click.UsageError("adapter must be msp or crossfire")


def _validate_startup_probe_config(config: MspServerConfig) -> None:
    if config.startup_probe_attempts <= 0:
        raise click.UsageError("startup_probe_attempts must be greater than zero")
    if config.startup_probe_interval < 0:
        raise click.UsageError("startup_probe_interval must be greater than or equal to zero")


def _validate_rc_config(config: MspServerConfig) -> None:
    if config.rc_rate_hz <= 0:
        raise click.UsageError("rc_rate_hz must be greater than zero")
    if len(config.failsafe_channels) != 8:
        raise click.UsageError("failsafe_channels must contain exactly 8 values")
    if config.rc_read_interval < 0:
        raise click.UsageError("rc_read_interval must be greater than or equal to zero")
    if config.rc_read_timeout <= 0:
        raise click.UsageError("rc_read_timeout must be greater than zero")
    if config.altitude_interval < 0:
        raise click.UsageError("altitude_interval must be greater than or equal to zero")
    if config.altitude_timeout <= 0:
        raise click.UsageError("altitude_timeout must be greater than zero")


def _validate_failsafe_config(config: MspServerConfig) -> None:
    if config.failsafe_joystick_timeout < 0:
        raise click.UsageError("failsafe_joystick_timeout must be greater than or equal to zero")
    if config.failsafe_joystick_timeout == 0:
        logger.warning("failsafe joystick monitor is disabled")


def _validate_takeoff_automation_config(config: MspServerConfig) -> None:
    automation = config.takeoff_automation
    valid_channels = {"roll", "pitch", "throttle", "yaw", "aux1", "aux2", "aux3", "aux4"}
    if automation.trigger_channel not in valid_channels:
        raise click.UsageError("takeoff_automation.trigger_channel must be a known RC channel")
    if automation.arm_channel not in valid_channels:
        raise click.UsageError("takeoff_automation.arm_channel must be a known RC channel")
    if automation.trigger_on < 0 or automation.arm_on < 0:
        raise click.UsageError("takeoff_automation channel values must be greater than or equal to zero")
    if automation.target_altitude_m <= 0:
        raise click.UsageError("takeoff_automation.target_altitude_m must be greater than zero")
    if automation.target_tolerance_m < 0:
        raise click.UsageError("takeoff_automation.target_tolerance_m must be greater than or equal to zero")
    if automation.throttle_min > automation.throttle_max:
        raise click.UsageError("takeoff_automation.throttle_min must be less than or equal to throttle_max")
    if not automation.throttle_min <= automation.throttle_base <= automation.throttle_max:
        raise click.UsageError("takeoff_automation.throttle_base must be between throttle_min and throttle_max")
    if automation.pid_integral_limit < 0:
        raise click.UsageError("takeoff_automation.pid_integral_limit must be greater than or equal to zero")


def _is_connection_refused(exc: OSError) -> bool:
    return isinstance(exc, ConnectionRefusedError) or exc.errno == errno.ECONNREFUSED


def _describe_output(config: MspServerConfig) -> str:
    if config.adapter == "crossfire":
        return "crossfire://placeholder"
    if config.output == "tcp":
        return f"tcp://{config.tcp_host}:{config.tcp_port}"
    return f"serial://{config.serial_device} baudrate={config.baudrate}"


def _configure_logging(log_level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {module}:{line} | {message}",
    )


if __name__ == "__main__":
    main()

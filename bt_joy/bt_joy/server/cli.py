"""Click command line interface for the bt_joy MSP server."""

from __future__ import annotations

from pathlib import Path

import click

from bt_joy import __version__
from bt_joy.server import joy_server
from bt_joy.server.joy_server import (
    ServerCliArgs,
    ServerConfigError,
    ServerOutputError,
    ServerStartupError,
    _dump_server_config_yaml,
)


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  joy-server --output serial --serial-device /dev/ttyUSB0 --baudrate 115200\n"
        "  joy-server --output serial --serial-device /dev/ttyUSB0 --status-interval 1.0\n"
        "  joy-server --adapter crossfire --print-config > crossfire-server.yaml\n"
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
@click.version_option(__version__, prog_name="joy-server")
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
    args = ServerCliArgs(
        config=config,
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
        print_config=print_config,
        log_level=log_level,
    )

    try:
        server_config = joy_server.main(args)
    except ServerConfigError as exc:
        raise click.UsageError(str(exc)) from exc
    except (ServerStartupError, ServerOutputError) as exc:
        raise click.ClickException(str(exc)) from exc

    if print_config and server_config is not None:
        click.echo(_dump_server_config_yaml(server_config), nl=False)


if __name__ == "__main__":
    main()

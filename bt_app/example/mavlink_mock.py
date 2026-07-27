"""Small MAVLink flight-controller peer for testing bt-joy."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import os
import sys
import time
from typing import Any

import click

from bt_joy.client.mavlink_output import IGNORE, RELEASE_EXTENDED


@dataclass(frozen=True)
class ChannelStatus:
    index: int
    value: int
    state: str


def classify_channels(message: Any) -> tuple[ChannelStatus, ...]:
    """Classify the distinct ignore/release semantics of all 18 fields."""

    result: list[ChannelStatus] = []
    for index in range(18):
        value = int(getattr(message, f"chan{index + 1}_raw"))
        if index < 8:
            state = "ignored" if value == IGNORE else "released" if value == 0 else "active"
        else:
            state = (
                "released"
                if value == RELEASE_EXTENDED
                else "ignored"
                if value in (0, IGNORE)
                else "active"
            )
        result.append(ChannelStatus(index + 1, value, state))
    return tuple(result)


class MavlinkMockServer:
    """Receive RC overrides and emit flight-controller heartbeats."""

    def __init__(
        self,
        connection: Any,
        heartbeat_rate_hz: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        print_func: Callable[[str], None] = print,
    ) -> None:
        self.connection = connection
        self.heartbeat_period = 1.0 / heartbeat_rate_hz
        self.clock = clock
        self.print = print_func
        self.client_seen = False
        self.next_heartbeat_at = 0.0
        self.message_count = 0
        self.first_override_at: float | None = None
        self.active_channels: set[int] = set()

    def run(self) -> None:
        try:
            while True:
                self.run_once()
                time.sleep(0.01)
        except KeyboardInterrupt:
            return
        finally:
            self.connection.close()

    def run_once(self) -> None:
        now = self.clock()
        while True:
            message = self.connection.recv_match(blocking=False)
            if message is None:
                break
            message_type = message.get_type()
            if message_type == "HEARTBEAT":
                first_client = not self.client_seen
                self.client_seen = True
                if first_client:
                    self.print(
                        f"client discovered system={message.get_srcSystem()} "
                        f"component={message.get_srcComponent()}"
                    )
                    self._send_heartbeat()
                    self.next_heartbeat_at = now + self.heartbeat_period
            elif message_type == "RC_CHANNELS_OVERRIDE":
                self.client_seen = True
                self._handle_override(message, now)

        if self.client_seen and now >= self.next_heartbeat_at:
            self._send_heartbeat()
            self.next_heartbeat_at = now + self.heartbeat_period

    def _send_heartbeat(self) -> None:
        constants = _constants(self.connection)
        self.connection.mav.heartbeat_send(
            constants.MAV_TYPE_QUADROTOR,
            constants.MAV_AUTOPILOT_GENERIC,
            0,
            0,
            constants.MAV_STATE_ACTIVE,
        )

    def _handle_override(self, message: Any, now: float) -> None:
        statuses = classify_channels(message)
        previously_active = set(self.active_channels)
        for status in statuses:
            if status.state == "active":
                self.active_channels.add(status.index)
            elif status.state == "released":
                self.active_channels.discard(status.index)

        released = bool(previously_active) and all(
            next(item for item in statuses if item.index == index).state == "released"
            for index in previously_active
        )
        self.message_count += 1
        if self.first_override_at is None:
            self.first_override_at = now
        elapsed = now - self.first_override_at
        rate = (self.message_count - 1) / elapsed if elapsed > 0 else 0.0
        values = " ".join(
            f"ch{item.index}={item.value}({item.state})"
            for item in statuses
            if item.state != "ignored"
        )
        label = " RELEASE" if released else ""
        self.print(
            f"RC_CHANNELS_OVERRIDE{label} "
            f"source={message.get_srcSystem()}/{message.get_srcComponent()} "
            f"target={message.target_system}/{message.target_component} "
            f"count={self.message_count} rate_hz={rate:.1f} {values}".rstrip()
        )


def open_server_connection(
    host: str,
    port: int,
    system_id: int,
    component_id: int,
) -> Any:
    os.environ.setdefault("MAVLINK20", "1")
    try:
        from pymavlink import mavutil
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "MAVLink support requires pymavlink; install with: pip install bt-joy[mavlink]"
        ) from exc
    connection = mavutil.mavlink_connection(
        f"udpin:{host}:{port}",
        source_system=system_id,
        source_component=component_id,
        dialect="common",
    )
    connection._bt_joy_mavlink = mavutil.mavlink
    return connection


def _constants(connection: Any) -> Any:
    constants = getattr(connection, "_bt_joy_mavlink", None)
    if constants is None:
        constants = getattr(connection, "mavlink", None)
    if constants is None:
        raise RuntimeError("MAVLink connection does not expose protocol constants")
    return constants


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--host", default="0.0.0.0", show_default=True, help="UDP bind host.")
@click.option("--port", type=click.IntRange(1, 65535), default=14550, show_default=True)
@click.option("--system-id", type=click.IntRange(1, 255), default=1, show_default=True)
@click.option("--component-id", type=click.IntRange(1, 255), default=1, show_default=True)
@click.option(
    "--heartbeat-rate-hz",
    type=click.FloatRange(min=0.01),
    default=1.0,
    show_default=True,
)
def cli(
    host: str,
    port: int,
    system_id: int,
    component_id: int,
    heartbeat_rate_hz: float,
) -> None:
    """Run a MAVLink heartbeat peer and inspect RC override messages."""

    try:
        connection = open_server_connection(host, port, system_id, component_id)
        click.echo(f"listening for MAVLink on udp://{host}:{port}")
        MavlinkMockServer(connection, heartbeat_rate_hz).run()
    except RuntimeError as exc:
        click.echo(str(exc), err=True)
        raise click.exceptions.Exit(2) from exc


def main(args: Sequence[str] | None = None) -> None:
    cli.main(args=list(args) if args is not None else None, prog_name="bt-joy-mavlink-mock")


if __name__ == "__main__":
    main(sys.argv[1:])

"""MAVLink transport boundary for joystick scenarios."""

from __future__ import annotations

from collections.abc import Sequence
import os
import socket
from typing import Any, Protocol

os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil

from joy_scenarios.models import (
    JOYSTICK_COMPONENT_ID,
    JOYSTICK_SYSTEM_ID,
    TARGET_COMPONENT_ID,
    TARGET_SYSTEM_ID,
    JoystickCommand,
    ScenarioError,
)

mavutil.set_dialect("common")


class RcTransport(Protocol):
    def open(self) -> None: ...

    def close(self) -> None: ...

    def send(self, command: JoystickCommand) -> None: ...

    def receive(self) -> Sequence[Any]: ...


class MavlinkUdpTransport:
    """Send RC overrides and receive MAVLink telemetry over one UDP socket."""

    def __init__(
        self,
        *,
        destination: tuple[str, int],
        listen: tuple[str, int],
    ) -> None:
        self.destination = destination
        self.listen = listen
        self._socket: socket.socket | None = None
        self._encoder = mavutil.mavlink.MAVLink(
            None,
            srcSystem=JOYSTICK_SYSTEM_ID,
            srcComponent=JOYSTICK_COMPONENT_ID,
        )
        self._parser = mavutil.mavlink.MAVLink(None)
        self._parser.robust_parsing = True

    def open(self) -> None:
        if self._socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(self.listen)
        except OSError as exc:
            sock.close()
            raise ScenarioError(
                f"Cannot bind telemetry socket {self.listen[0]}:{self.listen[1]}: {exc}"
            ) from exc
        sock.setblocking(False)
        self._socket = sock

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def send(self, command: JoystickCommand) -> None:
        if self._socket is None:
            raise ScenarioError("MAVLink transport is not open")
        message = self._encoder.rc_channels_override_encode(
            TARGET_SYSTEM_ID,
            TARGET_COMPONENT_ID,
            *command.channels,
        )
        self._socket.sendto(message.pack(self._encoder), self.destination)

    def receive(self) -> tuple[Any, ...]:
        if self._socket is None:
            return ()
        messages: list[Any] = []
        while True:
            try:
                payload, _address = self._socket.recvfrom(4096)
            except BlockingIOError:
                return tuple(messages)
            for byte in payload:
                message = self._parser.parse_char(bytes([byte]))
                if message is not None:
                    messages.append(message)

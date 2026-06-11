"""Thread-safe server state shared by output adapters and logic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import threading
import time
from collections.abc import Sequence

from bt_joy.server.msp import MspAltitude, MspStatus


class RcChannel(IntEnum):
    ROLL = 0
    PITCH = 1
    THROTTLE = 2
    YAW = 3
    AUX1 = 4
    AUX2 = 5
    AUX3 = 6
    AUX4 = 7


@dataclass(frozen=True)
class ServerStateSnapshot:
    manual_channels: tuple[int, ...] | None = None
    manual_channels_at: float | None = None
    output_channels: tuple[int, ...] | None = None
    output_channels_at: float | None = None
    commanded_channels: tuple[int, ...] | None = None
    commanded_channels_at: float | None = None
    fc_rc_channels: tuple[int, ...] | None = None
    fc_rc_channels_at: float | None = None
    status: MspStatus | None = None
    status_at: float | None = None
    altitude: MspAltitude | None = None
    altitude_at: float | None = None

    def commanded_channel(self, channel: RcChannel) -> int | None:
        return _read_channel(self.commanded_channels, channel)

    def manual_channel(self, channel: RcChannel) -> int | None:
        return _read_channel(self.manual_channels, channel)

    def output_channel(self, channel: RcChannel) -> int | None:
        return _read_channel(self.output_channels, channel)

    def fc_rc_channel(self, channel: RcChannel) -> int | None:
        return _read_channel(self.fc_rc_channels, channel)

    @property
    def commanded_throttle(self) -> int | None:
        return self.commanded_channel(RcChannel.THROTTLE)

    @property
    def manual_throttle(self) -> int | None:
        return self.manual_channel(RcChannel.THROTTLE)

    @property
    def output_throttle(self) -> int | None:
        return self.output_channel(RcChannel.THROTTLE)

    @property
    def fc_rc_throttle(self) -> int | None:
        return self.fc_rc_channel(RcChannel.THROTTLE)


class ServerStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._manual_channels: tuple[int, ...] | None = None
        self._manual_channels_at: float | None = None
        self._output_channels: tuple[int, ...] | None = None
        self._output_channels_at: float | None = None
        self._commanded_channels: tuple[int, ...] | None = None
        self._commanded_channels_at: float | None = None
        self._fc_rc_channels: tuple[int, ...] | None = None
        self._fc_rc_channels_at: float | None = None
        self._status: MspStatus | None = None
        self._status_at: float | None = None
        self._altitude: MspAltitude | None = None
        self._altitude_at: float | None = None

    def update_manual_channels(self, channels: Sequence[int]) -> None:
        with self._lock:
            self._manual_channels = tuple(int(channel) for channel in channels)
            self._manual_channels_at = time.monotonic()

    def update_output_channels(self, channels: Sequence[int]) -> None:
        with self._lock:
            self._output_channels = tuple(int(channel) for channel in channels)
            self._output_channels_at = time.monotonic()

    def update_commanded_channels(self, channels: Sequence[int]) -> None:
        with self._lock:
            self._commanded_channels = tuple(int(channel) for channel in channels)
            self._commanded_channels_at = time.monotonic()

    def update_fc_rc_channels(self, channels: Sequence[int]) -> None:
        with self._lock:
            self._fc_rc_channels = tuple(int(channel) for channel in channels)
            self._fc_rc_channels_at = time.monotonic()

    def update_status(self, status: MspStatus) -> None:
        with self._lock:
            self._status = status
            self._status_at = time.monotonic()

    def update_altitude(self, altitude: MspAltitude) -> None:
        with self._lock:
            self._altitude = altitude
            self._altitude_at = time.monotonic()

    def snapshot(self) -> ServerStateSnapshot:
        with self._lock:
            return ServerStateSnapshot(
                manual_channels=self._manual_channels,
                manual_channels_at=self._manual_channels_at,
                output_channels=self._output_channels,
                output_channels_at=self._output_channels_at,
                commanded_channels=self._commanded_channels,
                commanded_channels_at=self._commanded_channels_at,
                fc_rc_channels=self._fc_rc_channels,
                fc_rc_channels_at=self._fc_rc_channels_at,
                status=self._status,
                status_at=self._status_at,
                altitude=self._altitude,
                altitude_at=self._altitude_at,
            )


def _read_channel(channels: tuple[int, ...] | None, channel: RcChannel) -> int | None:
    if channels is None or int(channel) >= len(channels):
        return None
    return channels[int(channel)]

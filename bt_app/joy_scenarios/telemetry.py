"""Telemetry decoding independent of transport and scenario sequencing."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
import struct
from typing import Any

from pymavlink import mavutil

from joy_scenarios.models import (
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    TelemetrySnapshot,
)


CHANNEL_STATUS_MESSAGE_TYPE = 1
CHANNEL_STATUS_VERSION = 1
CHANNEL_STATUS_FORMAT = "<BBBH8H"
CHANNEL_STATUS_SIZE = struct.calcsize(CHANNEL_STATUS_FORMAT)


@dataclass(frozen=True)
class StateTransition:
    previous: int | None
    current: int
    snapshot: TelemetrySnapshot


@dataclass(frozen=True)
class TelemetryUpdate:
    changed: bool
    transition: StateTransition | None = None


class TelemetryMonitor:
    def __init__(self) -> None:
        self.snapshot = TelemetrySnapshot()

    def consume(self, message: Any) -> TelemetryUpdate:
        if (
            int(message.get_srcSystem()) != APP_SYSTEM_ID
            or int(message.get_srcComponent()) != APP_COMPONENT_ID
        ):
            return TelemetryUpdate(False)

        message_type = message.get_type()
        if message_type == "HEARTBEAT":
            previous_state = self.snapshot.state
            state = int(message.custom_mode)
            armed = bool(
                int(message.base_mode)
                & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            changed = state != previous_state or armed != self.snapshot.armed
            self.snapshot = replace(self.snapshot, state=state, armed=armed)
            transition = None
            if state != previous_state:
                transition = StateTransition(previous_state, state, self.snapshot)
            return TelemetryUpdate(changed, transition)

        if message_type == "GLOBAL_POSITION_INT":
            altitude_m = float(message.relative_alt) / 1000.0
            changed = altitude_m != self.snapshot.altitude_m
            self.snapshot = replace(
                self.snapshot,
                altitude_m=altitude_m,
                altitude_samples=self.snapshot.altitude_samples + 1,
            )
            return TelemetryUpdate(changed)

        if message_type == "NAMED_VALUE_FLOAT":
            name = message.name
            if isinstance(name, bytes):
                name = name.split(b"\0", 1)[0].decode("ascii")
            else:
                name = str(name).split("\0", 1)[0]
            if name != "alt_sp":
                return TelemetryUpdate(False)
            setpoint_m = float(message.value)
            changed = setpoint_m != self.snapshot.altitude_setpoint_m
            self.snapshot = replace(
                self.snapshot,
                altitude_setpoint_m=setpoint_m,
            )
            return TelemetryUpdate(changed)

        if message_type == "ATTITUDE":
            roll_deg = math.degrees(float(message.roll))
            pitch_deg = math.degrees(float(message.pitch))
            yaw_deg = math.degrees(float(message.yaw)) % 360.0
            changed = (
                roll_deg != self.snapshot.roll_deg
                or pitch_deg != self.snapshot.pitch_deg
                or yaw_deg != self.snapshot.yaw_deg
            )
            self.snapshot = replace(
                self.snapshot,
                roll_deg=roll_deg,
                pitch_deg=pitch_deg,
                yaw_deg=yaw_deg,
                attitude_samples=self.snapshot.attitude_samples + 1,
            )
            return TelemetryUpdate(changed)

        if (
            message_type == "V2_EXTENSION"
            and int(message.message_type) == CHANNEL_STATUS_MESSAGE_TYPE
        ):
            payload = bytes(message.payload[:CHANNEL_STATUS_SIZE])
            if len(payload) != CHANNEL_STATUS_SIZE:
                return TelemetryUpdate(False)
            version, _command, state, _flags, *_channels = struct.unpack(
                CHANNEL_STATUS_FORMAT,
                payload,
            )
            if version != CHANNEL_STATUS_VERSION:
                return TelemetryUpdate(False)
            previous_state = self.snapshot.state
            state = int(state)
            changed = state != previous_state
            self.snapshot = replace(self.snapshot, state=state)
            transition = None
            if changed:
                transition = StateTransition(previous_state, state, self.snapshot)
            return TelemetryUpdate(changed, transition)

        return TelemetryUpdate(False)

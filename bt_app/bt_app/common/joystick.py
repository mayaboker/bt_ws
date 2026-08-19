"""Internal representation of joystick input received over MAVLink."""

from collections.abc import Sequence
from enum import IntEnum
from typing import NamedTuple

from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN


LOW_THROTTLE_THRESHOLD = 1050
INTERNAL_JOYSTICK_CHANNELS = 18
ACTIVE_JOYSTICK_CHANNELS = 7


class TrackerMode(IntEnum):
    DISABLED = RC_MIN
    TRACKER1 = RC_MID
    TRACKER2 = RC_MAX


class InternalJoystick(NamedTuple):
    """Immutable, named snapshot of the application's joystick channels.

    boxer
    SA: manual/althokd
    SB: tracker mode: disabled/tracker1/tracker2
    SC:
    SD: auto take off
    SE: arm
    SF: enabler
    """

    roll: int = RC_MID
    pitch: int = RC_MID
    throttle: int = RC_MIN
    yaw: int = RC_MID
    arm: int = RC_MIN
    manual: int = RC_MIN
    auto_takeoff: int = RC_MIN
    tracker_mode: int = TrackerMode.DISABLED
    tracker_enable: int = RC_MIN
    reserved_10: int = RC_MIN
    reserved_11: int = RC_MIN
    reserved_12: int = RC_MIN
    reserved_13: int = RC_MIN
    reserved_14: int = RC_MIN
    reserved_15: int = RC_MIN
    reserved_16: int = RC_MIN
    reserved_17: int = RC_MIN
    reserved_18: int = RC_MIN

    @classmethod
    def from_channels(cls, channels: Sequence[int]) -> "InternalJoystick":
        """Validate and normalize one 18-channel MAVLink input snapshot."""
        if len(channels) != INTERNAL_JOYSTICK_CHANNELS:
            raise ValueError(
                "joystick input must contain exactly "
                f"{INTERNAL_JOYSTICK_CHANNELS} channels; received {len(channels)}"
            )

        normalized: list[int] = []
        for index, raw_value in enumerate(channels):
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"joystick channel {index + 1} is not an integer: {raw_value!r}"
                ) from exc

            if index >= ACTIVE_JOYSTICK_CHANNELS and value == 0:
                value = RC_MIN
            if not RC_MIN <= value <= RC_MAX:
                raise ValueError(
                    f"joystick channel {index + 1} must be between "
                    f"{RC_MIN} and {RC_MAX}; received {value}"
                )
            normalized.append(value)

        return cls(*normalized)

    def is_throttle_low(self) -> bool:
        return self.throttle < LOW_THROTTLE_THRESHOLD

    def is_armed(self) -> bool:
        return self.arm == RC_MAX

    def is_manual(self) -> bool:
        return self.manual == RC_MIN

    def is_auto_takeoff(self) -> bool:
        return self.auto_takeoff == RC_MAX

    def selected_tracker_mode(self) -> TrackerMode | None:
        try:
            return TrackerMode(self.tracker_mode)
        except ValueError:
            return None

    def is_tracker_selected(self) -> bool:
        return self.selected_tracker_mode() in {
            TrackerMode.TRACKER1,
            TrackerMode.TRACKER2,
        }

    def is_tracker_enable_high(self) -> bool:
        return self.tracker_enable == RC_MAX


__all__ = [
    "ACTIVE_JOYSTICK_CHANNELS",
    "INTERNAL_JOYSTICK_CHANNELS",
    "InternalJoystick",
    "LOW_THROTTLE_THRESHOLD",
    "TrackerMode",
]

"""Value objects and constants shared by joystick scenarios."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from bt_app.common import RobotState


RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000

APP_SYSTEM_ID = 1
APP_COMPONENT_ID = 1
JOYSTICK_SYSTEM_ID = 255
JOYSTICK_COMPONENT_ID = 190
TARGET_SYSTEM_ID = 254
TARGET_COMPONENT_ID = 0


class ScenarioError(RuntimeError):
    """Raised when a scenario cannot safely reach its expected condition."""


class ColorMode(str, Enum):
    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


@dataclass(frozen=True)
class JoystickCommand:
    """One complete 18-channel virtual joystick snapshot."""

    roll: int = RC_MID
    pitch: int = RC_MID
    throttle: int = RC_MIN
    yaw: int = RC_MID
    arm: int = RC_MIN
    manual: int = RC_MAX
    auto_takeoff: int = RC_MIN
    tracker_mode: int = RC_MIN
    tracker_enable: int = RC_MIN
    extended_channels: tuple[int, ...] = (RC_MIN,) * 9

    def __post_init__(self) -> None:
        named_channels = (
            ("roll", self.roll),
            ("pitch", self.pitch),
            ("throttle", self.throttle),
            ("yaw", self.yaw),
            ("arm", self.arm),
            ("manual", self.manual),
            ("auto_takeoff", self.auto_takeoff),
            ("tracker_mode", self.tracker_mode),
            ("tracker_enable", self.tracker_enable),
        )
        for name, value in named_channels:
            if not RC_MIN <= value <= RC_MAX:
                raise ValueError(f"{name} must be between {RC_MIN} and {RC_MAX}")
        if len(self.extended_channels) != 9:
            raise ValueError("extended_channels must contain channels 10 through 18")
        for index, value in enumerate(self.extended_channels, start=10):
            if not RC_MIN <= value <= RC_MAX:
                raise ValueError(
                    f"channel {index} must be between {RC_MIN} and {RC_MAX}"
                )

    @property
    def channels(self) -> tuple[int, ...]:
        return (
            self.roll,
            self.pitch,
            self.throttle,
            self.yaw,
            self.arm,
            self.manual,
            self.auto_takeoff,
            self.tracker_mode,
            self.tracker_enable,
            *self.extended_channels,
        )

    def with_controls(self, **changes: int) -> JoystickCommand:
        """Return a new snapshot with selected named controls changed."""

        return replace(self, **changes)

    @classmethod
    def neutral_disarmed(cls) -> JoystickCommand:
        return cls()

    @classmethod
    def manual_armed(cls, *, throttle: int = RC_MIN) -> JoystickCommand:
        return cls(throttle=throttle, arm=RC_MAX, manual=RC_MIN)

    @classmethod
    def automatic_takeoff(cls) -> JoystickCommand:
        return cls(arm=RC_MAX, auto_takeoff=RC_MAX)

    @classmethod
    def altitude_hold(cls) -> JoystickCommand:
        return cls(throttle=RC_MID, arm=RC_MAX)

    @classmethod
    def manual_disarmed(cls) -> JoystickCommand:
        return cls(manual=RC_MIN)

    @classmethod
    def tracker_1_selected(cls, *, enable: bool = False) -> JoystickCommand:
        return cls.altitude_hold().with_controls(
            tracker_mode=RC_MID,
            tracker_enable=RC_MAX if enable else RC_MIN,
        )


@dataclass(frozen=True)
class ScenarioConfig:
    destination_host: str = "127.0.0.1"
    destination_port: int = 14560
    listen_host: str = "0.0.0.0"
    listen_port: int = 14550
    rate_hz: float = 50.0
    state_timeout_s: float = 20.0
    takeoff_timeout_s: float = 60.0
    landing_timeout_s: float = 120.0
    touchdown_altitude_m: float = 0.15
    color: ColorMode = ColorMode.AUTO

    def __post_init__(self) -> None:
        if self.rate_hz <= 0:
            raise ValueError("rate_hz must be greater than zero")
        if min(
            self.state_timeout_s,
            self.takeoff_timeout_s,
            self.landing_timeout_s,
        ) <= 0:
            raise ValueError("timeouts must be greater than zero")
        if self.touchdown_altitude_m < 0:
            raise ValueError("touchdown_altitude_m cannot be negative")
        for name, value in (
            ("destination_port", self.destination_port),
            ("listen_port", self.listen_port),
        ):
            if not 1 <= value <= 65535:
                raise ValueError(f"{name} must be between 1 and 65535")

    @property
    def destination(self) -> tuple[str, int]:
        return self.destination_host, self.destination_port

    @property
    def listen(self) -> tuple[str, int]:
        return self.listen_host, self.listen_port


@dataclass(frozen=True)
class TelemetrySnapshot:
    state: int | None = None
    armed: bool = False
    altitude_m: float | None = None
    altitude_setpoint_m: float | None = None
    altitude_samples: int = 0
    roll_deg: float | None = None
    pitch_deg: float | None = None
    yaw_deg: float | None = None
    attitude_samples: int = 0

    def describe(self) -> str:
        altitude = "unknown" if self.altitude_m is None else f"{self.altitude_m:.2f} m"
        return (
            f"state={state_name(self.state)} armed={self.armed} "
            f"altitude={altitude} setpoint={self.altitude_setpoint_m}"
        )


STATE_NAMES = {int(state): state.name for state in RobotState}


def state_name(state: int | None) -> str:
    if state is None:
        return "UNKNOWN"
    return STATE_NAMES.get(state, f"UNKNOWN({state})")

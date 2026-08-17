"""Reusable MAVLink RC scenario transport and synchronization base."""

from __future__ import annotations

import socket
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Sequence

from pymavlink.dialects.v20 import ardupilotmega as mavlink_dialect

from bt_app.common import InternalJoy



ROLL = 0
PITCH = 1
THROTTLE = 2
YAW = 3
ARM = 4
MANUAL = 5
AUTO_TAKEOFF = 6
ENABLER = 7
TRACKER_MODE = 8

RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000

APP_SYSTEM_ID = 1
APP_COMPONENT_ID = mavlink_dialect.MAV_COMP_ID_AUTOPILOT1
JOYSTICK_SYSTEM_ID = 255
JOYSTICK_COMPONENT_ID = mavlink_dialect.MAV_COMP_ID_MISSIONPLANNER
TARGET_SYSTEM_ID = 254
TARGET_COMPONENT_ID = 0

STATE_IDLE = 0
STATE_MANUAL = 1
STATE_TAKEOFF = 5
STATE_ALT_HOLD = 7
STATE_GLIDE = 8
STATE_NAMES = {
    STATE_IDLE: "IDLE",
    STATE_MANUAL: "MANUAL",
    STATE_TAKEOFF: "TAKEOFF",
    STATE_ALT_HOLD: "ALT_HOLD",
    STATE_GLIDE: "GLIDE",
}
ANSI_BOLD_CYAN = "\033[1;36m"
ANSI_BOLD_YELLOW = "\033[1;33m"
ANSI_RESET = "\033[0m"

def rc_channels(
    *,
    throttle: int = RC_MIN,
    armed: bool = False,
    manual: bool = False,
    auto_takeoff: bool = False,
    tracker_mode: bool = False,
    payload: bool = False
) -> tuple[int, ...]:
    """Build the application joystick channels (up to MAVLink's 18 fields)."""

    channels = [RC_MIN] * len(InternalJoy)
    channels[InternalJoy.ROLL] = RC_MID
    channels[InternalJoy.PITCH] = RC_MID
    channels[InternalJoy.THROTTLE] = throttle
    channels[InternalJoy.YAW] = RC_MID
    channels[InternalJoy.ARM] = RC_MAX if armed else RC_MIN
    channels[InternalJoy.MANUAL] = RC_MIN if manual else RC_MAX
    channels[InternalJoy.PAYLOAD] = RC_MAX if payload else RC_MIN
    channels[InternalJoy.AUTO_TAKE_OFF] = RC_MAX if auto_takeoff else RC_MIN
    channels[InternalJoy.TRACKER_MODE] = RC_MAX if tracker_mode else RC_MIN

    return tuple(channels)


NEUTRAL_DISARMED = rc_channels()
ARM_IN_MANUAL = rc_channels(armed=True, manual=True)
AUTO_TAKEOFF_ARMED = rc_channels(armed=True, auto_takeoff=True)
# Centered throttle requests no altitude-setpoint change in ALT_HOLD and also
# satisfies the MANUAL -> ALT_HOLD state-machine guard (throttle > 1050).
ALT_HOLD_ARMED = rc_channels(armed=True, throttle=RC_MID)
MANUAL_DESCENT_ARMED = rc_channels(armed=True, manual=True, throttle=1600)
MANUAL_DISARMED = rc_channels(manual=True, throttle=RC_MIN)




class ScenarioError(RuntimeError):
    """Raised when a scenario cannot complete safely."""


class Telemetry:
    """Application heartbeat and relative-altitude telemetry snapshot."""

    def __init__(self) -> None:
        self.state: int | None = None
        self.armed = False
        self.altitude_m: float | None = None
        self.altitude_samples = 0

    def describe(self) -> str:
        state = STATE_NAMES.get(self.state, str(self.state))
        altitude = "unknown" if self.altitude_m is None else f"{self.altitude_m:.2f} m"
        return f"state={state} armed={self.armed} altitude={altitude}"

    def consume(self, message: Any) -> bool:
        if (
            int(message.get_srcSystem()) != APP_SYSTEM_ID
            or int(message.get_srcComponent()) != APP_COMPONENT_ID
        ):
            return False
        message_type = message.get_type()
        if message_type == "HEARTBEAT":
            new_state = int(message.custom_mode)
            new_armed = bool(
                int(message.base_mode)
                & mavlink_dialect.MAV_MODE_FLAG_SAFETY_ARMED
            )
            changed = new_state != self.state or new_armed != self.armed
            self.state = new_state
            self.armed = new_armed
            return changed
        if message_type == "GLOBAL_POSITION_INT":
            new_altitude = float(message.relative_alt) / 1000.0
            changed = new_altitude != self.altitude_m
            self.altitude_m = new_altitude
            self.altitude_samples += 1
            return changed
        return False


class MavlinkRcScenarioBase(ABC):
    """Base class for scenarios that periodically send RC overrides."""

    def __init__(
        self,
        *,
        destination: tuple[str, int],
        listen: tuple[str, int],
        rate_hz: float,
        state_timeout_s: float,
        landing_timeout_s: float,
        touchdown_altitude_m: float,
    ) -> None:
        if rate_hz <= 0.0:
            raise ValueError("rate_hz must be greater than zero")
        self.destination = destination
        self.listen = listen
        self.period_s = 1.0 / rate_hz
        self.state_timeout_s = state_timeout_s
        self.landing_timeout_s = landing_timeout_s
        self.touchdown_altitude_m = touchdown_altitude_m
        self.telemetry = Telemetry()
        self._socket: socket.socket | None = None
        self._encoder = mavlink_dialect.MAVLink(
            None, srcSystem=JOYSTICK_SYSTEM_ID, srcComponent=JOYSTICK_COMPONENT_ID
        )
        self._parser = mavlink_dialect.MAVLink(None)
        self._parser.robust_parsing = True
        self._airborne = False
        self._completed = False

    @abstractmethod
    def run(self) -> None:
        """Execute the scenario-specific phase flow."""

    def _open(self) -> None:
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

    def _wait_for_state(self, channels: Sequence[int], expected_state: int, timeout_s: float) -> None:
        self._wait_for(
            channels,
            lambda: self.telemetry.state == expected_state,
            timeout_s,
            f"state {STATE_NAMES[expected_state]}",
        )

    def _wait_for(
        self,
        channels: Sequence[int],
        predicate: Callable[[], bool],
        timeout_s: float,
        expectation: str,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        next_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(channels)
                next_send = now + self.period_s
            self._receive_pending()
            if predicate():
                return
            time.sleep(min(0.005, self.period_s))
        raise ScenarioError(
            f"Timed out after {timeout_s:.1f}s waiting for {expectation}; "
            f"last telemetry: {self.telemetry.describe()}"
        )

    def _send_rc(self, channels: Sequence[int]) -> None:
        if self._socket is None:
            raise ScenarioError("MAVLink socket is not open")
        if not 8 <= len(channels) <= 18:
            raise ScenarioError(
                "RC_CHANNELS_OVERRIDE requires between 8 and 18 channel values; "
                f"got {len(channels)}"
            )
        message = self._encoder.rc_channels_override_encode(
            TARGET_SYSTEM_ID, TARGET_COMPONENT_ID, *channels
        )
        self._socket.sendto(message.pack(self._encoder), self.destination)

    def _receive_pending(self) -> None:
        if self._socket is None:
            return
        while True:
            try:
                payload, _address = self._socket.recvfrom(4096)
            except BlockingIOError:
                return
            for byte in payload:
                message = self._parser.parse_char(bytes([byte]))
                if message is not None:
                    previous_state = self.telemetry.state
                    if self.telemetry.consume(message):
                        state_changed = self.telemetry.state != previous_state
                        self._phase(
                            self.telemetry.describe(),
                            color=ANSI_BOLD_CYAN if state_changed else None,
                        )

    def _send_for(self, channels: Sequence[int], duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self._send_rc(channels)
            self._receive_pending()
            time.sleep(self.period_s)

    def _cleanup(self) -> None:
        if self._socket is None:
            return
        try:
            if not self._completed and not self._airborne:
                self._phase("Sending final ground-safe disarm command")
                self._send_for(MANUAL_DISARMED, 0.5)
            elif not self._completed:
                self._phase(
                    "Stopping RC while airborne; bt-app communication failsafe must recover"
                )
        except OSError:
            pass
        finally:
            self._socket.close()
            self._socket = None

    @staticmethod
    def _phase(message: str, color: str | None = None) -> None:
        line = f"{time.strftime('%H:%M:%S')} - {message}"
        color = color or ANSI_BOLD_YELLOW
        line = f"{color}{line}{ANSI_RESET}"
        print(line, flush=True)

#!/usr/bin/env python3
"""Exercise the complete RC override takeoff and landing flow against SITL."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
import socket
import sys
import time
from typing import Any, Callable, Sequence

# The extended RC_CHANNELS_OVERRIDE fields are only available in MAVLink 2.
os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil

mavutil.set_dialect("common")

try:
    from joy_simulation.mavlink_rc_scenario import MavlinkRcScenarioBase
except ModuleNotFoundError:  # direct script execution
    from mavlink_rc_scenario import MavlinkRcScenarioBase  # type: ignore[no-redef]


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
APP_COMPONENT_ID = mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1
JOYSTICK_SYSTEM_ID = 255
JOYSTICK_COMPONENT_ID = mavutil.mavlink.MAV_COMP_ID_MISSIONPLANNER
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
ANSI_RESET = "\033[0m"

SCENARIO_BANNER = """\
==============================================================================
bt-app RC Override SITL Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Wait for bt-app MAVLink telemetry.
  2. Arm the drone in MANUAL with low throttle.
  3. Request automatic takeoff and wait for ALT_HOLD.
  4. Hold altitude for the configured duration.
  5. Switch to MANUAL and descend with the configured throttle.
  6. Confirm touchdown, disarm, and verify IDLE.

Safety behavior:
  Before takeoff, failures send a ground-safe disarm command.
  While airborne, failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class ScenarioError(RuntimeError):
    """Raised when the SITL scenario cannot complete safely."""


def rc_channels(
    *,
    throttle: int = RC_MIN,
    armed: bool = False,
    manual: bool = False,
    auto_takeoff: bool = False,
    tracker_mode: bool = False,
) -> tuple[int, ...]:
    """Build the eight application joystick channels."""

    channels = [RC_MID, RC_MID, throttle, RC_MID, RC_MIN, RC_MAX, RC_MIN, RC_MIN, RC_MIN]
    channels[ARM] = RC_MAX if armed else RC_MIN
    channels[MANUAL] = RC_MIN if manual else RC_MAX
    channels[AUTO_TAKEOFF] = RC_MAX if auto_takeoff else RC_MIN
    channels[TRACKER_MODE] = RC_MAX if tracker_mode else RC_MIN
    return tuple(channels)


NEUTRAL_DISARMED = rc_channels()
ARM_IN_MANUAL = rc_channels(armed=True, manual=True)
AUTO_TAKEOFF_ARMED = rc_channels(armed=True, auto_takeoff=True)
# Centered throttle requests no altitude-setpoint change in ALT_HOLD and also
# satisfies the MANUAL -> ALT_HOLD state-machine guard (throttle > 1050).
ALT_HOLD_ARMED = rc_channels(armed=True, throttle=RC_MID)
MANUAL_DESCENT_ARMED = rc_channels(armed=True, manual=True, throttle=1600)
MANUAL_DISARMED = rc_channels(manual=True, throttle=RC_MIN)


@dataclass
class Telemetry:
    state: int | None = None
    armed: bool = False
    altitude_m: float | None = None
    altitude_samples: int = 0

    def describe(self) -> str:
        state = STATE_NAMES.get(self.state, str(self.state))
        altitude = "unknown" if self.altitude_m is None else f"{self.altitude_m:.2f} m"
        return f"state={state} armed={self.armed} altitude={altitude}"

    def consume(self, message: Any) -> bool:
        """Consume application telemetry; return whether observable state changed."""

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
                & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
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


class MavlinkRcScenario:
    def __init__(
        self,
        *,
        destination: tuple[str, int],
        listen: tuple[str, int],
        rate_hz: float,
        state_timeout_s: float,
        landing_timeout_s: float,
        touchdown_altitude_m: float,
        alt_hold_duration_s: float = 15.0,
        descent_throttle: int = 1600,
    ) -> None:
        self.destination = destination
        self.listen = listen
        self.period_s = 1.0 / rate_hz
        self.state_timeout_s = state_timeout_s
        self.landing_timeout_s = landing_timeout_s
        self.touchdown_altitude_m = touchdown_altitude_m
        self.alt_hold_duration_s = alt_hold_duration_s
        self.manual_descent_channels = rc_channels(
            armed=True,
            manual=True,
            throttle=descent_throttle,
        )
        self.telemetry = Telemetry()
        self._socket: socket.socket | None = None
        self._encoder = mavutil.mavlink.MAVLink(
            None,
            srcSystem=JOYSTICK_SYSTEM_ID,
            srcComponent=JOYSTICK_COMPONENT_ID,
        )
        self._parser = mavutil.mavlink.MAVLink(None)
        self._parser.robust_parsing = True
        self._airborne = False
        self._completed = False

    def run(self) -> None:
        self._print_banner()
        self._open()
        try:
            self._phase("Waiting for bt-app telemetry")
            self._wait_for(
                NEUTRAL_DISARMED,
                lambda: self.telemetry.state is not None,
                self.state_timeout_s,
                "application heartbeat",
            )

            self._phase("Arming in MANUAL mode")
            self._wait_for_state(
                ARM_IN_MANUAL,
                STATE_MANUAL,
                self.state_timeout_s,
            )

            self._phase("Requesting automatic takeoff from MANUAL")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_TAKEOFF,
                self.state_timeout_s,
            )
            self._airborne = True

            self._phase("Waiting for takeoff completion and ALT_HOLD")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_ALT_HOLD,
                self.landing_timeout_s,
            )

            start_altitude = self.telemetry.altitude_m
            if start_altitude is None:
                raise ScenarioError("ALT_HOLD entered without altitude telemetry")

            self._phase(
                f"Holding ALT_HOLD for {self.alt_hold_duration_s:.1f} seconds"
            )
            self._send_for(ALT_HOLD_ARMED, self.alt_hold_duration_s)
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    "Vehicle left ALT_HOLD during dwell; "
                    f"last telemetry: {self.telemetry.describe()}"
                )

            descent_throttle = self.manual_descent_channels[THROTTLE]
            self._phase(
                "Switching to MANUAL and commanding slow descent "
                f"at throttle {descent_throttle}"
            )
            self._wait_for_state(
                self.manual_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            descent_threshold = max(
                self.touchdown_altitude_m,
                start_altitude - 0.20,
            )
            self._wait_for(
                self.manual_descent_channels,
                lambda: (
                    self.telemetry.altitude_m is not None
                    and self.telemetry.altitude_m <= descent_threshold
                ),
                self.state_timeout_s,
                f"altitude below {descent_threshold:.2f} m",
            )

            self._phase("Waiting for touchdown")
            consecutive_touchdown_samples = 0
            last_sample_count = self.telemetry.altitude_samples

            def touchdown_confirmed() -> bool:
                nonlocal consecutive_touchdown_samples, last_sample_count
                if self.telemetry.altitude_samples == last_sample_count:
                    return consecutive_touchdown_samples >= 3
                last_sample_count = self.telemetry.altitude_samples
                altitude = self.telemetry.altitude_m
                if altitude is not None and altitude <= self.touchdown_altitude_m:
                    consecutive_touchdown_samples += 1
                else:
                    consecutive_touchdown_samples = 0
                return consecutive_touchdown_samples >= 3

            self._wait_for(
                self.manual_descent_channels,
                touchdown_confirmed,
                self.landing_timeout_s,
                f"three touchdown samples <= {self.touchdown_altitude_m:.2f} m",
            )

            self._airborne = False
            self._phase("Disarming and waiting for IDLE")
            self._wait_for(
                MANUAL_DISARMED,
                lambda: self.telemetry.state == STATE_IDLE and not self.telemetry.armed,
                self.state_timeout_s,
                "IDLE with armed flag cleared",
            )
            self._send_for(MANUAL_DISARMED, 0.5)
            self._completed = True
            self._phase("Scenario completed successfully")
        finally:
            self._cleanup()

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

    def _wait_for_state(
        self,
        channels: Sequence[int],
        expected_state: int,
        timeout_s: float,
    ) -> None:
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
        message = self._encoder.rc_channels_override_encode(
            TARGET_SYSTEM_ID,
            TARGET_COMPONENT_ID,
            *channels,
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
    def _print_banner() -> None:
        print(SCENARIO_BANNER, flush=True)

    @staticmethod
    def _phase(message: str, color: str | None = None) -> None:
        line = f"{time.strftime('%H:%M:%S')} - {message}"
        if color:
            line = f"{color}{line}{ANSI_RESET}"
        print(line, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=SCENARIO_BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--destination-host", default="127.0.0.1")
    parser.add_argument("--destination-port", type=int, default=14560)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=14550)
    parser.add_argument("--rate-hz", type=float, default=50.0)
    parser.add_argument("--state-timeout", type=float, default=20.0)
    parser.add_argument("--landing-timeout", type=float, default=60.0)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    parser.add_argument("--alt-hold-duration", type=float, default=15.0)
    parser.add_argument(
        "--descent-throttle",
        type=int,
        default=1600,
        help="fixed MANUAL landing throttle; raise cautiously for a slower descent",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0:
        raise SystemExit("--rate-hz must be greater than zero")
    if args.state_timeout <= 0 or args.landing_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if args.touchdown_altitude < 0:
        raise SystemExit("--touchdown-altitude cannot be negative")
    if args.alt_hold_duration < 0:
        raise SystemExit("--alt-hold-duration cannot be negative")
    if not RC_MIN <= args.descent_throttle <= 1650:
        raise SystemExit("--descent-throttle must be between 1000 and 1650")

    scenario = MavlinkRcScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.landing_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=args.alt_hold_duration,
        descent_throttle=args.descent_throttle,
    )
    try:
        scenario.run()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except ScenarioError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

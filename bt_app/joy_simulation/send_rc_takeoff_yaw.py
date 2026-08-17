#!/usr/bin/env python3
"""Fixed automatic takeoff, 180-degree yaw, descent, and landing scenario."""

from __future__ import annotations

import math
import sys
import time
from typing import Any

from mavlink_rc_scenario import (
    ALT_HOLD_ARMED,
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    ARM_IN_MANUAL,
    AUTO_TAKEOFF_ARMED,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    STATE_TAKEOFF,
    MavlinkRcScenarioBase,
    ScenarioError,
    Telemetry,
    YAW,
    rc_channels,
)

   


# Flight settings are deliberately fixed: this script is a repeatable
# scenario, not a general-purpose command-line tool.
DESTINATION = ("127.0.0.1", 14560)
LISTEN = ("0.0.0.0", 14550)
RATE_HZ = 50.0
STATE_TIMEOUT_S = 20.0
FLIGHT_TIMEOUT_S = 120.0
TAKEOFF_ALTITUDE_M = 5.0
TURN_ANGLE_DEG = 180.0
CW_YAW_RC = 1900
CCW_YAW_RC = 1100
YAW_CENTER_PAUSE_S = 1.0
TURN_TIMEOUT_S = 60.0
DESCENT_RATE_M_S = 0.5
DESCENT_VELOCITY_KP = 15.0
DESCENT_HOVER_THROTTLE = 1660
DESCENT_MIN_THROTTLE = 1500
DESCENT_MAX_THROTTLE = 1800
TOUCHDOWN_ALTITUDE_M = 0.15


class ScenarioTelemetry(Telemetry):
    """Track yaw and vertical speed in addition to base state telemetry."""

    def __init__(self) -> None:
        super().__init__()
        self.yaw_deg: float | None = None
        self.vertical_speed_m_s: float | None = None
        self.attitude_samples = 0

    def consume(self, message: Any) -> bool:
        changed = super().consume(message)
        if (
            int(message.get_srcSystem()) != APP_SYSTEM_ID
            or int(message.get_srcComponent()) != APP_COMPONENT_ID
        ):
            return changed
        if message.get_type() == "ATTITUDE":
            yaw = math.degrees(float(message.yaw)) % 360.0
            changed = changed or yaw != self.yaw_deg
            self.yaw_deg = yaw
            self.attitude_samples += 1
        elif message.get_type() == "GLOBAL_POSITION_INT" and hasattr(message, "vz"):
            # MAVLink vz is positive down; positive is up in this scenario.
            speed = -float(message.vz) / 100.0
            changed = changed or speed != self.vertical_speed_m_s
            self.vertical_speed_m_s = speed
        return changed


def yaw_channels(yaw_rc: int) -> tuple[int, ...]:
    channels = list(ALT_HOLD_ARMED)
    channels[YAW] = yaw_rc
    return tuple(channels)


class TakeoffYawScenario(MavlinkRcScenarioBase):
    """Arm, take off to 10 m, yaw both directions, land, and disarm."""

    def __init__(self) -> None:
        super().__init__(
            destination=DESTINATION,
            listen=LISTEN,
            rate_hz=RATE_HZ,
            state_timeout_s=STATE_TIMEOUT_S,
            landing_timeout_s=FLIGHT_TIMEOUT_S,
            touchdown_altitude_m=TOUCHDOWN_ALTITUDE_M,
        )
        self.telemetry = ScenarioTelemetry()

    def run(self) -> None:
        self._open()
        try:
            self._phase("Waiting for bt-app telemetry")
            self._wait_for(
                NEUTRAL_DISARMED,
                lambda: self.telemetry.state is not None,
                STATE_TIMEOUT_S,
                "application heartbeat",
            )
            self._phase("Arming in MANUAL")
            self._wait_for_state(ARM_IN_MANUAL, STATE_MANUAL, STATE_TIMEOUT_S)

            self._phase(f"Automatic takeoff to {TAKEOFF_ALTITUDE_M:.0f} m")
            self._wait_for_state(AUTO_TAKEOFF_ARMED, STATE_TAKEOFF, STATE_TIMEOUT_S)
            self._airborne = True
            self._wait_for(
                AUTO_TAKEOFF_ARMED,
                lambda: self.telemetry.state == STATE_ALT_HOLD
                and (self.telemetry.altitude_m or 0.0) >= TAKEOFF_ALTITUDE_M,
                FLIGHT_TIMEOUT_S,
                f"ALT_HOLD at {TAKEOFF_ALTITUDE_M:.0f} m",
            )
            self._wait_for_settled_alt_hold()

            self._command_turn("clockwise", CW_YAW_RC)
            self._send_for(ALT_HOLD_ARMED, YAW_CENTER_PAUSE_S)
            self._command_turn("counter-clockwise", CCW_YAW_RC)
            self._send_for(ALT_HOLD_ARMED, YAW_CENTER_PAUSE_S)

            self._phase(f"Switching to MANUAL and descending at {DESCENT_RATE_M_S:.1f} m/s")
            self._wait_for_state(
                rc_channels(armed=True, manual=True, throttle=DESCENT_HOVER_THROTTLE),
                STATE_MANUAL,
                2,
            )
            self._descend_to_touchdown()
            self._airborne = False

            self._phase("Landing and disarming")
            self._wait_for(
                MANUAL_DISARMED,
                lambda: self.telemetry.state == STATE_IDLE and not self.telemetry.armed,
                STATE_TIMEOUT_S,
                "IDLE with armed flag cleared",
            )
            self._send_for(MANUAL_DISARMED, 0.5)
            self._completed = True
            self._phase("Scenario completed successfully")
        finally:
            self._cleanup()

    def _wait_for_settled_alt_hold(self) -> None:
        self._phase("Waiting for ALT_HOLD to settle")
        last_samples = self.telemetry.altitude_samples
        stable_samples = 0

        def settled() -> bool:
            nonlocal last_samples, stable_samples
            if self.telemetry.altitude_samples == last_samples:
                return stable_samples >= 3
            last_samples = self.telemetry.altitude_samples
            speed = self.telemetry.vertical_speed_m_s
            stable_samples = stable_samples + 1 if speed is not None and abs(speed) <= 0.25 else 0
            return stable_samples >= 3

        self._wait_for(ALT_HOLD_ARMED, settled, FLIGHT_TIMEOUT_S, "settled ALT_HOLD")

    def _command_turn(self, direction: str, yaw_rc: int) -> None:
        self._phase(f"Commanding {TURN_ANGLE_DEG:.0f} degree {direction} yaw")
        deadline = time.monotonic() + TURN_TIMEOUT_S
        previous = self.telemetry.yaw_deg
        samples = self.telemetry.attitude_samples
        turned = 0.0
        channels = yaw_channels(yaw_rc)
        while time.monotonic() < deadline:
            self._send_rc(channels)
            self._receive_pending()
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(f"Vehicle left ALT_HOLD during {direction} yaw")
            if self.telemetry.attitude_samples != samples:
                samples = self.telemetry.attitude_samples
                current = self.telemetry.yaw_deg
                if previous is not None and current is not None:
                    turned += (current - previous + 180.0) % 360.0 - 180.0
                    if abs(turned) >= TURN_ANGLE_DEG:
                        self._phase(f"{direction} yaw complete ({turned:+.1f} deg)")
                        return
                previous = current
            time.sleep(min(0.005, self.period_s))
        raise ScenarioError(f"Timed out during {direction} yaw ({turned:+.1f} deg)")

    def _descent_channels(self) -> tuple[int, ...]:
        speed = self.telemetry.vertical_speed_m_s
        if speed is None:
            throttle = DESCENT_HOVER_THROTTLE - 40
        else:
            throttle = DESCENT_HOVER_THROTTLE + DESCENT_VELOCITY_KP * (
                -DESCENT_RATE_M_S - speed
            )
        throttle = int(max(DESCENT_MIN_THROTTLE, min(DESCENT_MAX_THROTTLE, throttle)))
        return rc_channels(armed=True, manual=True, throttle=throttle)

    def _descend_to_touchdown(self) -> None:
        deadline = time.monotonic() + FLIGHT_TIMEOUT_S
        consecutive = 0
        while time.monotonic() < deadline:
            self._send_rc(self._descent_channels())
            self._receive_pending()
            if (
                self.telemetry.state == STATE_MANUAL
                and self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m <= TOUCHDOWN_ALTITUDE_M
            ):
                consecutive += 1
                if consecutive >= 3:
                    self._phase("Touchdown detected")
                    return
            else:
                consecutive = 0
            time.sleep(self.period_s)
        raise ScenarioError("Timed out waiting for touchdown")


def main() -> int:
    try:
        TakeoffYawScenario().run()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except ScenarioError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

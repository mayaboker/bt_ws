#!/usr/bin/env python3
"""Manual takeoff to 10 m followed by a fixed right/left roll maneuver."""

from __future__ import annotations

import sys
import time
import os

os.environ.setdefault("MAVLINK20", "1")

try:
    from bt_app.joy_simulation.mavlink_rc_scenario import (
        ALT_HOLD_ARMED,
        ARM_IN_MANUAL,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        ROLL,
        STATE_ALT_HOLD,
        STATE_IDLE,
        STATE_MANUAL,
        MavlinkRcScenarioBase,
        ScenarioError,
        rc_channels,
    )
except ModuleNotFoundError:
    from mavlink_rc_scenario import (  # type: ignore[no-redef]
        ALT_HOLD_ARMED,
        ARM_IN_MANUAL,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        ROLL,
        STATE_ALT_HOLD,
        STATE_IDLE,
        STATE_MANUAL,
        MavlinkRcScenarioBase,
        ScenarioError,
        rc_channels,
    )


TARGET_ALTITUDE_M = 10.0
RATE_HZ = 50.0
STATE_TIMEOUT_S = 20.0
FLIGHT_TIMEOUT_S = 90.0
ASCENT_START_THROTTLE = 1600
ASCENT_HOVER_THROTTLE = 1660
ASCENT_MAX_THROTTLE = 1680
ASCENT_KP = 18.0
ASCENT_KI = 1.5
ASCENT_KD = 25.0
ASCENT_INTEGRAL_LIMIT_M_S = 20.0
ROLL_RIGHT_RC = 1600
ROLL_LEFT_RC = 1400
ROLL_DURATION_S = 3.0
STABILIZE_DURATION_S = 5.0
TOUCHDOWN_ALTITUDE_M = 0.15
DESCENT_START_THROTTLE = 1600
DESCENT_HOVER_THROTTLE = 1660
DESCENT_MIN_THROTTLE = 1500
DESCENT_MAX_THROTTLE = 1800
DESCENT_KP = 10.0
DESCENT_KI = 1.0
DESCENT_KD = 25.0
DESCENT_INTEGRAL_LIMIT_M_S = 20.0


def roll_channels(roll_rc: int) -> tuple[int, ...]:
    channels = list(ALT_HOLD_ARMED)
    channels[ROLL] = roll_rc
    return tuple(channels)


class TakeoffRollScenario(MavlinkRcScenarioBase):
    """Arm, manually climb to 10 m, roll right/left, and finish centered."""

    def __init__(self) -> None:
        super().__init__(
            destination=("127.0.0.1", 14560),
            listen=("0.0.0.0", 14550),
            rate_hz=RATE_HZ,
            state_timeout_s=STATE_TIMEOUT_S,
            landing_timeout_s=FLIGHT_TIMEOUT_S,
            touchdown_altitude_m=TOUCHDOWN_ALTITUDE_M,
        )

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

            self._airborne = True
            self._phase(f"Manual climb to {TARGET_ALTITUDE_M:.0f} m")
            self._climb_to_target()

            self._phase("Entering ALT_HOLD at target altitude")
            self._wait_for_state(ALT_HOLD_ARMED, STATE_ALT_HOLD, STATE_TIMEOUT_S)

            self._phase("Roll right for 3 seconds")
            self._send_for(roll_channels(ROLL_RIGHT_RC), ROLL_DURATION_S)
            self._phase("Stabilizing roll")
            self._send_for(ALT_HOLD_ARMED, STABILIZE_DURATION_S)
            self._phase("Roll left for 3 seconds")
            self._send_for(roll_channels(ROLL_LEFT_RC), ROLL_DURATION_S)
            self._phase("Centering roll and stabilizing")
            self._send_for(ALT_HOLD_ARMED, STABILIZE_DURATION_S)

            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    "Vehicle left ALT_HOLD during roll maneuver; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            self._phase("Switching to MANUAL for stabilized descent")
            self._wait_for_state(
                rc_channels(armed=True, manual=True, throttle=DESCENT_START_THROTTLE),
                STATE_MANUAL,
                STATE_TIMEOUT_S,
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

    def _climb_to_target(self) -> None:
        """Climb with altitude-error PID control, starting at 1600 PWM."""
        deadline = time.monotonic() + FLIGHT_TIMEOUT_S
        next_send = 0.0
        last_control_at = time.monotonic()
        last_altitude: float | None = None
        integral = 0.0
        first_command = True
        while time.monotonic() < deadline:
            now = time.monotonic()
            self._receive_pending()
            if now >= next_send:
                dt = max(0.001, now - last_control_at)
                altitude = self.telemetry.altitude_m
                if first_command or altitude is None:
                    throttle = ASCENT_START_THROTTLE
                else:
                    error = TARGET_ALTITUDE_M - altitude
                    integral = max(
                        -ASCENT_INTEGRAL_LIMIT_M_S,
                        min(ASCENT_INTEGRAL_LIMIT_M_S, integral + error * dt),
                    )
                    climb_rate = 0.0 if last_altitude is None else (altitude - last_altitude) / dt
                    throttle = ASCENT_HOVER_THROTTLE + (
                        ASCENT_KP * error
                        + ASCENT_KI * integral
                        - ASCENT_KD * climb_rate
                    )
                    throttle = int(max(ASCENT_START_THROTTLE, min(ASCENT_MAX_THROTTLE, throttle)))
                self._send_rc(rc_channels(armed=True, manual=True, throttle=throttle))
                next_send = now + self.period_s
                last_control_at = now
                last_altitude = altitude
                first_command = False
            if (
                self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m >= TARGET_ALTITUDE_M
            ):
                self._phase(f"Reached {self.telemetry.altitude_m:.2f} m")
                return
            time.sleep(min(0.005, self.period_s))
        raise ScenarioError(
            f"Timed out climbing to {TARGET_ALTITUDE_M:.1f} m; "
            f"last telemetry: {self.telemetry.describe()}"
        )

    def _descend_to_touchdown(self) -> None:
        """Descend in MANUAL with altitude feedback and confirm touchdown."""
        deadline = time.monotonic() + FLIGHT_TIMEOUT_S
        next_send = 0.0
        last_control_at = time.monotonic()
        last_altitude: float | None = None
        integral = 0.0
        first_command = True
        consecutive_touchdown = 0

        while time.monotonic() < deadline:
            now = time.monotonic()
            self._receive_pending()
            if now >= next_send:
                dt = max(0.001, now - last_control_at)
                altitude = self.telemetry.altitude_m
                if first_command or altitude is None:
                    throttle = DESCENT_START_THROTTLE
                else:
                    error = TOUCHDOWN_ALTITUDE_M - altitude
                    integral = max(
                        -DESCENT_INTEGRAL_LIMIT_M_S,
                        min(DESCENT_INTEGRAL_LIMIT_M_S, integral + error * dt),
                    )
                    descent_rate = (
                        0.0
                        if last_altitude is None
                        else (altitude - last_altitude) / dt
                    )
                    throttle = DESCENT_HOVER_THROTTLE + (
                        DESCENT_KP * error
                        + DESCENT_KI * integral
                        - DESCENT_KD * descent_rate
                    )
                    throttle = int(
                        max(DESCENT_MIN_THROTTLE, min(DESCENT_MAX_THROTTLE, throttle))
                    )
                self._send_rc(rc_channels(armed=True, manual=True, throttle=throttle))
                next_send = now + self.period_s
                last_control_at = now
                last_altitude = altitude
                first_command = False

            if (
                self.telemetry.state == STATE_MANUAL
                and self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m <= TOUCHDOWN_ALTITUDE_M
            ):
                consecutive_touchdown += 1
                if consecutive_touchdown >= 3:
                    self._phase("Touchdown detected")
                    return
            else:
                consecutive_touchdown = 0
            time.sleep(min(0.005, self.period_s))

        raise ScenarioError(
            "Timed out waiting for touchdown; "
            f"last telemetry: {self.telemetry.describe()}"
        )


def main() -> int:
    try:
        TakeoffRollScenario().run()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except ScenarioError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

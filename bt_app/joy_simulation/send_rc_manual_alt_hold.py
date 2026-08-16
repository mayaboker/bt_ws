#!/usr/bin/env python3
"""Manual climb to 5 m, ALT_HOLD dwell, manual descent, and disarm."""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("MAVLINK20", "1")

try:
    from joy_simulation.mavlink_rc_scenario import (
        ALT_HOLD_ARMED,
        ARM_IN_MANUAL,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        STATE_ALT_HOLD,
        STATE_IDLE,
        STATE_MANUAL,
        THROTTLE,
        MavlinkRcScenarioBase,
        ScenarioError,
        rc_channels,
    )
except ModuleNotFoundError:  # direct script execution
    from mavlink_rc_scenario import (  # type: ignore[no-redef]
        ALT_HOLD_ARMED,
        ARM_IN_MANUAL,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        STATE_ALT_HOLD,
        STATE_IDLE,
        STATE_MANUAL,
        THROTTLE,
        MavlinkRcScenarioBase,
        ScenarioError,
        rc_channels,
    )


SCENARIO_BANNER = """\
==============================================================================
bt-app MANUAL Climb / ALT_HOLD SITL Scenario
==============================================================================
Flight flow:
  1. Arm in MANUAL with low throttle.
  2. Ramp MANUAL throttle until 5 m altitude.
  3. Switch to centered-throttle ALT_HOLD.
  4. Hold ALT_HOLD for 10 seconds.
  5. Switch to MANUAL and descend.
  6. Confirm touchdown and disarm.

Safety behavior:
  Before takeoff, failures send a ground-safe disarm command.
  While airborne, failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class ManualClimbScenario(MavlinkRcScenarioBase):
    """Fixed manual takeoff, altitude hold, descent, and disarm flow."""

    def __init__(
        self,
        *,
        destination: tuple[str, int] = ("127.0.0.1", 14560),
        listen: tuple[str, int] = ("0.0.0.0", 14550),
        rate_hz: float = 50.0,
        state_timeout_s: float = 20.0,
        landing_timeout_s: float = 90.0,
        touchdown_altitude_m: float = 0.15,
        target_altitude_m: float = 5.0,
        alt_hold_duration_s: float = 10.0,
        ascent_start_throttle: int = 1500,
        ascent_max_throttle: int = 1680,
        ascent_ramp_pwm_s: float = 10.0,
        descent_throttle: int = 1550,
    ) -> None:
        super().__init__(
            destination=destination,
            listen=listen,
            rate_hz=rate_hz,
            state_timeout_s=state_timeout_s,
            landing_timeout_s=landing_timeout_s,
            touchdown_altitude_m=touchdown_altitude_m,
        )
        self.target_altitude_m = target_altitude_m
        self.alt_hold_duration_s = alt_hold_duration_s
        self.ascent_start_throttle = ascent_start_throttle
        self.ascent_max_throttle = ascent_max_throttle
        self.ascent_ramp_pwm_s = ascent_ramp_pwm_s
        self.manual_descent_channels = rc_channels(
            armed=True,
            manual=True,
            throttle=descent_throttle,
        )

    @staticmethod
    def _print_banner() -> None:
        print(SCENARIO_BANNER, flush=True)

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
            self._wait_for_state(ARM_IN_MANUAL, STATE_MANUAL, self.state_timeout_s)

            self._airborne = True
            self._phase(f"Climbing in MANUAL to {self.target_altitude_m:.1f} m")
            self._climb_to_target()

            self._phase("Switching from MANUAL to ALT_HOLD")
            self._wait_for_state(ALT_HOLD_ARMED, STATE_ALT_HOLD, self.state_timeout_s)
            self._phase(f"Holding ALT_HOLD for {self.alt_hold_duration_s:.1f} seconds")
            self._send_for(ALT_HOLD_ARMED, self.alt_hold_duration_s)
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    "Vehicle left ALT_HOLD during dwell; "
                    f"last telemetry: {self.telemetry.describe()}"
                )

            self._phase(
                "Switching to MANUAL and descending "
                f"at throttle {self.manual_descent_channels[THROTTLE]}"
            )
            self._wait_for_state(
                self.manual_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            self._wait_for_touchdown()

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

    def _climb_to_target(self) -> None:
        deadline = time.monotonic() + self.landing_timeout_s
        started_at = time.monotonic()
        next_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            throttle = min(
                self.ascent_max_throttle,
                int(self.ascent_start_throttle + self.ascent_ramp_pwm_s * (now - started_at)),
            )
            if now >= next_send:
                self._send_rc(rc_channels(armed=True, manual=True, throttle=throttle))
                next_send = now + self.period_s
            self._receive_pending()
            if (
                self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m >= self.target_altitude_m
            ):
                self._phase(
                    f"Reached {self.telemetry.altitude_m:.2f} m and throttle {throttle}"
                )
                return
            time.sleep(min(0.005, self.period_s))
        raise ScenarioError(
            f"Timed out after {self.landing_timeout_s:.1f}s climbing to "
            f"{self.target_altitude_m:.2f} m; last telemetry: "
            f"{self.telemetry.describe()}"
        )

    def _wait_for_touchdown(self) -> None:
        self._phase("Waiting for touchdown")
        consecutive_samples = 0
        last_sample_count = self.telemetry.altitude_samples

        def touchdown_confirmed() -> bool:
            nonlocal consecutive_samples, last_sample_count
            if self.telemetry.altitude_samples == last_sample_count:
                return consecutive_samples >= 3
            last_sample_count = self.telemetry.altitude_samples
            if (
                self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m <= self.touchdown_altitude_m
            ):
                consecutive_samples += 1
            else:
                consecutive_samples = 0
            return consecutive_samples >= 3

        self._wait_for(
            self.manual_descent_channels,
            touchdown_confirmed,
            self.landing_timeout_s,
            f"three touchdown samples <= {self.touchdown_altitude_m:.2f} m",
        )


def main() -> int:
    try:
        ManualClimbScenario().run()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except ScenarioError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

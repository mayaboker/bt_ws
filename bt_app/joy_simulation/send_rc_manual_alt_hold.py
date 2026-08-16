#!/usr/bin/env python3
"""Fly a MANUAL climb, ALT_HOLD dwell, and MANUAL landing against SITL."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

from send_rc import (
    ALT_HOLD_ARMED,
    ARM_IN_MANUAL,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    RC_MAX,
    RC_MIN,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    THROTTLE,
    MavlinkRcScenario,
    ScenarioError,
    rc_channels,
)

SCENARIO_BANNER = """\
==============================================================================
bt-app MANUAL Climb / ALT_HOLD SITL Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Wait for bt-app MAVLink telemetry and arm in MANUAL.
  2. Increase MANUAL throttle slowly until the target altitude is reached.
  3. Center the throttle and switch from MANUAL to ALT_HOLD.
  4. Hold altitude for the configured duration.
  5. Switch back to MANUAL and descend with fixed throttle.
  6. Confirm touchdown, disarm, and verify IDLE.

Safety behavior:
  Before takeoff, failures send a ground-safe disarm command.
  While airborne, failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class ManualClimbScenario(MavlinkRcScenario):
    def __init__(
        self,
        *,
        target_altitude_m: float = 3.0,
        ascent_start_throttle: int = 1500,
        ascent_max_throttle: int = 1680,
        ascent_ramp_pwm_s: float = 10.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_altitude_m = target_altitude_m
        self.ascent_start_throttle = ascent_start_throttle
        self.ascent_max_throttle = ascent_max_throttle
        self.ascent_ramp_pwm_s = ascent_ramp_pwm_s

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
            self._phase(
                "Climbing in MANUAL toward "
                f"{self.target_altitude_m:.2f} m with increasing throttle"
            )
            self._climb_to_target()

            self._phase("Switching from MANUAL to ALT_HOLD")
            self._wait_for_state(
                ALT_HOLD_ARMED,
                STATE_ALT_HOLD,
                self.state_timeout_s,
            )
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
            self._wait_for_touchdown()

            self._airborne = False
            self._phase("Disarming and waiting for IDLE")
            self._wait_for(
                MANUAL_DISARMED,
                lambda: self.telemetry.state == STATE_IDLE
                and not self.telemetry.armed,
                self.state_timeout_s,
                "IDLE with armed flag cleared",
            )
            self._send_for(MANUAL_DISARMED, 0.5)
            self._completed = True
            self._phase("Scenario completed successfully")
        finally:
            self._cleanup()

    @staticmethod
    def _print_banner() -> None:
        print(SCENARIO_BANNER, flush=True)

    def _climb_to_target(self) -> None:
        deadline = time.monotonic() + self.landing_timeout_s
        started_at = time.monotonic()
        next_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            throttle = min(
                self.ascent_max_throttle,
                int(
                    self.ascent_start_throttle
                    + self.ascent_ramp_pwm_s * (now - started_at)
                ),
            )
            if now >= next_send:
                self._send_rc(
                    rc_channels(armed=True, manual=True, throttle=throttle)
                )
                next_send = now + self.period_s
            self._receive_pending()
            if (
                self.telemetry.altitude_m is not None
                and self.telemetry.altitude_m >= self.target_altitude_m
            ):
                self._phase(
                    f"Reached {self.telemetry.altitude_m:.2f} m "
                    f"and throttle {throttle}"
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
            altitude = self.telemetry.altitude_m
            if altitude is not None and altitude <= self.touchdown_altitude_m:
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
    parser.add_argument("--flight-timeout", type=float, default=90.0)
    parser.add_argument("--target-altitude", type=float, default=3.0)
    parser.add_argument("--ascent-start-throttle", type=int, default=1500)
    parser.add_argument("--ascent-max-throttle", type=int, default=1680)
    parser.add_argument("--ascent-ramp", type=float, default=10.0)
    parser.add_argument("--alt-hold-duration", type=float, default=30.0)
    parser.add_argument("--descent-throttle", type=int, default=1550)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0 or args.ascent_ramp <= 0:
        raise SystemExit("--rate-hz and --ascent-ramp must be greater than zero")
    if args.state_timeout <= 0 or args.flight_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if args.target_altitude <= args.touchdown_altitude:
        raise SystemExit("--target-altitude must be above --touchdown-altitude")
    if not RC_MIN <= args.ascent_start_throttle < args.ascent_max_throttle:
        raise SystemExit("invalid ascent throttle range")
    if not args.ascent_max_throttle <= RC_MAX:
        raise SystemExit("--ascent-max-throttle cannot exceed 2000")
    if not RC_MIN <= args.descent_throttle < 1600:
        raise SystemExit("--descent-throttle must be between 1000 and 1599")
    if args.alt_hold_duration < 0 or args.touchdown_altitude < 0:
        raise SystemExit("durations and altitudes cannot be negative")

    scenario = ManualClimbScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=args.alt_hold_duration,
        descent_throttle=args.descent_throttle,
        target_altitude_m=args.target_altitude,
        ascent_start_throttle=args.ascent_start_throttle,
        ascent_max_throttle=args.ascent_max_throttle,
        ascent_ramp_pwm_s=args.ascent_ramp,
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

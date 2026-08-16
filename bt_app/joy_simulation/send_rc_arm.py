#!/usr/bin/env python3
"""Arm and disarm a bt-app instance through MAVLink RC overrides."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

os.environ.setdefault("MAVLINK20", "1")

try:
    from joy_simulation.mavlink_rc_scenario import (
        ARM_IN_MANUAL,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        STATE_IDLE,
        STATE_MANUAL,
        MavlinkRcScenarioBase,
        ScenarioError,
    )
except ModuleNotFoundError:  # direct ``python joy_simulation/send_rc_arm.py``
    from mavlink_rc_scenario import (  # type: ignore[no-redef]
        ARM_IN_MANUAL,
        MANUAL_DISARMED,
        NEUTRAL_DISARMED,
        STATE_IDLE,
        STATE_MANUAL,
        MavlinkRcScenarioBase,
        ScenarioError,
    )


SCENARIO_BANNER = """\
==============================================================================
bt-app RC Override Arm Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Wait for bt-app MAVLink telemetry.
  2. Arm the drone in MANUAL with low throttle.
  3. Disarm and verify IDLE.

Safety behavior:
  Before takeoff, failures send a ground-safe disarm command.
  While airborne, failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class ArmScenario(MavlinkRcScenarioBase):
    """Scenario flow for an arm/disarm smoke test."""
    def _print_banner(self) -> None:
        print(SCENARIO_BANNER)

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


# Compatibility name for callers that imported the old class from this script.
MavlinkRcScenario = ArmScenario


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0 or args.state_timeout <= 0 or args.landing_timeout <= 0:
        raise SystemExit("rate and timeouts must be greater than zero")
    if args.touchdown_altitude < 0:
        raise SystemExit("--touchdown-altitude cannot be negative")

    scenario = ArmScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.landing_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
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

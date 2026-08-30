"""Scenario 02: take off to 10 m, visit two ALT_HOLD targets, then land."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from joy_scenarios.models import ColorMode, ScenarioConfig, ScenarioError
from joy_scenarios.scenario import JoyScenario


BANNER = """\
==============================================================================
bt-app ALT_HOLD Altitude Steps Scenario (SITL ONLY)
==============================================================================
Scripted joystick sequence:
  1. Arm in MANUAL and automatically take off to 10 m.
  2. In ALT_HOLD, move the altitude setpoint to 15 m and wait 10 seconds.
  3. Move the altitude setpoint to 8 m and wait 10 seconds.
  4. Switch to MANUAL, land, disarm, and verify IDLE.

WARNING: This scenario commands an armed aircraft and is intended for SITL.
=============================================================================="""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--destination-host", default="127.0.0.1")
    parser.add_argument("--destination-port", type=int, default=14560)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=14550)
    parser.add_argument("--rate-hz", type=float, default=50.0)
    parser.add_argument("--state-timeout", type=float, default=20.0)
    parser.add_argument("--flight-timeout", type=float, default=120.0)
    parser.add_argument("--takeoff-altitude", type=float, default=10.0)
    parser.add_argument("--high-altitude", type=float, default=15.0)
    parser.add_argument("--low-altitude", type=float, default=8.0)
    parser.add_argument("--hold-duration", type=float, default=10.0)
    parser.add_argument("--altitude-tolerance", type=float, default=0.3)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    parser.add_argument("--descent-throttle", type=int, default=1640)
    parser.add_argument(
        "--color",
        choices=tuple(mode.value for mode in ColorMode),
        default=ColorMode.AUTO.value,
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if min(args.takeoff_altitude, args.high_altitude, args.low_altitude) < 0:
        raise ValueError("altitude targets cannot be negative")
    if args.high_altitude <= args.takeoff_altitude:
        raise ValueError("--high-altitude must be above --takeoff-altitude")
    if args.low_altitude >= args.high_altitude:
        raise ValueError("--low-altitude must be below --high-altitude")
    if args.hold_duration < 0:
        raise ValueError("--hold-duration cannot be negative")
    if args.altitude_tolerance <= 0:
        raise ValueError("--altitude-tolerance must be greater than zero")
    if not 1000 <= args.descent_throttle <= 1650:
        raise ValueError("--descent-throttle must be between 1000 and 1650")


def config_from_args(args: argparse.Namespace) -> ScenarioConfig:
    validate_args(args)
    return ScenarioConfig(
        destination_host=args.destination_host,
        destination_port=args.destination_port,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        takeoff_timeout_s=args.flight_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        color=ColorMode(args.color),
    )


def run_scenario(config: ScenarioConfig, args: argparse.Namespace) -> None:
    with JoyScenario(config) as scenario:
        scenario.logger.phase(BANNER)
        scenario.wait_for_telemetry()
        scenario.arm_manual()
        scenario.auto_takeoff()
        scenario.wait_for_altitude(
            args.takeoff_altitude,
            tolerance_m=args.altitude_tolerance,
            timeout_s=args.flight_timeout,
        )
        scenario.change_altitude(
            args.high_altitude,
            tolerance_m=args.altitude_tolerance,
            timeout_s=args.flight_timeout,
        )
        scenario.hold_altitude(args.hold_duration)
        scenario.change_altitude(
            args.low_altitude,
            tolerance_m=args.altitude_tolerance,
            timeout_s=args.flight_timeout,
        )
        scenario.hold_altitude(args.hold_duration)
        scenario.land_manual(args.descent_throttle)
        scenario.disarm()
        scenario.complete()
        scenario.logger.phase("Scenario completed successfully")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = config_from_args(args)
        run_scenario(config, args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except (ScenarioError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

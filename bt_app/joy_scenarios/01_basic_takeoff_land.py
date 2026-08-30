"""Scenario 01: basic operator-like automatic takeoff and manual landing."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from joy_scenarios.models import ColorMode, ScenarioConfig, ScenarioError
from joy_scenarios.scenario import JoyScenario


BANNER = """\
==============================================================================
bt-app Basic Joystick Takeoff and Landing Scenario (SITL ONLY)
==============================================================================
This program acts like a scripted joystick operator:
  1. Discover bt-app telemetry.
  2. Arm in MANUAL with low throttle.
  3. Request automatic takeoff and wait for ALT_HOLD.
  4. Hold altitude, switch to MANUAL, and land with fixed throttle.
  5. Confirm touchdown, disarm, and verify IDLE.

WARNING: This scenario commands an armed aircraft. It is designed for SITL and
must not be connected to real hardware without a separate safety review.
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
    parser.add_argument("--takeoff-timeout", type=float, default=60.0)
    parser.add_argument("--landing-timeout", type=float, default=120.0)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    parser.add_argument("--alt-hold-duration", type=float, default=15.0)
    parser.add_argument(
        "--descent-throttle",
        type=int,
        default=1640,
        help=(
            "fixed MANUAL landing throttle, not a velocity command; "
            "raise cautiously for a slower descent"
        ),
    )
    parser.add_argument(
        "--color",
        choices=tuple(mode.value for mode in ColorMode),
        default=ColorMode.AUTO.value,
    )
    return parser


def config_from_args(args: argparse.Namespace) -> ScenarioConfig:
    if args.alt_hold_duration < 0:
        raise ValueError("--alt-hold-duration cannot be negative")
    if not 1000 <= args.descent_throttle <= 1650:
        raise ValueError("--descent-throttle must be between 1000 and 1650")
    return ScenarioConfig(
        destination_host=args.destination_host,
        destination_port=args.destination_port,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        takeoff_timeout_s=args.takeoff_timeout,
        landing_timeout_s=args.landing_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        color=ColorMode(args.color),
    )


def run_scenario(
    config: ScenarioConfig,
    *,
    alt_hold_duration_s: float,
    descent_throttle: int,
) -> None:
    with JoyScenario(config) as scenario:
        scenario.logger.phase(BANNER)
        scenario.wait_for_telemetry()
        scenario.arm_manual()
        scenario.auto_takeoff()
        scenario.hold_altitude(alt_hold_duration_s)
        scenario.land_manual(descent_throttle)
        scenario.disarm()
        scenario.complete()
        scenario.logger.phase("Scenario completed successfully")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = config_from_args(args)
        run_scenario(
            config,
            alt_hold_duration_s=args.alt_hold_duration,
            descent_throttle=args.descent_throttle,
        )
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except (ScenarioError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

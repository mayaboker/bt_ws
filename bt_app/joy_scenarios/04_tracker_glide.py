"""Scenario 04: acquire a tracker target and glide until TRACK exits."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from joy_scenarios.models import ColorMode, ScenarioConfig, ScenarioError
from joy_scenarios.scenario import JoyScenario


BANNER = """\
==============================================================================
bt-app Tracker Glide Scenario (SITL ONLY)
==============================================================================
Scripted joystick sequence:
  1. Arm in MANUAL and automatically take off to 10 m.
  2. Select tracker 1 and move the image-space target gate downward.
  3. Center the gate command, then pulse enable to lock and enter TRACK.
  4. Glide under tracker control until TRACK automatically returns to ALT_HOLD.
  5. On tracking timeout, disable the tracker and recover ALT_HOLD.
  6. Switch to MANUAL, land, disarm, and verify IDLE.

TRACK exit is used as the target-hit signal; bt-app exposes no separate impact
event. A timeout still performs a controlled landing but returns exit status 1.
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
    parser.add_argument("--altitude-tolerance", type=float, default=0.3)
    parser.add_argument("--tracker-entry-timeout", type=float, default=30.0)
    parser.add_argument("--tracking-timeout", type=float, default=60.0)
    parser.add_argument("--tracker-pulse-duration", type=float, default=0.25)
    parser.add_argument("--gate-roll", type=int, default=1500)
    parser.add_argument("--gate-pitch", type=int, default=1300)
    parser.add_argument("--gate-move-duration", type=float, default=2.0)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    parser.add_argument("--descent-throttle", type=int, default=1640)
    parser.add_argument(
        "--color",
        choices=tuple(mode.value for mode in ColorMode),
        default=ColorMode.AUTO.value,
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.takeoff_altitude < 0:
        raise ValueError("--takeoff-altitude cannot be negative")
    for name in (
        "altitude_tolerance",
        "tracker_entry_timeout",
        "tracking_timeout",
        "tracker_pulse_duration",
        "gate_move_duration",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    for name in ("gate_roll", "gate_pitch"):
        if not 1000 <= getattr(args, name) <= 2000:
            raise ValueError(f"--{name.replace('_', '-')} must be between 1000 and 2000")
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
    tracking_failure: ScenarioError | None = None
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
        try:
            scenario.move_target_gate(
                roll=args.gate_roll,
                pitch=args.gate_pitch,
                duration_s=args.gate_move_duration,
            )
            scenario.enter_tracker_1(
                entry_timeout_s=args.tracker_entry_timeout,
                pulse_duration_s=args.tracker_pulse_duration,
            )
            scenario.wait_for_tracker_exit(
                tracking_timeout_s=args.tracking_timeout
            )
        except ScenarioError as exc:
            tracking_failure = exc
            scenario.logger.failure(f"Tracker phase failed: {exc}")
            scenario.disable_tracker_and_recover(timeout_s=args.state_timeout)

        scenario.land_manual(args.descent_throttle)
        scenario.disarm()
        scenario.complete()
        if tracking_failure is not None:
            raise tracking_failure
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

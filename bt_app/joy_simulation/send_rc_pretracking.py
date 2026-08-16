#!/usr/bin/env python3
"""Emulate a no-enabler Boxer pre-tracking cursor scenario over MAVLink."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from send_rc_tracker_mode import (
    ENABLER,
    PITCH,
    RC_MIN,
    ROLL,
    TRACKER_MODE,
    TrackerModeSender,
    tracker_channels,
)


def cursor_channels(*, roll: int = 1500, pitch: int = 1500) -> tuple[int, ...]:
    """Build ground-safe CURSOR channels while keeping the enabler low."""

    channels = list(tracker_channels("cursor", enabler=RC_MIN))
    channels[ROLL] = roll
    channels[PITCH] = pitch
    return tuple(channels)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination-host", default="127.0.0.1")
    parser.add_argument("--destination-port", type=int, default=14560)
    parser.add_argument("--rate-hz", type=float, default=50.0)
    parser.add_argument("--disabled-settle-duration", type=float, default=0.5)
    parser.add_argument("--cursor-settle-duration", type=float, default=0.5)
    parser.add_argument(
        "--side-duration",
        type=float,
        default=5.0,
        help="seconds to hold each side of the square movement",
    )
    parser.add_argument("--recenter-duration", type=float, default=0.5)
    parser.add_argument("--final-disabled-duration", type=float, default=1.0)
    parser.add_argument(
        "--stick-deflection",
        type=int,
        default=200,
        help="RC distance from center for each square direction",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    durations = (
        args.disabled_settle_duration,
        args.cursor_settle_duration,
        args.side_duration,
        args.recenter_duration,
        args.final_disabled_duration,
    )
    if args.rate_hz <= 0:
        raise SystemExit("--rate-hz must be greater than zero")
    if min(durations) < 0:
        raise SystemExit("durations cannot be negative")
    if not 101 <= args.stick_deflection <= 500:
        raise SystemExit("--stick-deflection must be between 101 and 500")

    disabled = tracker_channels("disabled", enabler=RC_MIN)
    centered_cursor = cursor_channels()
    stick_low = 1500 - args.stick_deflection
    stick_high = 1500 + args.stick_deflection
    square_sides = (
        ("move right", cursor_channels(roll=stick_high)),
        ("move down", cursor_channels(pitch=stick_high)),
        ("move left", cursor_channels(roll=stick_low)),
        ("move up", cursor_channels(pitch=stick_low)),
    )
    sender = TrackerModeSender(
        (args.destination_host, args.destination_port),
        rate_hz=args.rate_hz,
        dry_run=args.dry_run,
    )
    packet_count = 0
    completed = False

    def phase(label: str, channels: Sequence[int], duration: float) -> None:
        nonlocal packet_count
        print(
            f"{label}: roll={channels[ROLL]} pitch={channels[PITCH]} "
            f"enabler={channels[ENABLER]} tracker_mode={channels[TRACKER_MODE]} "
            f"duration={duration:.2f}s",
            flush=True,
        )
        packet_count += sender.send_for(channels, duration)

    try:
        phase("1/8 DISABLED settle", disabled, args.disabled_settle_duration)
        phase("2/8 enter CURSOR centered", centered_cursor, args.cursor_settle_duration)
        for index, (label, channels) in enumerate(square_sides, start=3):
            phase(f"{index}/8 square: {label}", channels, args.side_duration)
        phase("7/8 recenter sticks in CURSOR", centered_cursor, args.recenter_duration)
        phase("8/8 return to DISABLED", disabled, args.final_disabled_duration)
        completed = True
        print(
            f"Scenario completed: sent {packet_count} packets, enabler remained low",
            flush=True,
        )
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"ERROR: failed to send MAVLink RC override: {exc}", file=sys.stderr)
        return 1
    finally:
        if not completed:
            try:
                print("Safety cleanup: sending final DISABLED command", flush=True)
                sender.send_once(disabled)
            except OSError:
                pass
        sender.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

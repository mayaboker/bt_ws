#!/usr/bin/env python3
"""Select a tracker mode and pulse the joystick enabler over MAVLink.

The channel layout mirrors ``config/boxer_mapping.yaml``.  In particular,
channel 8 is the momentary enabler and channel 9 is the three-position tracker
mode selector (disabled/cursor/tracking).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from collections.abc import Sequence

# RC channels 9-18 are MAVLink 2 extension fields.
os.environ.setdefault("MAVLINK20", "1")

from pymavlink import mavutil

mavutil.set_dialect("common")


ROLL = 0
PITCH = 1
THROTTLE = 2
YAW = 3
ARM = 4
MANUAL_ALT_HOLD = 5
AUTO_TAKEOFF = 6
ENABLER = 7
TRACKER_MODE = 8

RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000
TRACKER_MODES = {
    "disabled": RC_MIN,
    "cursor": RC_MID,
    "tracking": RC_MAX,
}

JOYSTICK_SYSTEM_ID = 255
JOYSTICK_COMPONENT_ID = mavutil.mavlink.MAV_COMP_ID_MISSIONPLANNER
TARGET_SYSTEM_ID = 254
TARGET_COMPONENT_ID = 0


def tracker_channels(mode: str, *, enabler: int = RC_MIN) -> tuple[int, ...]:
    """Return the nine Boxer-mapped RC channels in a ground-safe state."""

    channels = [
        RC_MID,  # roll
        RC_MID,  # pitch
        RC_MIN,  # throttle
        RC_MID,  # yaw
        RC_MIN,  # disarmed
        RC_MAX,  # application convention: manual switch not requested
        RC_MIN,  # automatic takeoff not requested
        enabler,
        TRACKER_MODES[mode],
    ]
    return tuple(channels)


class TrackerModeSender:
    def __init__(
        self,
        destination: tuple[str, int],
        *,
        rate_hz: float,
        dry_run: bool = False,
    ) -> None:
        self.destination = destination
        self.period_s = 1.0 / rate_hz
        self.dry_run = dry_run
        self.encoder = mavutil.mavlink.MAVLink(
            None,
            srcSystem=JOYSTICK_SYSTEM_ID,
            srcComponent=JOYSTICK_COMPONENT_ID,
        )
        self.socket = None if dry_run else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()

    def send_for(self, channels: Sequence[int], duration_s: float) -> int:
        count = 0
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self.send_once(channels)
            count += 1
            time.sleep(self.period_s)
        return count

    def send_once(self, channels: Sequence[int]) -> None:
        if len(channels) != 9:
            raise ValueError(f"expected 9 mapped RC channels, got {len(channels)}")
        message = self.encoder.rc_channels_override_encode(
            TARGET_SYSTEM_ID,
            TARGET_COMPONENT_ID,
            *channels,
        )
        if self.socket is not None:
            self.socket.sendto(message.pack(self.encoder), self.destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=tuple(TRACKER_MODES))
    parser.add_argument("--destination-host", default="127.0.0.1")
    parser.add_argument("--destination-port", type=int, default=14560)
    parser.add_argument("--rate-hz", type=float, default=50.0)
    parser.add_argument(
        "--settle-duration",
        type=float,
        default=0.25,
        help="seconds to send enabler low before its rising edge",
    )
    parser.add_argument(
        "--pulse-duration",
        type=float,
        default=0.25,
        help="seconds to hold the enabler high",
    )
    parser.add_argument(
        "--hold-duration",
        type=float,
        default=1.0,
        help="seconds to hold the selected mode after releasing the enabler",
    )
    parser.add_argument(
        "--no-enable",
        action="store_true",
        help="select the tracker mode without pulsing the enabler",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0:
        raise SystemExit("--rate-hz must be greater than zero")
    if min(args.settle_duration, args.pulse_duration, args.hold_duration) < 0:
        raise SystemExit("durations cannot be negative")

    low = tracker_channels(args.mode, enabler=RC_MIN)
    high = tracker_channels(args.mode, enabler=RC_MAX)
    sender = TrackerModeSender(
        (args.destination_host, args.destination_port),
        rate_hz=args.rate_hz,
        dry_run=args.dry_run,
    )
    try:
        print(
            f"Selecting tracker mode {args.mode} "
            f"(ch9={low[TRACKER_MODE]}) via "
            f"{args.destination_host}:{args.destination_port}",
            flush=True,
        )
        count = sender.send_for(low, args.settle_duration)
        if not args.no_enable:
            print("Pulsing enabler ch8: 1000 -> 2000 -> 1000", flush=True)
            count += sender.send_for(high, args.pulse_duration)
        count += sender.send_for(low, args.hold_duration)
        print(f"Sent {count} RC override packets", flush=True)
    except OSError as exc:
        print(f"ERROR: failed to send MAVLink RC override: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    finally:
        sender.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

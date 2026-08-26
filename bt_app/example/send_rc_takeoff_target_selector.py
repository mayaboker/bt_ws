#!/usr/bin/env python3
"""Take off, move the image-space target selector, and enable tracking."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from typing import Any

from send_rc import PITCH, RC_MAX, RC_MID, RC_MIN, ROLL, ScenarioError
from send_rc_takeoff_tracker import (
    ALT_HOLD_18,
    TRACKER1,
    TRACKER_ENABLE,
    TRACKER_MODE,
    TRACKER_SELECTED_LOW,
    TakeoffTrackerScenario,
    build_parser as build_tracker_parser,
)

TARGET_GESTURES = {
    "left": (RC_MIN, RC_MIN),
    "center": (RC_MID, RC_MIN),
    "right": (RC_MAX, RC_MIN),
}


def target_gesture(
    target: str,
    *,
    roll_override: int | None = None,
    pitch_override: int | None = None,
) -> tuple[int, int]:
    """Resolve a named target to roll/pitch, preserving optional tuning overrides."""
    roll_rc, pitch_rc = TARGET_GESTURES[target]
    return (
        roll_rc if roll_override is None else int(roll_override),
        pitch_rc if pitch_override is None else int(pitch_override),
    )


def selector_channels(roll_rc: int, pitch_rc: int, *, enable_high=False):
    channels = list(ALT_HOLD_18)
    channels[ROLL] = int(roll_rc)
    channels[PITCH] = int(pitch_rc)
    channels[TRACKER_MODE] = TRACKER1
    channels[TRACKER_ENABLE] = RC_MAX if enable_high else RC_MIN
    return tuple(channels)


class TakeoffTargetSelectorScenario(TakeoffTrackerScenario):
    """Select a target without moving the vehicle in ALT_HOLD."""

    def __init__(
        self,
        *,
        selector_roll_rc: int = 1900,
        selector_pitch_rc: int = 1300,
        selector_move_duration_s: float = 0.8,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.selector_move_duration_s = float(selector_move_duration_s)
        self.move_selection = selector_channels(selector_roll_rc, selector_pitch_rc)
        self.centered_low = selector_channels(RC_MID, RC_MID)
        self.centered_high = selector_channels(RC_MID, RC_MID, enable_high=True)

    def _enter_tracking(self) -> None:
        self._phase("Moving the image selector; drone pitch/roll remain centered")
        if self._send_for_or_track(self.move_selection, self.selector_move_duration_s):
            return
        self._phase("Selector stopped; waiting for a stable green TARGET READY box")
        deadline = time.monotonic() + self.tracker_entry_timeout_s
        while time.monotonic() < deadline:
            if self._send_for_or_track(self.centered_low, self.tracker_pulse_duration_s):
                break
            if self._send_for_or_track(self.centered_high, self.tracker_pulse_duration_s):
                break
        else:
            raise ScenarioError(
                "Target selector did not enter TRACK; adjust --selector-roll-rc, "
                "--selector-pitch-rc, or --selector-move-duration"
            )
        self._send_rc(TRACKER_SELECTED_LOW)
        self._phase("ALT_HOLD -> TRACK; selected target is now locked")


def build_parser() -> argparse.ArgumentParser:
    parser = build_tracker_parser()
    parser.description = "Takeoff and select one of three red targets with an image reticle."
    parser.add_argument(
        "--target",
        choices=tuple(TARGET_GESTURES),
        default="right",
        help="named red box to select from the centered reticle",
    )
    parser.add_argument(
        "--selector-roll-rc",
        type=int,
        default=None,
        help="override the named target's horizontal selector command",
    )
    parser.add_argument(
        "--selector-pitch-rc",
        type=int,
        default=None,
        help="override the named target's vertical selector command",
    )
    parser.add_argument("--selector-move-duration", type=float, default=0.8)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selector_roll_rc, selector_pitch_rc = target_gesture(
        args.target,
        roll_override=args.selector_roll_rc,
        pitch_override=args.selector_pitch_rc,
    )
    for name in ("selector_roll_rc", "selector_pitch_rc"):
        value = selector_roll_rc if name == "selector_roll_rc" else selector_pitch_rc
        if not RC_MIN <= value <= RC_MAX:
            raise SystemExit(f"--{name.replace('_', '-')} must be from {RC_MIN} through {RC_MAX}")
    if args.selector_move_duration <= 0:
        raise SystemExit("--selector-move-duration must be greater than zero")
    scenario = TakeoffTargetSelectorScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.landing_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=args.alt_hold_duration,
        descent_throttle=args.descent_throttle,
        tracker_entry_timeout_s=args.tracker_entry_timeout,
        tracking_timeout_s=args.tracking_timeout,
        tracker_pulse_duration_s=args.tracker_pulse_duration,
        selector_roll_rc=selector_roll_rc,
        selector_pitch_rc=selector_pitch_rc,
        selector_move_duration_s=args.selector_move_duration,
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

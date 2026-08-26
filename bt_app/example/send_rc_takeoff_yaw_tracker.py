#!/usr/bin/env python3
"""Take off, yaw in ALT_HOLD until a target appears, track, then land."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from typing import Any

from send_rc import RC_MAX, RC_MID, RC_MIN, YAW, ScenarioError
from send_rc_takeoff_tracker import (
    ALT_HOLD_18,
    TRACKER1,
    TRACKER_ENABLE,
    TRACKER_MODE,
    TRACKER_SELECTED_LOW,
    TakeoffTrackerScenario,
    build_parser as build_tracker_parser,
)


SCENARIO_BANNER = """\
==============================================================================
bt-app Takeoff / ALT_HOLD Yaw Search / Red-Target Tracking Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Arm in MANUAL and complete automatic takeoff into ALT_HOLD.
  2. Select tracker1 and continuously yaw clockwise with SF held LOW.
  3. Alternate SF LOW-to-HIGH while yawing; pulses are ignored until the
     visual tracker has acquired enough target frames.
  4. On the first accepted pulse, bt-app transitions ALT_HOLD -> TRACK and
     TrackerController takes ownership of yaw, pitch, and throttle.
  5. Wait for TRACK to exit automatically, then land and verify IDLE.

Transition details:
  ALT_HOLD yaw search -> target visible -> tracker acquisition ready
  -> next SF rising edge -> TRACK -> centered external yaw command.

The red detector, bt-gst, and bt-app must already be running. Start the drone
with the target outside the camera view so the yaw-search behavior is visible.

Safety behavior:
  A search or tracker timeout disables tracking and attempts a controlled
  landing. Other airborne failures stop RC traffic so bt-app failsafe recovers.
=============================================================================="""


def yaw_search_channels(yaw_rc: int, *, enable_high: bool) -> tuple[int, ...]:
    """Build a complete ALT_HOLD tracker-selection snapshot with yaw search."""

    channels = list(ALT_HOLD_18)
    channels[YAW] = int(yaw_rc)
    channels[TRACKER_MODE] = TRACKER1
    channels[TRACKER_ENABLE] = RC_MAX if enable_high else RC_MIN
    return tuple(channels)


class TakeoffYawTrackerScenario(TakeoffTrackerScenario):
    """Search clockwise in ALT_HOLD and enter TRACK on visual acquisition.

    bt-app accumulates visual acquisition while tracker1 remains selected. Each
    LOW phase arms its rising-edge detector. If the target is not ready, the
    following HIGH edge is ignored and yaw search continues. Once acquisition
    is ready, a HIGH edge changes the application state from ALT_HOLD to TRACK.
    The TRACK controller then owns flight RC; this scenario sends one centered-
    yaw LOW snapshot after observing the state transition.
    """

    def __init__(self, *, search_yaw_rc: int = 1900, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_yaw_rc = int(search_yaw_rc)
        self.search_low = yaw_search_channels(
            self.search_yaw_rc,
            enable_high=False,
        )
        self.search_high = yaw_search_channels(
            self.search_yaw_rc,
            enable_high=True,
        )

    def _enter_tracking(self) -> None:
        """Yaw and pulse tracker enable until channel telemetry reports TRACK."""

        self._phase(
            "ALT_HOLD target search: selecting tracker1 and commanding "
            f"clockwise yaw_rc={self.search_yaw_rc}"
        )
        deadline = time.monotonic() + self.tracker_entry_timeout_s
        pulse_count = 0
        while time.monotonic() < deadline:
            if self._send_for_or_track(
                self.search_low,
                self.tracker_pulse_duration_s,
            ):
                break
            pulse_count += 1
            self._phase(
                f"Target search pulse {pulse_count}: SF LOW -> HIGH while yawing"
            )
            if self._send_for_or_track(
                self.search_high,
                self.tracker_pulse_duration_s,
            ):
                break
        else:
            raise ScenarioError(
                "Timed out yawing in ALT_HOLD without entering TRACK; verify "
                "the target enters the camera view and bt-gst reports detections"
            )

        self._send_rc(TRACKER_SELECTED_LOW)
        self._phase(
            "ALT_HOLD -> TRACK observed after "
            f"{pulse_count} SF pulse(s); external yaw centered"
        )

    @staticmethod
    def _print_banner() -> None:
        print(SCENARIO_BANNER, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = build_tracker_parser()
    parser.description = SCENARIO_BANNER
    parser.add_argument(
        "--search-yaw-rc",
        type=int,
        default=1900,
        help="clockwise ALT_HOLD search yaw PWM, from 1501 through 2000",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0:
        raise SystemExit("--rate-hz must be greater than zero")
    if args.state_timeout <= 0 or args.landing_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if args.tracker_entry_timeout <= 0 or args.tracking_timeout <= 0:
        raise SystemExit("tracker timeouts must be greater than zero")
    if args.tracker_pulse_duration <= 0:
        raise SystemExit("--tracker-pulse-duration must be greater than zero")
    if args.alt_hold_duration < 0:
        raise SystemExit("--alt-hold-duration cannot be negative")
    if args.touchdown_altitude < 0:
        raise SystemExit("--touchdown-altitude cannot be negative")
    if not RC_MIN <= args.descent_throttle <= 1650:
        raise SystemExit("--descent-throttle must be between 1000 and 1650")
    if not RC_MID < args.search_yaw_rc <= RC_MAX:
        raise SystemExit("--search-yaw-rc must be between 1501 and 2000")

    scenario = TakeoffYawTrackerScenario(
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
        search_yaw_rc=args.search_yaw_rc,
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

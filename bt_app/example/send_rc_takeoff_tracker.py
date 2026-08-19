#!/usr/bin/env python3
"""Take off, enter red-target tracking, then land after tracking exits."""

from __future__ import annotations

import argparse
import struct
import sys
import time
from collections.abc import Sequence
from typing import Any

from send_rc import (
    ALT_HOLD_ARMED,
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    ARM_IN_MANUAL,
    AUTO_TAKEOFF_ARMED,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    RC_MAX,
    RC_MID,
    RC_MIN,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    STATE_NAMES,
    STATE_TAKEOFF,
    MavlinkRcScenario,
    ScenarioError,
    Telemetry,
)
from send_rc import (
    build_parser as build_base_parser,
)

TRACKER_MODE = 7
TRACKER_ENABLE = 8
INTERNAL_CHANNEL_COUNT = 18
TRACKER1 = RC_MID
TRACKER_DISABLED = RC_MIN
STATE_TRACK = 8

CHANNEL_STATUS_MESSAGE_TYPE = 1
CHANNEL_STATUS_VERSION = 1
CHANNEL_STATUS_FORMAT = "<BBBH8H"
CHANNEL_STATUS_SIZE = struct.calcsize(CHANNEL_STATUS_FORMAT)

TRACKER_STATE_NAMES = {**STATE_NAMES, STATE_TRACK: "TRACK"}


def extended_channels(
    channels: Sequence[int],
    *,
    tracker_mode: int = TRACKER_DISABLED,
    tracker_enable: int = RC_MIN,
) -> tuple[int, ...]:
    """Return one complete bt-app joystick snapshot."""

    result = [int(value) for value in channels]
    result.extend([RC_MIN] * (INTERNAL_CHANNEL_COUNT - len(result)))
    if len(result) != INTERNAL_CHANNEL_COUNT:
        raise ValueError("base channels cannot contain more than 18 values")
    result[TRACKER_MODE] = tracker_mode
    result[TRACKER_ENABLE] = tracker_enable
    return tuple(result)


NEUTRAL_18 = extended_channels(NEUTRAL_DISARMED)
ARM_MANUAL_18 = extended_channels(ARM_IN_MANUAL)
AUTO_TAKEOFF_18 = extended_channels(AUTO_TAKEOFF_ARMED)
ALT_HOLD_18 = extended_channels(ALT_HOLD_ARMED)
TRACKER_SELECTED_LOW = extended_channels(
    ALT_HOLD_ARMED,
    tracker_mode=TRACKER1,
    tracker_enable=RC_MIN,
)
TRACKER_SELECTED_HIGH = extended_channels(
    ALT_HOLD_ARMED,
    tracker_mode=TRACKER1,
    tracker_enable=RC_MAX,
)
MANUAL_DISARMED_18 = extended_channels(MANUAL_DISARMED)


SCENARIO_BANNER = """\
==============================================================================
bt-app Takeoff to Red-Target Tracking Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Arm in MANUAL and complete automatic takeoff into ALT_HOLD.
  2. Select tracker1 and retry SF low-to-high pulses until TRACK is observed.
  3. Keep tracker1 selected until bt-app returns automatically to ALT_HOLD.
  4. Switch to MANUAL, descend, disarm, and verify IDLE.

The red detector, bt-gst, and bt-app must already be running.

Safety behavior:
  A tracker timeout disables tracking and attempts a controlled landing.
  Other airborne failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class TrackerTelemetry(Telemetry):
    """Telemetry with the 10 Hz bt-app controller-state extension."""

    def consume(self, message: Any) -> bool:
        previous_state = self.state
        changed = super().consume(message)
        if (
            int(message.get_srcSystem()) == APP_SYSTEM_ID
            and int(message.get_srcComponent()) == APP_COMPONENT_ID
            and message.get_type() == "V2_EXTENSION"
            and int(message.message_type) == CHANNEL_STATUS_MESSAGE_TYPE
        ):
            values = struct.unpack(
                CHANNEL_STATUS_FORMAT,
                bytes(message.payload[:CHANNEL_STATUS_SIZE]),
            )
            version, _command, state, _flags, *_channels = values
            if version == CHANNEL_STATUS_VERSION:
                self.state = int(state)
        return changed or self.state != previous_state

    def describe(self) -> str:
        state = TRACKER_STATE_NAMES.get(self.state, str(self.state))
        altitude = "unknown" if self.altitude_m is None else f"{self.altitude_m:.2f} m"
        return f"state={state} armed={self.armed} altitude={altitude}"


class TakeoffTrackerScenario(MavlinkRcScenario):
    """Automatic takeoff followed by one externally observed tracking run."""

    def __init__(
        self,
        *,
        tracker_entry_timeout_s: float,
        tracking_timeout_s: float,
        tracker_pulse_duration_s: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.telemetry = TrackerTelemetry()
        self.tracker_entry_timeout_s = tracker_entry_timeout_s
        self.tracking_timeout_s = tracking_timeout_s
        self.tracker_pulse_duration_s = tracker_pulse_duration_s
        self.manual_descent_channels = extended_channels(self.manual_descent_channels)

    def run(self) -> None:
        self._print_banner()
        self._open()
        try:
            self._phase("Waiting for bt-app telemetry")
            self._wait_for(
                NEUTRAL_18,
                lambda: self.telemetry.state is not None,
                self.state_timeout_s,
                "application telemetry",
            )

            self._phase("Arming in MANUAL mode")
            self._wait_for_state(ARM_MANUAL_18, STATE_MANUAL, self.state_timeout_s)

            self._phase("Requesting automatic takeoff")
            self._wait_for_state(
                AUTO_TAKEOFF_18,
                STATE_TAKEOFF,
                self.state_timeout_s,
            )
            self._airborne = True

            self._phase("Waiting for takeoff completion and ALT_HOLD")
            self._wait_for_state(
                AUTO_TAKEOFF_18,
                STATE_ALT_HOLD,
                self.landing_timeout_s,
            )
            if self.alt_hold_duration_s:
                self._phase(
                    "Stabilizing before tracking for "
                    f"{self.alt_hold_duration_s:.1f} seconds"
                )
                self._send_for(ALT_HOLD_18, self.alt_hold_duration_s)

            failure: ScenarioError | None = None
            try:
                self._enter_tracking()
                self._phase("TRACK active; waiting for automatic ALT_HOLD exit")
                self._wait_for(
                    TRACKER_SELECTED_LOW,
                    lambda: self.telemetry.state == STATE_ALT_HOLD,
                    self.tracking_timeout_s,
                    "automatic TRACK to ALT_HOLD transition",
                )
                self._phase("Tracking exited automatically")
            except ScenarioError as exc:
                failure = exc
                self._phase(f"Tracker failure: {exc}")
                self._phase("Disabling tracker and recovering ALT_HOLD")
                self._wait_for(
                    ALT_HOLD_18,
                    lambda: self.telemetry.state == STATE_ALT_HOLD,
                    self.state_timeout_s,
                    "ALT_HOLD after tracker disable",
                )

            self._phase("Switching to MANUAL for landing")
            self._wait_for_state(
                self.manual_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            self._land_and_disarm()
            self._completed = True
            if failure is not None:
                raise failure
            self._phase("Scenario completed successfully")
        finally:
            self._cleanup()

    def _enter_tracking(self) -> None:
        self._phase("Selecting tracker1 and waiting for target lock")
        deadline = time.monotonic() + self.tracker_entry_timeout_s
        pulse_count = 0
        while time.monotonic() < deadline:
            if self._send_for_or_track(
                TRACKER_SELECTED_LOW,
                self.tracker_pulse_duration_s,
            ):
                break
            pulse_count += 1
            self._phase(f"Sending SF tracking-entry pulse {pulse_count}")
            if self._send_for_or_track(
                TRACKER_SELECTED_HIGH,
                self.tracker_pulse_duration_s,
            ):
                break
        else:
            raise ScenarioError(
                "Timed out waiting for TRACK; verify bt-gst target detection"
            )

        self._send_rc(TRACKER_SELECTED_LOW)
        self._phase(f"TRACK entered after {pulse_count} SF pulse(s)")

    def _send_for_or_track(
        self,
        channels: Sequence[int],
        duration_s: float,
    ) -> bool:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self._send_rc(channels)
            self._receive_pending()
            if self.telemetry.state == STATE_TRACK:
                return True
            time.sleep(self.period_s)
        return self.telemetry.state == STATE_TRACK

    def _land_and_disarm(self) -> None:
        self._phase("Waiting for touchdown")
        consecutive_samples = 0
        last_sample_count = self.telemetry.altitude_samples

        def touchdown() -> bool:
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
            touchdown,
            self.landing_timeout_s,
            f"three touchdown samples <= {self.touchdown_altitude_m:.2f} m",
        )
        self._airborne = False
        self._phase("Disarming and waiting for IDLE")
        self._wait_for(
            MANUAL_DISARMED_18,
            lambda: self.telemetry.state == STATE_IDLE and not self.telemetry.armed,
            self.state_timeout_s,
            "IDLE with armed flag cleared",
        )
        self._send_for(MANUAL_DISARMED_18, 0.5)

    @staticmethod
    def _print_banner() -> None:
        print(SCENARIO_BANNER, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = build_base_parser()
    parser.description = SCENARIO_BANNER
    parser.set_defaults(alt_hold_duration=0.0, descent_throttle=1600)
    parser.add_argument(
        "--tracker-entry-timeout",
        type=float,
        default=30.0,
        help="seconds allowed for target lock and TRACK entry",
    )
    parser.add_argument(
        "--tracking-timeout",
        type=float,
        default=60.0,
        help="seconds allowed for TRACK to exit automatically",
    )
    parser.add_argument(
        "--tracker-pulse-duration",
        type=float,
        default=0.25,
        help="seconds to hold each SF low and high pulse phase",
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

    scenario = TakeoffTrackerScenario(
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

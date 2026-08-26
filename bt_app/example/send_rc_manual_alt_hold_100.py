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
    NEUTRAL_DISARMED,
    RC_MAX,
    RC_MID,
    RC_MIN,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    PITCH,
    ROLL,
    THROTTLE,
    MavlinkRcScenario,
    ScenarioError,
    rc_channels,
)
from send_rc_takeoff_tracker import (
    MANUAL_DISARMED_18,
    STATE_TRACK,
    TRACKER_ENABLE,
    TRACKER_SELECTED_LOW,
    TrackerTelemetry,
    extended_channels,
)

SELECTOR_SPEED_PX_S = 360.0
SELECTOR_SCAN_SPEED_PX_S = 60.0
SELECTOR_STICK_DEADBAND = 35
SELECTOR_STICK_USABLE = 500 - SELECTOR_STICK_DEADBAND
SELECTOR_SCAN_RC_OFFSET = int(
    SELECTOR_STICK_DEADBAND
    + SELECTOR_STICK_USABLE * SELECTOR_SCAN_SPEED_PX_S / SELECTOR_SPEED_PX_S
    + 0.5
)
SELECTOR_SCAN_UP_RC = RC_MID + SELECTOR_SCAN_RC_OFFSET
SELECTOR_SCAN_DOWN_RC = RC_MID - SELECTOR_SCAN_RC_OFFSET
SELECTOR_INITIAL_SCAN_RC = SELECTOR_SCAN_DOWN_RC
DEFAULT_SELECTOR_SWEEP_DURATION_S = 400.0 / SELECTOR_SCAN_SPEED_PX_S
SELECTOR_SCAN_STEP_PX = 20.0
SELECTOR_SCAN_STEP_DURATION_S = SELECTOR_SCAN_STEP_PX / SELECTOR_SCAN_SPEED_PX_S


def tracker_selector_channels(
    *, roll: int, pitch: int, enable_high: bool = False
) -> tuple[int, ...]:
    """Return an ALT_HOLD TRACKER1-selection snapshot with selector sticks."""
    channels = list(TRACKER_SELECTED_LOW)
    channels[ROLL] = int(roll)
    channels[PITCH] = int(pitch)
    channels[TRACKER_ENABLE] = RC_MAX if enable_high else RC_MIN
    return tuple(channels)


SCENARIO_BANNER = """\
==============================================================================
bt-app MANUAL Climb / ALT_HOLD SITL Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Wait for bt-app MAVLink telemetry and arm in MANUAL.
  2. Increase MANUAL throttle slowly until the target altitude is reached.
  3. Center the throttle and switch from MANUAL to ALT_HOLD.
  4. Select TRACKER1 with its image gate centered horizontally.
  5. Search only the lower image half: center-to-bottom-to-center until TRACK starts.
  6. Wait for tracking to exit automatically back to ALT_HOLD.
  7. Deselect the tracker, switch back to MANUAL, and descend.
  8. Confirm touchdown, disarm, and verify IDLE.

Safety behavior:
  Before takeoff, failures send a ground-safe disarm command.
  While airborne, failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class ManualClimbScenario(MavlinkRcScenario):
    def __init__(
        self,
        *,
        target_altitude_m: float = 50.0,
        ascent_start_throttle: int = 1500,
        ascent_max_throttle: int = 1680,
        ascent_ramp_pwm_s: float = 10.0,
        tracker_entry_timeout_s: float = 30.0,
        tracking_timeout_s: float = 90.0,
        tracker_pulse_duration_s: float = 0.4,
        selector_sweep_duration_s: float = DEFAULT_SELECTOR_SWEEP_DURATION_S,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.target_altitude_m = target_altitude_m
        self.ascent_start_throttle = ascent_start_throttle
        self.ascent_max_throttle = ascent_max_throttle
        self.ascent_ramp_pwm_s = ascent_ramp_pwm_s
        self.tracker_entry_timeout_s = tracker_entry_timeout_s
        self.tracking_timeout_s = tracking_timeout_s
        self.tracker_pulse_duration_s = tracker_pulse_duration_s
        self.selector_sweep_duration_s = selector_sweep_duration_s
        self.telemetry = TrackerTelemetry()
        # Always transmit explicit tracker channels after selection so the
        # receiver cannot retain TRACKER1 when this scenario returns to MANUAL.
        self.manual_descent_channels = extended_channels(
            self.manual_descent_channels
        )

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
            if self.alt_hold_duration_s:
                self._phase(
                    "Stabilizing in ALT_HOLD for "
                    f"{self.alt_hold_duration_s:.1f} seconds"
                )
                self._send_for(ALT_HOLD_ARMED, self.alt_hold_duration_s)
            self._phase("Selecting TRACKER1 at the camera horizontal center")
            self._send_rc(TRACKER_SELECTED_LOW)
            self._enter_tracking_with_vertical_scan()
            self._phase("TRACK active; centering selector sticks")
            self._wait_for(
                TRACKER_SELECTED_LOW,
                lambda: self.telemetry.state == STATE_ALT_HOLD,
                self.tracking_timeout_s,
                "automatic TRACK to ALT_HOLD transition",
            )
            self._phase("Tracking exited automatically")

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
                MANUAL_DISARMED_18,
                lambda: self.telemetry.state == STATE_IDLE
                and not self.telemetry.armed,
                self.state_timeout_s,
                "IDLE with armed flag cleared",
            )
            self._send_for(MANUAL_DISARMED_18, 0.5)
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

    def _enter_tracking_with_vertical_scan(self) -> None:
        """Move in small vertical steps, then pulse TRACK with centered sticks."""
        self._phase(
            "Scanning selector in 20 px steps; dwell and pulse while centered"
        )
        deadline = time.monotonic() + self.tracker_entry_timeout_s
        pitch_rc = SELECTOR_INITIAL_SCAN_RC  # Target is expected below image center.
        # Keep the search in the lower image half. Every leg runs between the
        # image center and bottom, never into the upper half where this target
        # cannot appear.
        remaining_move_s = self.selector_sweep_duration_s / 2.0
        pulse_count = 0
        while time.monotonic() < deadline:
            if remaining_move_s <= 1e-9:
                pitch_rc = (
                    SELECTOR_SCAN_DOWN_RC
                    if pitch_rc == SELECTOR_SCAN_UP_RC
                    else SELECTOR_SCAN_UP_RC
                )
                remaining_move_s = self.selector_sweep_duration_s / 2.0
                direction = "down" if pitch_rc == SELECTOR_SCAN_DOWN_RC else "up"
                destination = "bottom" if direction == "down" else "center"
                self._phase(f"Reversing lower-half selector sweep toward {destination}")
            move_duration_s = min(SELECTOR_SCAN_STEP_DURATION_S, remaining_move_s)
            moving_low = tracker_selector_channels(
                roll=RC_MID,
                pitch=pitch_rc,
                enable_high=False,
            )
            if self._send_for_or_track(
                moving_low,
                min(move_duration_s, max(0.0, deadline - time.monotonic())),
            ):
                self._send_rc(TRACKER_SELECTED_LOW)
                return
            remaining_move_s -= move_duration_s

            # TRACK entry explicitly requires centered pitch and roll. Hold LOW
            # long enough to acquire, then create the rising edge while the gate
            # remains stationary over any selected target.
            for enable_high in (False, True):
                stationary = tracker_selector_channels(
                    roll=RC_MID,
                    pitch=RC_MID,
                    enable_high=enable_high,
                )
                if self._send_for_or_track(
                    stationary,
                    min(
                        self.tracker_pulse_duration_s,
                        max(0.0, deadline - time.monotonic()),
                    ),
                ):
                    self._send_rc(TRACKER_SELECTED_LOW)
                    self._phase(
                        f"Target acquired; ALT_HOLD -> TRACK after {pulse_count} pulse(s)"
                    )
                    return
                if enable_high:
                    pulse_count += 1
        raise ScenarioError(
            "Timed out searching the lower image half without entering TRACK; "
            "verify the red detector and target visibility"
        )

    def _send_for_or_track(
        self, channels: Sequence[int], duration_s: float
    ) -> bool:
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            self._send_rc(channels)
            self._receive_pending()
            if self.telemetry.state == STATE_TRACK:
                return True
            time.sleep(self.period_s)
        return self.telemetry.state == STATE_TRACK

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
    parser.add_argument("--target-altitude", type=float, default=40.0)
    parser.add_argument("--ascent-start-throttle", type=int, default=1500)
    parser.add_argument("--ascent-max-throttle", type=int, default=1680)
    parser.add_argument("--ascent-ramp", type=float, default=10.0)
    parser.add_argument("--alt-hold-duration", type=float, default=30.0)
    parser.add_argument("--tracker-entry-timeout", type=float, default=30.0)
    parser.add_argument("--tracking-timeout", type=float, default=90.0)
    parser.add_argument("--tracker-pulse-duration", type=float, default=0.4)
    parser.add_argument(
        "--selector-sweep-duration",
        type=float,
        default=DEFAULT_SELECTOR_SWEEP_DURATION_S,
        help=(
            "seconds for a full 400 px image-height pass; the lower-half search "
            "uses half this time for each center/bottom leg"
        ),
    )
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
    if (
        args.tracker_entry_timeout <= 0
        or args.tracking_timeout <= 0
        or args.tracker_pulse_duration <= 0
        or args.selector_sweep_duration <= 0
    ):
        raise SystemExit("tracker and selector durations must be greater than zero")

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
        tracker_entry_timeout_s=args.tracker_entry_timeout,
        tracking_timeout_s=args.tracking_timeout,
        tracker_pulse_duration_s=args.tracker_pulse_duration,
        selector_sweep_duration_s=args.selector_sweep_duration,
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

#!/usr/bin/env python3
"""Test two ALT_HOLD entries separated by a MANUAL hover attempt in SITL."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Sequence

from send_rc import (
    ALT_HOLD_ARMED,
    ARM_IN_MANUAL,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    RC_MAX,
    RC_MIN,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    THROTTLE,
    ScenarioError,
    Telemetry,
    rc_channels,
)
from send_rc_manual_alt_hold import ManualClimbScenario


class DescentTelemetry(Telemetry):
    """Telemetry with upward-positive speed derived from altitude samples."""

    def __init__(self) -> None:
        super().__init__()
        self.vertical_speed_m_s: float | None = None
        self._altitude_sample_time_s: float | None = None

    def consume(self, message: Any) -> bool:
        previous_samples = self.altitude_samples
        previous_altitude = self.altitude_m
        previous_time_s = self._altitude_sample_time_s
        changed = super().consume(message)
        if self.altitude_samples == previous_samples:
            return changed

        now_s = time.monotonic()
        if (
            previous_altitude is not None
            and previous_time_s is not None
            and now_s > previous_time_s
            and self.altitude_m is not None
        ):
            self.vertical_speed_m_s = (
                self.altitude_m - previous_altitude
            ) / (now_s - previous_time_s)
        self._altitude_sample_time_s = now_s
        return changed

    def describe(self) -> str:
        description = super().describe()
        speed = (
            "unknown"
            if self.vertical_speed_m_s is None
            else f"{self.vertical_speed_m_s:+.2f} m/s"
        )
        return f"{description} vertical_speed={speed}"


class ManualReentryScenario(ManualClimbScenario):
    def __init__(
        self,
        *,
        first_alt_hold_duration_s: float = 10.0,
        manual_hold_duration_s: float = 10.0,
        manual_hold_throttle: int = 1660,
        second_alt_hold_duration_s: float = 30.0,
        descent_rate_m_s: float = 1.0,
        descent_velocity_kp: float = 50.0,
        descent_min_throttle: int = 1500,
        descent_hover_throttle: int = 1660,
        descent_max_throttle: int = 1800,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.telemetry = DescentTelemetry()
        self.first_alt_hold_duration_s = first_alt_hold_duration_s
        self.manual_hold_duration_s = manual_hold_duration_s
        self.manual_hold_channels = rc_channels(
            armed=True,
            manual=True,
            throttle=manual_hold_throttle,
        )
        self.second_alt_hold_duration_s = second_alt_hold_duration_s
        self.descent_rate_m_s = descent_rate_m_s
        self.descent_velocity_kp = descent_velocity_kp
        self.descent_min_throttle = descent_min_throttle
        self.descent_hover_throttle = descent_hover_throttle
        self.descent_max_throttle = descent_max_throttle

    def run(self) -> None:
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
                f"Climbing slowly in MANUAL to {self.target_altitude_m:.2f} m"
            )
            self._climb_to_target()

            self._enter_and_hold_altitude(
                self.first_alt_hold_duration_s,
                "first",
            )

            manual_throttle = self.manual_hold_channels[THROTTLE]
            self._phase(
                "Switching back to MANUAL and attempting to hold altitude "
                f"at throttle {manual_throttle}"
            )
            self._wait_for_state(
                self.manual_hold_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            manual_start_altitude = self.telemetry.altitude_m
            self._send_for(self.manual_hold_channels, self.manual_hold_duration_s)
            if self.telemetry.state != STATE_MANUAL:
                raise ScenarioError(
                    "Vehicle left MANUAL during hover attempt; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            if manual_start_altitude is not None and self.telemetry.altitude_m is not None:
                drift = self.telemetry.altitude_m - manual_start_altitude
                self._phase(
                    f"MANUAL hover attempt completed with altitude drift {drift:+.2f} m"
                )

            self._enter_and_hold_altitude(
                self.second_alt_hold_duration_s,
                "second",
            )

            self._phase(
                "Switching to MANUAL and controlling descent at "
                f"{self.descent_rate_m_s:.2f} m/s"
            )
            initial_descent_channels = self._descent_channels(None)
            self._wait_for_state(
                initial_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            self._controlled_descent_to_touchdown()

            self._airborne = False
            self._phase("Disarming and waiting for IDLE")
            self._wait_for(
                MANUAL_DISARMED,
                lambda: self.telemetry.state == STATE_IDLE
                and not self.telemetry.armed,
                self.state_timeout_s,
                "IDLE with armed flag cleared",
            )
            self._send_for(MANUAL_DISARMED, 0.5)
            self._completed = True
            self._phase("Scenario completed successfully")
        finally:
            self._cleanup()

    def _enter_and_hold_altitude(self, duration_s: float, label: str) -> None:
        self._phase(f"Switching to {label} ALT_HOLD")
        self._wait_for_state(
            ALT_HOLD_ARMED,
            STATE_ALT_HOLD,
            self.state_timeout_s,
        )
        self._phase(f"Holding {label} ALT_HOLD for {duration_s:.1f} seconds")
        self._send_for(ALT_HOLD_ARMED, duration_s)
        if self.telemetry.state != STATE_ALT_HOLD:
            raise ScenarioError(
                f"Vehicle left {label} ALT_HOLD during dwell; "
                f"last telemetry: {self.telemetry.describe()}"
            )

    def _descent_channels(self, vertical_speed_m_s: float | None) -> tuple[int, ...]:
        measured_speed = 0.0 if vertical_speed_m_s is None else vertical_speed_m_s
        target_speed = -self.descent_rate_m_s
        throttle = int(
            self.descent_hover_throttle
            + self.descent_velocity_kp * (target_speed - measured_speed)
        )
        throttle = max(
            self.descent_min_throttle,
            min(self.descent_max_throttle, throttle),
        )
        return rc_channels(armed=True, manual=True, throttle=throttle)

    def _controlled_descent_to_touchdown(self) -> None:
        self._phase("Waiting for controlled touchdown")
        deadline = time.monotonic() + self.landing_timeout_s
        last_sample_count = self.telemetry.altitude_samples
        consecutive_touchdown_samples = 0
        channels = self._descent_channels(self.telemetry.vertical_speed_m_s)
        next_send = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(channels)
                next_send = now + self.period_s
            self._receive_pending()
            if self.telemetry.state != STATE_MANUAL:
                raise ScenarioError(
                    "Vehicle left MANUAL during controlled descent; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            if self.telemetry.altitude_samples != last_sample_count:
                last_sample_count = self.telemetry.altitude_samples
                channels = self._descent_channels(
                    self.telemetry.vertical_speed_m_s
                )
                altitude = self.telemetry.altitude_m
                if altitude is not None and altitude <= self.touchdown_altitude_m:
                    consecutive_touchdown_samples += 1
                else:
                    consecutive_touchdown_samples = 0
                if consecutive_touchdown_samples >= 3:
                    return
            time.sleep(min(0.005, self.period_s))

        raise ScenarioError(
            f"Timed out after {self.landing_timeout_s:.1f}s descending at "
            f"{self.descent_rate_m_s:.2f} m/s; last telemetry: "
            f"{self.telemetry.describe()}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination-host", default="127.0.0.1")
    parser.add_argument("--destination-port", type=int, default=14560)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=14550)
    parser.add_argument("--rate-hz", type=float, default=50.0)
    parser.add_argument("--state-timeout", type=float, default=20.0)
    parser.add_argument("--flight-timeout", type=float, default=120.0)
    parser.add_argument("--target-altitude", type=float, default=3.0)
    parser.add_argument("--ascent-start-throttle", type=int, default=1500)
    parser.add_argument("--ascent-max-throttle", type=int, default=1680)
    parser.add_argument("--ascent-ramp", type=float, default=10.0)
    parser.add_argument("--first-alt-hold-duration", type=float, default=10.0)
    parser.add_argument("--manual-hold-duration", type=float, default=10.0)
    parser.add_argument("--manual-hold-throttle", type=int, default=1660)
    parser.add_argument("--second-alt-hold-duration", type=float, default=30.0)
    parser.add_argument("--descent-rate", type=float, default=1.0)
    parser.add_argument("--descent-velocity-kp", type=float, default=50.0)
    parser.add_argument("--descent-min-throttle", type=int, default=1500)
    parser.add_argument("--descent-hover-throttle", type=int, default=1660)
    parser.add_argument("--descent-max-throttle", type=int, default=1800)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    durations = (
        args.first_alt_hold_duration,
        args.manual_hold_duration,
        args.second_alt_hold_duration,
    )
    if args.rate_hz <= 0 or args.ascent_ramp <= 0:
        raise SystemExit("--rate-hz and --ascent-ramp must be greater than zero")
    if args.state_timeout <= 0 or args.flight_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if any(duration < 0 for duration in durations):
        raise SystemExit("hold durations cannot be negative")
    if args.target_altitude <= args.touchdown_altitude:
        raise SystemExit("--target-altitude must be above --touchdown-altitude")
    if not RC_MIN <= args.ascent_start_throttle < args.ascent_max_throttle:
        raise SystemExit("invalid ascent throttle range")
    if not args.ascent_max_throttle <= RC_MAX:
        raise SystemExit("--ascent-max-throttle cannot exceed 2000")
    if not RC_MIN <= args.manual_hold_throttle <= RC_MAX:
        raise SystemExit("--manual-hold-throttle must be between 1000 and 2000")
    if args.descent_rate <= 0 or args.descent_velocity_kp <= 0:
        raise SystemExit("descent rate and velocity gain must be positive")
    if not (
        RC_MIN
        <= args.descent_min_throttle
        < args.descent_hover_throttle
        < args.descent_max_throttle
        <= RC_MAX
    ):
        raise SystemExit("invalid descent throttle range")
    if args.touchdown_altitude < 0:
        raise SystemExit("--touchdown-altitude cannot be negative")

    scenario = ManualReentryScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=args.first_alt_hold_duration,
        descent_throttle=args.descent_min_throttle,
        target_altitude_m=args.target_altitude,
        ascent_start_throttle=args.ascent_start_throttle,
        ascent_max_throttle=args.ascent_max_throttle,
        ascent_ramp_pwm_s=args.ascent_ramp,
        first_alt_hold_duration_s=args.first_alt_hold_duration,
        manual_hold_duration_s=args.manual_hold_duration,
        manual_hold_throttle=args.manual_hold_throttle,
        second_alt_hold_duration_s=args.second_alt_hold_duration,
        descent_rate_m_s=args.descent_rate,
        descent_velocity_kp=args.descent_velocity_kp,
        descent_min_throttle=args.descent_min_throttle,
        descent_hover_throttle=args.descent_hover_throttle,
        descent_max_throttle=args.descent_max_throttle,
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

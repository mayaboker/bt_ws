#!/usr/bin/env python3
"""Auto takeoff, timed CW/CCW ALT_HOLD yaw turns, and controlled landing."""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Any
from typing import Sequence

from send_rc import (
    ALT_HOLD_ARMED,
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
    STATE_TAKEOFF,
    YAW,
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    ScenarioError,
    rc_channels,
)
from send_rc_manual_reentry import DescentTelemetry, ManualReentryScenario


def alt_hold_yaw_channels(yaw: int) -> tuple[int, ...]:
    channels = list(ALT_HOLD_ARMED)
    channels[YAW] = yaw
    return tuple(channels)


class YawTelemetry(DescentTelemetry):
    def __init__(self) -> None:
        super().__init__()
        self.roll_deg: float | None = None
        self.pitch_deg: float | None = None
        self.yaw_deg: float | None = None
        self.attitude_samples = 0

    def consume(self, message: Any) -> bool:
        changed = super().consume(message)
        if (
            int(message.get_srcSystem()) != APP_SYSTEM_ID
            or int(message.get_srcComponent()) != APP_COMPONENT_ID
            or message.get_type() != "ATTITUDE"
        ):
            return changed
        roll_deg = math.degrees(float(message.roll))
        pitch_deg = math.degrees(float(message.pitch))
        yaw_deg = math.degrees(float(message.yaw)) % 360.0
        attitude_changed = (
            roll_deg != self.roll_deg
            or pitch_deg != self.pitch_deg
            or yaw_deg != self.yaw_deg
        )
        self.roll_deg = roll_deg
        self.pitch_deg = pitch_deg
        self.yaw_deg = yaw_deg
        self.attitude_samples += 1
        return changed or attitude_changed

    def describe(self) -> str:
        description = super().describe()
        if self.yaw_deg is None:
            return f"{description} attitude=unknown"
        return (
            f"{description} roll={self.roll_deg:+.1f} deg "
            f"pitch={self.pitch_deg:+.1f} deg yaw={self.yaw_deg:.1f} deg"
        )


class AutoYawScenario(ManualReentryScenario):
    def __init__(
        self,
        *,
        turn_angle_deg: float = 360.0,
        yaw_rate_dps: float = 10.0,
        direction_pause_s: float = 1.0,
        cw_yaw_rc: int = 1650,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.telemetry = YawTelemetry()
        self.turn_angle_deg = turn_angle_deg
        self.yaw_rate_dps = yaw_rate_dps
        self.turn_duration_s = turn_angle_deg / yaw_rate_dps
        self.direction_pause_s = direction_pause_s
        self.cw_channels = alt_hold_yaw_channels(cw_yaw_rc)
        ccw_yaw_rc = RC_MID - (cw_yaw_rc - RC_MID)
        self.ccw_channels = alt_hold_yaw_channels(ccw_yaw_rc)

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

            self._phase("Requesting automatic takeoff from MANUAL")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_TAKEOFF,
                self.state_timeout_s,
            )
            self._airborne = True

            self._phase("Waiting for automatic takeoff to enter ALT_HOLD")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_ALT_HOLD,
                self.landing_timeout_s,
            )
            self._wait_for_settled_alt_hold()

            self._command_turn("clockwise", self.cw_channels)
            self._phase(
                f"Centering yaw for {self.direction_pause_s:.1f} seconds"
            )
            self._send_for(ALT_HOLD_ARMED, self.direction_pause_s)
            self._command_turn("counter-clockwise", self.ccw_channels)
            self._phase(
                f"Centering yaw for {self.direction_pause_s:.1f} seconds"
            )
            self._send_for(ALT_HOLD_ARMED, self.direction_pause_s)

            self._phase(
                "Switching to MANUAL and controlling descent at "
                f"{self.descent_rate_m_s:.2f} m/s"
            )
            self._wait_for_state(
                self._descent_channels(None),
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

    def _command_turn(self, label: str, channels: Sequence[int]) -> None:
        commanded_yaw_rc = channels[YAW]
        self._phase(
            f"Commanding {self.turn_angle_deg:.0f} degree {label} yaw for "
            f"approximately {self.turn_duration_s:.1f} seconds: "
            f"yaw_rc={commanded_yaw_rc}, expected_rate={self.yaw_rate_dps:.1f} deg/s"
        )
        deadline = time.monotonic() + max(10.0, self.turn_duration_s * 3.0)
        next_send = 0.0
        last_sample_count = self.telemetry.attitude_samples
        previous_yaw = self.telemetry.yaw_deg
        accumulated_deg = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(channels)
                next_send = now + self.period_s
            self._receive_pending()
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    f"Vehicle left ALT_HOLD during {label} yaw; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            if self.telemetry.attitude_samples != last_sample_count:
                last_sample_count = self.telemetry.attitude_samples
                current_yaw = self.telemetry.yaw_deg
                if previous_yaw is not None and current_yaw is not None:
                    delta = (current_yaw - previous_yaw + 180.0) % 360.0 - 180.0
                    accumulated_deg += delta
                    self._phase(
                        f"{label} yaw progress={accumulated_deg:+.1f} deg "
                        f"heading={current_yaw:.1f} deg"
                    )
                    if abs(accumulated_deg) >= self.turn_angle_deg:
                        return
                previous_yaw = current_yaw
            time.sleep(min(0.005, self.period_s))
        raise ScenarioError(
            f"Timed out waiting for measured {label} yaw to reach "
            f"{self.turn_angle_deg:.0f} degrees; measured {accumulated_deg:+.1f}; "
            f"last telemetry: {self.telemetry.describe()}"
        )

    def _wait_for_settled_alt_hold(self) -> None:
        self._phase("Waiting for ALT_HOLD vertical speed to settle")
        last_sample_count = self.telemetry.altitude_samples
        consecutive_samples = 0

        def settled() -> bool:
            nonlocal last_sample_count, consecutive_samples
            if self.telemetry.altitude_samples == last_sample_count:
                return consecutive_samples >= 3
            last_sample_count = self.telemetry.altitude_samples
            speed = self.telemetry.vertical_speed_m_s
            if speed is not None and abs(speed) <= 0.25:
                consecutive_samples += 1
            else:
                consecutive_samples = 0
            return consecutive_samples >= 3

        self._wait_for(
            ALT_HOLD_ARMED,
            settled,
            self.landing_timeout_s,
            "three settled ALT_HOLD altitude samples",
        )
        self._phase(
            "ALT_HOLD settled at "
            f"{self.telemetry.altitude_m:.2f} m, "
            f"vertical speed {self.telemetry.vertical_speed_m_s:+.2f} m/s"
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
    parser.add_argument("--turn-angle", type=float, default=360.0)
    parser.add_argument("--yaw-rate", type=float, default=10.0)
    parser.add_argument("--direction-pause", type=float, default=1.0)
    parser.add_argument("--cw-yaw-rc", type=int, default=1650)
    parser.add_argument("--descent-rate", type=float, default=1.0)
    parser.add_argument("--descent-velocity-kp", type=float, default=50.0)
    parser.add_argument("--descent-min-throttle", type=int, default=1500)
    parser.add_argument("--descent-hover-throttle", type=int, default=1660)
    parser.add_argument("--descent-max-throttle", type=int, default=1800)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0 or args.yaw_rate <= 0 or args.turn_angle <= 0:
        raise SystemExit("rate, yaw rate, and turn angle must be positive")
    if args.state_timeout <= 0 or args.flight_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if args.direction_pause < 0:
        raise SystemExit("--direction-pause cannot be negative")
    if not RC_MID < args.cw_yaw_rc <= RC_MAX:
        raise SystemExit("--cw-yaw-rc must be between 1501 and 2000")
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

    scenario = AutoYawScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=0.0,
        descent_throttle=args.descent_min_throttle,
        turn_angle_deg=args.turn_angle,
        yaw_rate_dps=args.yaw_rate,
        direction_pause_s=args.direction_pause,
        cw_yaw_rc=args.cw_yaw_rc,
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

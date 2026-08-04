#!/usr/bin/env python3
"""Auto takeoff, balanced ALT_HOLD roll pulses, and controlled landing."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

from send_rc import (
    ALT_HOLD_ARMED,
    ARM,
    ARM_IN_MANUAL,
    AUTO_TAKEOFF,
    AUTO_TAKEOFF_ARMED,
    MANUAL,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    PITCH,
    RC_MAX,
    RC_MID,
    RC_MIN,
    ROLL,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    STATE_TAKEOFF,
    THROTTLE,
    YAW,
    ScenarioError,
)
from send_rc_auto_yaw import AutoYawScenario


def alt_hold_roll_channels(roll: int) -> tuple[int, ...]:
    channels = list(ALT_HOLD_ARMED)
    channels[ROLL] = roll
    return tuple(channels)


class AutoRollScenario(AutoYawScenario):
    def __init__(
        self,
        *,
        roll_amplitude: int = 200,
        pulse_duration_s: float = 2.0,
        max_roll_angle_deg: float = 25.0,
        max_altitude_drift_m: float = 1.0,
        recovery_angle_deg: float = 3.0,
        recovery_vertical_speed_m_s: float = 0.25,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.roll_amplitude = roll_amplitude
        self.pulse_duration_s = pulse_duration_s
        self.max_roll_angle_deg = max_roll_angle_deg
        self.max_altitude_drift_m = max_altitude_drift_m
        self.recovery_angle_deg = recovery_angle_deg
        self.recovery_vertical_speed_m_s = recovery_vertical_speed_m_s
        self.left_channels = alt_hold_roll_channels(RC_MID - roll_amplitude)
        self.right_channels = alt_hold_roll_channels(RC_MID + roll_amplitude)
        self.center_channels = alt_hold_roll_channels(RC_MID)
        self._maneuver_start_altitude_m: float | None = None

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

            if self.telemetry.altitude_m is None:
                raise ScenarioError("Cannot start roll test without altitude telemetry")
            self._maneuver_start_altitude_m = self.telemetry.altitude_m
            self._run_roll_pattern()
            self._wait_for_roll_recovery()

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

    def _run_roll_pattern(self) -> None:
        self._command_roll_phase(
            "left",
            self.left_channels,
            self.pulse_duration_s,
        )
        self._command_roll_phase(
            "right",
            self.right_channels,
            self.pulse_duration_s * 2.0,
        )
        self._command_roll_phase(
            "left recovery",
            self.left_channels,
            self.pulse_duration_s,
        )

    def _command_roll_phase(
        self,
        label: str,
        channels: Sequence[int],
        duration_s: float,
    ) -> None:
        command_roll = int(channels[ROLL])
        self._phase(
            f"Roll phase={label} command_rc={command_roll} "
            f"duration={duration_s:.1f} s"
        )
        deadline = time.monotonic() + duration_s
        next_send = 0.0
        last_attitude_samples = self.telemetry.attitude_samples
        received_attitude = False
        started_at = time.monotonic()
        previous_roll = self.telemetry.roll_deg
        previous_attitude_time_s: float | None = None
        peak_abs_roll_deg = 0.0
        minimum_altitude_m = self.telemetry.altitude_m
        maximum_altitude_m = self.telemetry.altitude_m
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(channels)
                next_send = now + self.period_s
            self._receive_pending()
            self._check_roll_safety(label)
            if self.telemetry.attitude_samples != last_attitude_samples:
                last_attitude_samples = self.telemetry.attitude_samples
                received_attitude = True
                attitude_time_s = time.monotonic()
                roll = self.telemetry.roll_deg
                roll_rate_deg_s = 0.0
                if (
                    roll is not None
                    and previous_roll is not None
                    and previous_attitude_time_s is not None
                    and attitude_time_s > previous_attitude_time_s
                ):
                    roll_rate_deg_s = (
                        roll - previous_roll
                    ) / (attitude_time_s - previous_attitude_time_s)
                if roll is not None:
                    peak_abs_roll_deg = max(peak_abs_roll_deg, abs(roll))
                    previous_roll = roll
                previous_attitude_time_s = attitude_time_s
                altitude = self.telemetry.altitude_m
                if altitude is not None:
                    minimum_altitude_m = (
                        altitude
                        if minimum_altitude_m is None
                        else min(minimum_altitude_m, altitude)
                    )
                    maximum_altitude_m = (
                        altitude
                        if maximum_altitude_m is None
                        else max(maximum_altitude_m, altitude)
                    )
                self._phase(
                    f"Roll phase={label} command_rc={command_roll} "
                    f"elapsed={now - started_at:.2f} s "
                    f"roll={self.telemetry.roll_deg:+.1f} deg "
                    f"roll_rate={roll_rate_deg_s:+.1f} deg/s "
                    f"pitch={self.telemetry.pitch_deg:+.1f} deg "
                    f"yaw={self.telemetry.yaw_deg:.1f} deg "
                    f"altitude={self.telemetry.altitude_m:.2f} m"
                )
            time.sleep(min(0.005, self.period_s))
        if not received_attitude:
            raise ScenarioError(f"No attitude telemetry during roll phase {label}")
        altitude_span_m = 0.0
        if minimum_altitude_m is not None and maximum_altitude_m is not None:
            altitude_span_m = maximum_altitude_m - minimum_altitude_m
        self._phase(
            f"Roll phase={label} complete peak_abs_roll={peak_abs_roll_deg:.1f} deg "
            f"altitude_span={altitude_span_m:.2f} m"
        )

    def _check_roll_safety(self, label: str) -> None:
        if self.telemetry.state != STATE_ALT_HOLD:
            raise ScenarioError(
                f"Vehicle left ALT_HOLD during roll phase {label}; "
                f"last telemetry: {self.telemetry.describe()}"
            )
        roll = self.telemetry.roll_deg
        if roll is not None and abs(roll) > self.max_roll_angle_deg:
            raise ScenarioError(
                f"Roll safety limit exceeded during {label}: {roll:+.1f} deg"
            )
        altitude = self.telemetry.altitude_m
        start_altitude = self._maneuver_start_altitude_m
        if (
            altitude is not None
            and start_altitude is not None
            and abs(altitude - start_altitude) > self.max_altitude_drift_m
        ):
            raise ScenarioError(
                f"Altitude drift safety limit exceeded during {label}: "
                f"start={start_altitude:.2f} m current={altitude:.2f} m"
            )

    def _wait_for_roll_recovery(self) -> None:
        self._phase("Centering roll and waiting for attitude recovery")
        last_attitude_samples = self.telemetry.attitude_samples
        consecutive_samples = 0

        def recovered() -> bool:
            nonlocal last_attitude_samples, consecutive_samples
            self._check_roll_safety("center recovery")
            if self.telemetry.attitude_samples == last_attitude_samples:
                return consecutive_samples >= 3
            last_attitude_samples = self.telemetry.attitude_samples
            roll = self.telemetry.roll_deg
            pitch = self.telemetry.pitch_deg
            vertical_speed = self.telemetry.vertical_speed_m_s
            within_limits = (
                roll is not None
                and pitch is not None
                and vertical_speed is not None
                and abs(roll) <= self.recovery_angle_deg
                and abs(pitch) <= self.recovery_angle_deg
                and abs(vertical_speed) <= self.recovery_vertical_speed_m_s
            )
            consecutive_samples = consecutive_samples + 1 if within_limits else 0
            return consecutive_samples >= 3

        self._wait_for(
            self.center_channels,
            recovered,
            self.landing_timeout_s,
            "three centered and vertically settled attitude samples",
        )
        self._phase(
            f"Roll recovery complete roll={self.telemetry.roll_deg:+.1f} deg "
            f"pitch={self.telemetry.pitch_deg:+.1f} deg "
            f"vertical_speed={self.telemetry.vertical_speed_m_s:+.2f} m/s"
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
    parser.add_argument("--roll-amplitude", type=int, default=200)
    parser.add_argument("--pulse-duration", type=float, default=2.0)
    parser.add_argument("--max-roll-angle", type=float, default=25.0)
    parser.add_argument("--max-altitude-drift", type=float, default=1.0)
    parser.add_argument("--descent-rate", type=float, default=1.0)
    parser.add_argument("--descent-velocity-kp", type=float, default=50.0)
    parser.add_argument("--descent-min-throttle", type=int, default=1500)
    parser.add_argument("--descent-hover-throttle", type=int, default=1660)
    parser.add_argument("--descent-max-throttle", type=int, default=1800)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0 or args.pulse_duration <= 0:
        raise SystemExit("rate and pulse duration must be positive")
    if args.state_timeout <= 0 or args.flight_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if not 1 <= args.roll_amplitude <= 400:
        raise SystemExit("--roll-amplitude must be between 1 and 400")
    if args.max_roll_angle <= 0 or args.max_altitude_drift <= 0:
        raise SystemExit("roll and altitude safety limits must be positive")
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

    scenario = AutoRollScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=0.0,
        descent_throttle=args.descent_min_throttle,
        roll_amplitude=args.roll_amplitude,
        pulse_duration_s=args.pulse_duration,
        max_roll_angle_deg=args.max_roll_angle,
        max_altitude_drift_m=args.max_altitude_drift,
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

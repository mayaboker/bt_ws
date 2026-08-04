#!/usr/bin/env python3
"""Auto takeoff, balanced ALT_HOLD pitch pulses, and controlled landing."""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Sequence

from send_rc import (
    ALT_HOLD_ARMED,
    ARM,
    AUTO_TAKEOFF,
    MANUAL,
    PITCH,
    RC_MAX,
    RC_MID,
    RC_MIN,
    ROLL,
    STATE_ALT_HOLD,
    THROTTLE,
    YAW,
    ScenarioError,
)
from send_rc_auto_roll import AutoRollScenario

MAX_SAFE_PITCH_AMPLITUDE = 100


def alt_hold_pitch_channels(pitch: int) -> tuple[int, ...]:
    channels = list(ALT_HOLD_ARMED)
    channels[PITCH] = pitch
    return tuple(channels)


class AutoPitchScenario(AutoRollScenario):
    def __init__(
        self,
        *,
        pitch_amplitude: int = 100,
        pulse_duration_s: float = 2.0,
        max_pitch_angle_deg: float = 25.0,
        max_altitude_drift_m: float = 1.0,
        recovery_angle_deg: float = 3.0,
        recovery_vertical_speed_m_s: float = 0.25,
        **kwargs,
    ) -> None:
        if not 1 <= pitch_amplitude <= MAX_SAFE_PITCH_AMPLITUDE:
            raise ValueError(
                "pitch_amplitude must be between 1 and "
                f"{MAX_SAFE_PITCH_AMPLITUDE} RC"
            )
        super().__init__(
            roll_amplitude=1,
            pulse_duration_s=pulse_duration_s,
            max_roll_angle_deg=max_pitch_angle_deg,
            max_altitude_drift_m=max_altitude_drift_m,
            recovery_angle_deg=recovery_angle_deg,
            recovery_vertical_speed_m_s=recovery_vertical_speed_m_s,
            **kwargs,
        )
        self.pitch_amplitude = pitch_amplitude
        self.max_pitch_angle_deg = max_pitch_angle_deg
        self.forward_channels = alt_hold_pitch_channels(
            RC_MID - pitch_amplitude
        )
        self.backward_channels = alt_hold_pitch_channels(
            RC_MID + pitch_amplitude
        )
        self.center_channels = alt_hold_pitch_channels(RC_MID)

    def _run_roll_pattern(self) -> None:
        self._command_smooth_pitch_pattern()

    def _pitch_command_at(self, elapsed_s: float) -> int:
        unit = self.pulse_duration_s
        knots = (
            (0.0, RC_MID),
            (1.0 * unit, RC_MID - self.pitch_amplitude),
            (2.0 * unit, RC_MID),
            (4.0 * unit, RC_MID + self.pitch_amplitude),
            (6.0 * unit, RC_MID),
            (7.0 * unit, RC_MID - self.pitch_amplitude),
            (8.0 * unit, RC_MID),
        )
        elapsed_s = max(0.0, min(float(elapsed_s), knots[-1][0]))
        for (start_s, start_rc), (end_s, end_rc) in zip(knots, knots[1:]):
            if elapsed_s <= end_s:
                fraction = (elapsed_s - start_s) / (end_s - start_s)
                smooth_fraction = (1.0 - math.cos(math.pi * fraction)) / 2.0
                return round(start_rc + (end_rc - start_rc) * smooth_fraction)
        return RC_MID

    def _command_smooth_pitch_pattern(self) -> None:
        duration_s = self.pulse_duration_s * 8.0
        self._phase(
            "Starting smooth balanced pitch pattern "
            f"duration={duration_s:.1f} s range="
            f"{RC_MID - self.pitch_amplitude}..{RC_MID + self.pitch_amplitude}"
        )
        started_at = time.monotonic()
        deadline = started_at + duration_s
        next_send = 0.0
        last_attitude_samples = self.telemetry.attitude_samples
        received_attitude = False
        previous_pitch = self.telemetry.pitch_deg
        previous_attitude_time_s: float | None = None
        peak_abs_pitch_deg = 0.0
        minimum_altitude_m = self.telemetry.altitude_m
        maximum_altitude_m = self.telemetry.altitude_m

        while time.monotonic() < deadline:
            now = time.monotonic()
            elapsed_s = now - started_at
            command_pitch = self._pitch_command_at(elapsed_s)
            channels = alt_hold_pitch_channels(command_pitch)
            if now >= next_send:
                self._send_rc(channels)
                next_send = now + self.period_s
            self._receive_pending()
            self._check_pitch_safety("smooth pattern")
            if self.telemetry.attitude_samples != last_attitude_samples:
                last_attitude_samples = self.telemetry.attitude_samples
                received_attitude = True
                attitude_time_s = time.monotonic()
                pitch = self.telemetry.pitch_deg
                pitch_rate_deg_s = 0.0
                if (
                    pitch is not None
                    and previous_pitch is not None
                    and previous_attitude_time_s is not None
                    and attitude_time_s > previous_attitude_time_s
                ):
                    pitch_rate_deg_s = (
                        pitch - previous_pitch
                    ) / (attitude_time_s - previous_attitude_time_s)
                if pitch is not None:
                    peak_abs_pitch_deg = max(peak_abs_pitch_deg, abs(pitch))
                    previous_pitch = pitch
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
                    f"Pitch smooth command_rc={command_pitch} "
                    f"elapsed={elapsed_s:.2f}/{duration_s:.1f} s "
                    f"pitch={self.telemetry.pitch_deg:+.1f} deg "
                    f"pitch_rate={pitch_rate_deg_s:+.1f} deg/s "
                    f"roll={self.telemetry.roll_deg:+.1f} deg "
                    f"yaw={self.telemetry.yaw_deg:.1f} deg "
                    f"altitude={self.telemetry.altitude_m:.2f} m"
                )
            time.sleep(min(0.005, self.period_s))

        if not received_attitude:
            raise ScenarioError("No attitude telemetry during smooth pitch pattern")
        altitude_span_m = 0.0
        if minimum_altitude_m is not None and maximum_altitude_m is not None:
            altitude_span_m = maximum_altitude_m - minimum_altitude_m
        self._phase(
            "Smooth pitch pattern complete "
            f"peak_abs_pitch={peak_abs_pitch_deg:.1f} deg "
            f"altitude_span={altitude_span_m:.2f} m"
        )

    def _command_pitch_phase(
        self,
        label: str,
        channels: Sequence[int],
        duration_s: float,
    ) -> None:
        command_pitch = int(channels[PITCH])
        self._phase(
            f"Pitch phase={label} command_rc={command_pitch} "
            f"duration={duration_s:.1f} s"
        )
        deadline = time.monotonic() + duration_s
        next_send = 0.0
        last_attitude_samples = self.telemetry.attitude_samples
        received_attitude = False
        started_at = time.monotonic()
        previous_pitch = self.telemetry.pitch_deg
        previous_attitude_time_s: float | None = None
        peak_abs_pitch_deg = 0.0
        minimum_altitude_m = self.telemetry.altitude_m
        maximum_altitude_m = self.telemetry.altitude_m

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(channels)
                next_send = now + self.period_s
            self._receive_pending()
            self._check_pitch_safety(label)
            if self.telemetry.attitude_samples != last_attitude_samples:
                last_attitude_samples = self.telemetry.attitude_samples
                received_attitude = True
                attitude_time_s = time.monotonic()
                pitch = self.telemetry.pitch_deg
                pitch_rate_deg_s = 0.0
                if (
                    pitch is not None
                    and previous_pitch is not None
                    and previous_attitude_time_s is not None
                    and attitude_time_s > previous_attitude_time_s
                ):
                    pitch_rate_deg_s = (
                        pitch - previous_pitch
                    ) / (attitude_time_s - previous_attitude_time_s)
                if pitch is not None:
                    peak_abs_pitch_deg = max(peak_abs_pitch_deg, abs(pitch))
                    previous_pitch = pitch
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
                    f"Pitch phase={label} command_rc={command_pitch} "
                    f"elapsed={now - started_at:.2f} s "
                    f"pitch={self.telemetry.pitch_deg:+.1f} deg "
                    f"pitch_rate={pitch_rate_deg_s:+.1f} deg/s "
                    f"roll={self.telemetry.roll_deg:+.1f} deg "
                    f"yaw={self.telemetry.yaw_deg:.1f} deg "
                    f"altitude={self.telemetry.altitude_m:.2f} m"
                )
            time.sleep(min(0.005, self.period_s))

        if not received_attitude:
            raise ScenarioError(f"No attitude telemetry during pitch phase {label}")
        altitude_span_m = 0.0
        if minimum_altitude_m is not None and maximum_altitude_m is not None:
            altitude_span_m = maximum_altitude_m - minimum_altitude_m
        self._phase(
            f"Pitch phase={label} complete "
            f"peak_abs_pitch={peak_abs_pitch_deg:.1f} deg "
            f"altitude_span={altitude_span_m:.2f} m"
        )

    def _check_pitch_safety(self, label: str) -> None:
        if self.telemetry.state != STATE_ALT_HOLD:
            raise ScenarioError(
                f"Vehicle left ALT_HOLD during pitch phase {label}; "
                f"last telemetry: {self.telemetry.describe()}"
            )
        pitch = self.telemetry.pitch_deg
        if pitch is not None and abs(pitch) > self.max_pitch_angle_deg:
            raise ScenarioError(
                f"Pitch safety limit exceeded during {label}: {pitch:+.1f} deg"
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
        self._phase("Centering pitch and waiting for attitude recovery")
        last_attitude_samples = self.telemetry.attitude_samples
        consecutive_samples = 0

        def recovered() -> bool:
            nonlocal last_attitude_samples, consecutive_samples
            self._check_pitch_safety("center recovery")
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
            f"Pitch recovery complete pitch={self.telemetry.pitch_deg:+.1f} deg "
            f"roll={self.telemetry.roll_deg:+.1f} deg "
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
    parser.add_argument("--pitch-amplitude", type=int, default=100)
    parser.add_argument("--pulse-duration", type=float, default=2.0)
    parser.add_argument("--max-pitch-angle", type=float, default=25.0)
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
    if not 1 <= args.pitch_amplitude <= MAX_SAFE_PITCH_AMPLITUDE:
        raise SystemExit(
            "--pitch-amplitude must be between 1 and "
            f"{MAX_SAFE_PITCH_AMPLITUDE}"
        )
    if args.max_pitch_angle <= 0 or args.max_altitude_drift <= 0:
        raise SystemExit("pitch and altitude safety limits must be positive")
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

    scenario = AutoPitchScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=0.0,
        descent_throttle=args.descent_min_throttle,
        pitch_amplitude=args.pitch_amplitude,
        pulse_duration_s=args.pulse_duration,
        max_pitch_angle_deg=args.max_pitch_angle,
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

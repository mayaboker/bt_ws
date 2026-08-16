#!/usr/bin/env python3
"""Auto takeoff, hold a forward pitch in ALT_HOLD, and land safely."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
import time
from typing import Any, Sequence

from send_rc import PITCH, RC_MAX, RC_MID, RC_MIN, STATE_ALT_HOLD, ScenarioError
from send_rc_auto_pitch import AutoPitchScenario, alt_hold_pitch_channels
from send_rc_takeoff_diagnostic import DiagnosticTelemetry

SCENARIO_BANNER = """\
==============================================================================
bt-app Automatic Takeoff / Aggressive Forward Pitch Hold SITL Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Arm in MANUAL and request automatic takeoff.
  2. Wait for ALT_HOLD and stable vertical speed.
  3. Use attitude feedback to approach about 10 degrees forward pitch.
  4. Hold forward pitch for 10 seconds while ALT_HOLD controls throttle.
  5. Center pitch, verify attitude and vertical-speed recovery.
  6. Descend in MANUAL, confirm touchdown, and disarm.

Pitch convention:
  Negative pitch is forward. The default target is -10 degrees.

Safety behavior:
  Pitch commands are bounded to 1300..1500 RC by default. The maneuver aborts
  on excessive attitude, altitude drift, loss of ALT_HOLD, or stale attitude.
=============================================================================="""


class PitchDiagnosticTelemetry(DiagnosticTelemetry):
    """Diagnostic telemetry with fresh-attitude sample tracking."""

    def __init__(self) -> None:
        super().__init__()
        self.attitude_samples = 0

    def consume(self, message: Any) -> bool:
        changed = super().consume(message)
        if message.get_type() == "ATTITUDE":
            self.attitude_samples += 1
        return changed


class ForwardPitchHoldScenario(AutoPitchScenario):
    FIELDNAMES = (
        "local_time",
        "elapsed_s",
        "sample_source",
        "phase",
        "state",
        "armed",
        "altitude_setpoint_m",
        "altitude_m",
        "vertical_speed_m_s",
        "roll_deg",
        "pitch_deg",
        "yaw_deg",
        "joystick_roll_pwm",
        "joystick_pitch_pwm",
        "joystick_throttle_pwm",
        "joystick_yaw_pwm",
        "output_roll_pwm",
        "output_pitch_pwm",
        "output_throttle_pwm",
        "output_yaw_pwm",
        "altitude_error_m",
        "pitch_target_deg",
        "pitch_error_deg",
    )

    def __init__(
        self,
        *,
        target_pitch_deg: float = -10.0,
        hold_duration_s: float = 10.0,
        pitch_feedforward_rc: int = 100,
        pitch_kp_rc_per_deg: float = 4.0,
        maximum_pitch_command_rc: int = 200,
        output_path: Path = Path("logs/pitch_hold_diagnostic.csv"),
        **kwargs,
    ) -> None:
        if target_pitch_deg >= 0.0:
            raise ValueError("target_pitch_deg must be negative for forward pitch")
        if hold_duration_s <= 0.0:
            raise ValueError("hold_duration_s must be positive")
        if not 1 <= pitch_feedforward_rc <= maximum_pitch_command_rc:
            raise ValueError("pitch feedforward must be within the command limit")
        if pitch_kp_rc_per_deg <= 0.0:
            raise ValueError("pitch gain must be positive")
        if not 1 <= maximum_pitch_command_rc <= 300:
            raise ValueError("maximum pitch command must be between 1 and 300 RC")
        super().__init__(pitch_amplitude=1, **kwargs)
        self.target_pitch_deg = float(target_pitch_deg)
        self.hold_duration_s = float(hold_duration_s)
        self.pitch_feedforward_rc = int(pitch_feedforward_rc)
        self.pitch_kp_rc_per_deg = float(pitch_kp_rc_per_deg)
        self.maximum_pitch_command_rc = int(maximum_pitch_command_rc)
        self.telemetry = PitchDiagnosticTelemetry()
        self.output_path = output_path.expanduser().resolve()
        self._requested_channels = alt_hold_pitch_channels(RC_MID)
        self._diagnostic_phase = "initializing"
        self._diagnostic_started_at_s = time.monotonic()
        self._csv_file: Any = None
        self._csv_writer: csv.DictWriter | None = None
        self._banner_printed = False

    def _print_banner(self) -> None:
        if self._banner_printed:
            return
        print(SCENARIO_BANNER, flush=True)
        print(f"Diagnostic CSV: {self.output_path}", flush=True)
        self._banner_printed = True

    def run(self) -> None:
        self._open_recording()
        try:
            super().run()
        finally:
            self._close_recording()

    def _open_recording(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._csv_file = self.output_path.open("w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(
            self._csv_file,
            fieldnames=self.FIELDNAMES,
        )
        self._csv_writer.writeheader()
        self._csv_file.flush()

    def _close_recording(self) -> None:
        if self._csv_file is not None:
            self._csv_file.flush()
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None
        print(f"Diagnostic CSV saved to: {self.output_path}", flush=True)

    def _phase(self, message: str, color: str | None = None) -> None:
        phase_prefixes = (
            "Waiting for bt-app",
            "Arming in MANUAL",
            "Requesting automatic",
            "Waiting for automatic",
            "Waiting for ALT_HOLD",
            "ALT_HOLD settled",
            "Starting forward",
            "Forward pitch hold complete",
            "Centering pitch",
            "Pitch recovery complete",
            "Switching to MANUAL",
            "Waiting for controlled touchdown",
            "Disarming and waiting",
            "Scenario completed",
        )
        if message.startswith(phase_prefixes):
            self._diagnostic_phase = message
        super()._phase(message, color=color)

    def _send_rc(self, channels: Sequence[int]) -> None:
        self._requested_channels = tuple(int(value) for value in channels)
        super()._send_rc(channels)

    def _receive_pending(self) -> None:
        if self._socket is None:
            return
        while True:
            try:
                payload, _address = self._socket.recvfrom(4096)
            except BlockingIOError:
                return
            for byte in payload:
                message = self._parser.parse_char(bytes([byte]))
                if message is None:
                    continue
                previous_state = self.telemetry.state
                changed = self.telemetry.consume(message)
                if changed:
                    state_changed = self.telemetry.state != previous_state
                    self._phase(
                        self.telemetry.describe(),
                        color="\033[1;36m" if state_changed else None,
                    )
                if message.get_type() in (
                    "GLOBAL_POSITION_INT",
                    "ATTITUDE",
                    "NAMED_VALUE_FLOAT",
                    "RC_CHANNELS",
                    "V2_EXTENSION",
                ):
                    self._write_snapshot(message.get_type())

    def _write_snapshot(self, sample_source: str) -> None:
        if self._csv_writer is None:
            return
        output = self.telemetry.output_channels

        def output_channel(index: int) -> int | None:
            return None if output is None else output[index]

        altitude = self.telemetry.altitude_m
        altitude_setpoint = self.telemetry.altitude_setpoint_m
        pitch = self.telemetry.pitch_deg
        self._csv_writer.writerow({
            "local_time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "elapsed_s": f"{time.monotonic() - self._diagnostic_started_at_s:.6f}",
            "sample_source": sample_source,
            "phase": self._diagnostic_phase,
            "state": self.telemetry.state,
            "armed": int(self.telemetry.armed),
            "altitude_setpoint_m": altitude_setpoint,
            "altitude_m": altitude,
            "vertical_speed_m_s": self.telemetry.vertical_speed_m_s,
            "roll_deg": self.telemetry.roll_deg,
            "pitch_deg": pitch,
            "yaw_deg": self.telemetry.yaw_deg,
            "joystick_roll_pwm": self._requested_channels[0],
            "joystick_pitch_pwm": self._requested_channels[1],
            "joystick_throttle_pwm": self._requested_channels[2],
            "joystick_yaw_pwm": self._requested_channels[3],
            "output_roll_pwm": output_channel(0),
            "output_pitch_pwm": output_channel(1),
            "output_throttle_pwm": output_channel(2),
            "output_yaw_pwm": output_channel(3),
            "altitude_error_m": (
                None if altitude is None or altitude_setpoint is None
                else altitude_setpoint - altitude
            ),
            "pitch_target_deg": self.target_pitch_deg,
            "pitch_error_deg": (
                None if pitch is None else self.target_pitch_deg - pitch
            ),
        })
        if self._csv_file is not None:
            self._csv_file.flush()

    def _run_roll_pattern(self) -> None:
        self._hold_forward_pitch()

    def _pitch_rc_for_attitude(self, pitch_deg: float) -> int:
        error_deg = self.target_pitch_deg - float(pitch_deg)
        command_offset = -self.pitch_feedforward_rc + (
            self.pitch_kp_rc_per_deg * error_deg
        )
        command_offset = max(
            -self.maximum_pitch_command_rc,
            min(0.0, command_offset),
        )
        return round(RC_MID + command_offset)

    def _hold_forward_pitch(self) -> None:
        self._phase(
            "Starting forward pitch hold "
            f"target={self.target_pitch_deg:+.1f} deg "
            f"duration={self.hold_duration_s:.1f} s"
        )
        started_at = time.monotonic()
        deadline = started_at + self.hold_duration_s
        next_send = 0.0
        last_attitude_samples = self.telemetry.attitude_samples
        last_attitude_received_at = started_at
        minimum_altitude = self.telemetry.altitude_m
        maximum_altitude = self.telemetry.altitude_m
        peak_forward_pitch = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()
            pitch = self.telemetry.pitch_deg
            if pitch is None:
                raise ScenarioError("No pitch telemetry for feedback control")
            command_rc = self._pitch_rc_for_attitude(pitch)
            if now >= next_send:
                self._send_rc(alt_hold_pitch_channels(command_rc))
                next_send = now + self.period_s
            self._receive_pending()
            self._check_pitch_safety("forward hold")

            if self.telemetry.attitude_samples != last_attitude_samples:
                last_attitude_samples = self.telemetry.attitude_samples
                last_attitude_received_at = now
                pitch = self.telemetry.pitch_deg
                altitude = self.telemetry.altitude_m
                if pitch is not None:
                    peak_forward_pitch = min(peak_forward_pitch, pitch)
                if altitude is not None:
                    minimum_altitude = (
                        altitude if minimum_altitude is None
                        else min(minimum_altitude, altitude)
                    )
                    maximum_altitude = (
                        altitude if maximum_altitude is None
                        else max(maximum_altitude, altitude)
                    )
                self._phase(
                    f"Forward hold target={self.target_pitch_deg:+.1f} deg "
                    f"command_rc={command_rc} "
                    f"elapsed={now - started_at:.2f}/{self.hold_duration_s:.1f} s "
                    f"pitch={self.telemetry.pitch_deg:+.1f} deg "
                    f"roll={self.telemetry.roll_deg:+.1f} deg "
                    f"altitude={self.telemetry.altitude_m:.2f} m "
                    f"vertical_speed={self.telemetry.vertical_speed_m_s:+.2f} m/s"
                )
            elif now - last_attitude_received_at > 1.0:
                raise ScenarioError("Attitude telemetry stale for more than 1 second")
            time.sleep(min(0.005, self.period_s))

        altitude_span = 0.0
        if minimum_altitude is not None and maximum_altitude is not None:
            altitude_span = maximum_altitude - minimum_altitude
        self._phase(
            "Forward pitch hold complete "
            f"peak_forward_pitch={peak_forward_pitch:+.1f} deg "
            f"altitude_span={altitude_span:.2f} m"
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
    parser.add_argument("--flight-timeout", type=float, default=120.0)
    parser.add_argument("--target-pitch", type=float, default=-10.0)
    parser.add_argument("--hold-duration", type=float, default=10.0)
    parser.add_argument("--pitch-feedforward", type=int, default=100)
    parser.add_argument("--pitch-kp", type=float, default=4.0)
    parser.add_argument("--max-pitch-command", type=int, default=200)
    parser.add_argument("--max-pitch-angle", type=float, default=20.0)
    parser.add_argument("--max-altitude-drift", type=float, default=1.5)
    parser.add_argument("--descent-rate", type=float, default=0.5)
    parser.add_argument("--descent-velocity-kp", type=float, default=50.0)
    parser.add_argument("--descent-min-throttle", type=int, default=1500)
    parser.add_argument("--descent-hover-throttle", type=int, default=1660)
    parser.add_argument("--descent-max-throttle", type=int, default=1800)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/pitch_hold_diagnostic.csv"),
        help="diagnostic CSV output path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0.0 or args.state_timeout <= 0.0 or args.flight_timeout <= 0.0:
        raise SystemExit("rate and timeouts must be positive")
    if args.max_pitch_angle <= abs(args.target_pitch):
        raise SystemExit("--max-pitch-angle must exceed the target magnitude")
    if args.max_altitude_drift <= 0.0:
        raise SystemExit("--max-altitude-drift must be positive")
    if args.descent_rate <= 0.0 or args.descent_velocity_kp <= 0.0:
        raise SystemExit("descent rate and velocity gain must be positive")
    if not (
        RC_MIN <= args.descent_min_throttle < args.descent_hover_throttle
        < args.descent_max_throttle <= RC_MAX
    ):
        raise SystemExit("invalid descent throttle range")

    scenario = ForwardPitchHoldScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=0.0,
        descent_throttle=args.descent_min_throttle,
        target_pitch_deg=args.target_pitch,
        hold_duration_s=args.hold_duration,
        pitch_feedforward_rc=args.pitch_feedforward,
        pitch_kp_rc_per_deg=args.pitch_kp,
        maximum_pitch_command_rc=args.max_pitch_command,
        output_path=args.output,
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
    except (ScenarioError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

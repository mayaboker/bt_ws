#!/usr/bin/env python3
"""Run an automatic takeoff and record synchronized diagnostic telemetry."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import math
from pathlib import Path
import struct
import sys
import time
from typing import Any, Sequence

from pymavlink import mavutil

from send_rc import (
    ALT_HOLD_ARMED,
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    ARM_IN_MANUAL,
    AUTO_TAKEOFF_ARMED,
    MANUAL_DISARMED,
    NEUTRAL_DISARMED,
    STATE_ALT_HOLD,
    STATE_IDLE,
    STATE_MANUAL,
    STATE_NAMES,
    STATE_TAKEOFF,
    THROTTLE,
    MavlinkRcScenario,
    ScenarioError,
    Telemetry,
    build_parser as build_base_parser,
)


CHANNEL_STATUS_MESSAGE_TYPE = 1
CHANNEL_STATUS_VERSION = 1
CHANNEL_STATUS_FORMAT = "<BBBH8H"
CHANNEL_STATUS_SIZE = struct.calcsize(CHANNEL_STATUS_FORMAT)
PARAMETERS = (
    "TAKEOFF_ALT",
    "TAKEOFF_RATE",
    "ALT_KP",
    "ALT_KI",
    "ALT_KD",
    "ALT_OUT_LIMIT",
    "HOV_BASELINE",
)


def decode_parameter_value(message: Any) -> float | int:
    """Decode the bytewise value carried by a MAVLink ``PARAM_VALUE``."""

    parameter_type = int(message.param_type)
    wire_value = float(message.param_value)
    if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_REAL32:
        return wire_value

    raw = struct.pack("<f", wire_value)
    if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_INT32:
        return struct.unpack("<i", raw)[0]
    if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_UINT8:
        value = struct.unpack("<I", raw)[0]
        if value > 0xFF:
            raise ValueError(f"invalid MAV_PARAM_TYPE_UINT8 value {value}")
        return value
    raise ValueError(f"unsupported MAVLink parameter type {parameter_type}")

SCENARIO_BANNER = """\
==============================================================================
bt-app Takeoff Controller Diagnostic Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Wait for bt-app telemetry and read the active takeoff parameters.
  2. Arm in MANUAL and request automatic takeoff.
  3. Record TAKEOFF and the transition into ALT_HOLD.
  4. Remain in ALT_HOLD so the post-transition response is visible.
  5. Switch to MANUAL, descend, disarm, and verify IDLE.

CSV data includes altitude, derived vertical speed, attitude, requested joystick
channels, and bt-app's actual controller output channels. The internal PI terms
are not available on MAVLink and are therefore not recorded as measured data.

Safety behavior:
  Before takeoff, failures send a ground-safe disarm command.
  While airborne, failures stop RC traffic so bt-app failsafe can recover.
=============================================================================="""


class DiagnosticTelemetry(Telemetry):
    """Telemetry required to evaluate the takeoff and handoff response."""

    def __init__(self) -> None:
        super().__init__()
        self.vertical_speed_m_s: float | None = None
        self.roll_deg: float | None = None
        self.pitch_deg: float | None = None
        self.yaw_deg: float | None = None
        self.output_state: int | None = None
        self.output_channels: tuple[int, ...] | None = None
        self.altitude_setpoint_m: float | None = None
        self._last_altitude_m: float | None = None
        self._last_altitude_time_s: float | None = None

    def consume(self, message: Any) -> bool:
        previous_samples = self.altitude_samples
        changed = super().consume(message)
        message_type = message.get_type()

        if self.altitude_samples != previous_samples:
            now_s = time.monotonic()
            if (
                self._last_altitude_m is not None
                and self._last_altitude_time_s is not None
                and self.altitude_m is not None
                and now_s > self._last_altitude_time_s
            ):
                self.vertical_speed_m_s = (
                    self.altitude_m - self._last_altitude_m
                ) / (now_s - self._last_altitude_time_s)
            self._last_altitude_m = self.altitude_m
            self._last_altitude_time_s = now_s

        if (
            int(message.get_srcSystem()) != APP_SYSTEM_ID
            or int(message.get_srcComponent()) != APP_COMPONENT_ID
        ):
            return changed

        if message_type == "ATTITUDE":
            self.roll_deg = math.degrees(float(message.roll))
            self.pitch_deg = math.degrees(float(message.pitch))
            self.yaw_deg = math.degrees(float(message.yaw)) % 360.0
        elif message_type == "NAMED_VALUE_FLOAT":
            name = message.name
            if isinstance(name, bytes):
                name = name.split(b"\0", 1)[0].decode("ascii", errors="replace")
            else:
                name = str(name).split("\0", 1)[0]
            if name == "alt_sp":
                self.altitude_setpoint_m = float(message.value)
        elif message_type == "RC_CHANNELS":
            channel_count = min(8, int(message.chancount))
            channels = tuple(
                int(getattr(message, f"chan{index}_raw"))
                for index in range(1, channel_count + 1)
            )
            if channel_count == 8:
                self.output_state = self.state
                self.output_channels = channels
        elif (
            message_type == "V2_EXTENSION"
            and int(message.message_type) == CHANNEL_STATUS_MESSAGE_TYPE
        ):
            values = struct.unpack(
                CHANNEL_STATUS_FORMAT,
                bytes(message.payload[:CHANNEL_STATUS_SIZE]),
            )
            version, _command, state, _flags, *channels = values
            if version == CHANNEL_STATUS_VERSION:
                self.output_state = int(state)
                self.output_channels = tuple(int(value) for value in channels)
        return changed

    def describe(self) -> str:
        description = super().describe()
        speed = (
            "unknown"
            if self.vertical_speed_m_s is None
            else f"{self.vertical_speed_m_s:+.2f} m/s"
        )
        throttle = (
            "unknown"
            if self.output_channels is None
            else str(self.output_channels[THROTTLE])
        )
        return f"{description} vertical_speed={speed} output_throttle={throttle}"


class TakeoffDiagnosticScenario(MavlinkRcScenario):
    """Automatic takeoff scenario with CSV snapshots at controller-output rate."""

    FIELDNAMES = (
        "local_time",
        "elapsed_s",
        "sample_source",
        "phase",
        "state",
        "state_id",
        "armed",
        "altitude_setpoint_m",
        "altitude_m",
        "vertical_speed_m_s",
        "roll_deg",
        "pitch_deg",
        "yaw_deg",
        "joystick_throttle_pwm",
        "output_throttle_pwm",
        "output_correction_pwm",
        "output_saturated",
        "output_roll_pwm",
        "output_pitch_pwm",
        "output_yaw_pwm",
        *PARAMETERS,
    )

    def __init__(
        self,
        *,
        output_path: Path,
        parameter_destination: tuple[str, int],
        parameter_timeout_s: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.telemetry = DiagnosticTelemetry()
        self.output_path = output_path
        self.parameter_destination = parameter_destination
        self.parameter_timeout_s = parameter_timeout_s
        self.parameter_values: dict[str, float | int] = {}
        self._requested_channels: tuple[int, ...] = tuple(NEUTRAL_DISARMED)
        self._phase_name = "initializing"
        self._start_s = time.monotonic()
        self._csv_file: Any = None
        self._csv_writer: csv.DictWriter | None = None

    def run(self) -> None:
        self._print_banner()
        self._open_recording()
        self._open()
        try:
            self._set_phase("Waiting for bt-app telemetry")
            self._wait_for(
                NEUTRAL_DISARMED,
                lambda: self.telemetry.state is not None,
                self.state_timeout_s,
                "application heartbeat",
            )
            self._read_takeoff_parameters()

            self._set_phase("Arming in MANUAL mode")
            self._wait_for_state(ARM_IN_MANUAL, STATE_MANUAL, self.state_timeout_s)

            self._set_phase("Requesting automatic takeoff from MANUAL")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_TAKEOFF,
                self.state_timeout_s,
            )
            self._airborne = True

            self._set_phase("Recording TAKEOFF until ALT_HOLD")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_ALT_HOLD,
                self.landing_timeout_s,
            )

            self._set_phase(
                f"Recording ALT_HOLD response for {self.alt_hold_duration_s:.1f} seconds"
            )
            self._send_for(ALT_HOLD_ARMED, self.alt_hold_duration_s)
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    "Vehicle left ALT_HOLD during diagnostic dwell; "
                    f"last telemetry: {self.telemetry.describe()}"
                )

            self._set_phase("Switching to MANUAL for landing")
            self._wait_for_state(
                self.manual_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            self._land_and_disarm()
            self._completed = True
            self._set_phase(f"Scenario completed; CSV saved to {self.output_path}")
        finally:
            self._cleanup()
            self._close_recording()

    def _land_and_disarm(self) -> None:
        self._set_phase("Waiting for touchdown")
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
        self._set_phase("Disarming and waiting for IDLE")
        self._wait_for(
            MANUAL_DISARMED,
            lambda: self.telemetry.state == STATE_IDLE and not self.telemetry.armed,
            self.state_timeout_s,
            "IDLE with armed flag cleared",
        )
        self._send_for(MANUAL_DISARMED, 0.5)

    def _read_takeoff_parameters(self) -> None:
        self._set_phase("Reading active takeoff parameters")
        pending = set(PARAMETERS)
        deadline = time.monotonic() + self.parameter_timeout_s
        next_request_s = 0.0
        while pending and time.monotonic() < deadline:
            now_s = time.monotonic()
            self._send_rc(NEUTRAL_DISARMED)
            if now_s >= next_request_s:
                for name in sorted(pending):
                    message = self._encoder.param_request_read_encode(
                        APP_SYSTEM_ID,
                        APP_COMPONENT_ID,
                        name.encode("ascii"),
                        -1,
                    )
                    if self._socket is not None:
                        self._socket.sendto(
                            message.pack(self._encoder), self.parameter_destination
                        )
                next_request_s = now_s + 0.5
            self._receive_pending()
            pending.difference_update(self.parameter_values)
            time.sleep(min(0.01, self.period_s))
        if pending:
            raise ScenarioError(
                "Timed out reading takeoff parameters: " + ", ".join(sorted(pending))
            )
        values = " ".join(
            f"{name}={self.parameter_values[name]:g}" for name in PARAMETERS
        )
        self._phase(f"Active parameters: {values}")

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
                if (
                    int(message.get_srcSystem()) == APP_SYSTEM_ID
                    and int(message.get_srcComponent()) == APP_COMPONENT_ID
                    and message.get_type() == "PARAM_VALUE"
                ):
                    name = message.param_id
                    if isinstance(name, bytes):
                        name = name.split(b"\0", 1)[0].decode("ascii")
                    else:
                        name = str(name).split("\0", 1)[0]
                    try:
                        value = decode_parameter_value(message)
                    except ValueError as exc:
                        self._phase(f"Ignoring parameter {name}: {exc}")
                    else:
                        self.parameter_values[name] = value

                previous_state = self.telemetry.state
                self.telemetry.consume(message)
                state_changed = self.telemetry.state != previous_state
                if state_changed:
                    self._phase(self.telemetry.describe(), color="\033[1;36m")
                if message.get_type() in ("GLOBAL_POSITION_INT", "RC_CHANNELS"):
                    self._write_snapshot(message.get_type())
                elif (
                    message.get_type() == "V2_EXTENSION"
                    and int(message.message_type) == CHANNEL_STATUS_MESSAGE_TYPE
                ):
                    self._write_snapshot("V2_CHANNEL_STATUS")

    def _write_snapshot(self, sample_source: str = "test") -> None:
        if self._csv_writer is None:
            return
        output = self.telemetry.output_channels
        baseline = self.parameter_values.get("HOV_BASELINE")
        correction = (
            None
            if baseline is None or output is None
            else output[THROTTLE] - baseline
        )
        limit = self.parameter_values.get("ALT_OUT_LIMIT")
        saturated = (
            correction is not None
            and limit is not None
            and abs(correction) >= limit - 0.5
        )
        state_id = self.telemetry.state
        row: dict[str, Any] = {
            "local_time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "elapsed_s": f"{time.monotonic() - self._start_s:.6f}",
            "sample_source": sample_source,
            "phase": self._phase_name,
            "state": STATE_NAMES.get(state_id, state_id),
            "state_id": state_id,
            "armed": int(self.telemetry.armed),
            "altitude_setpoint_m": self.telemetry.altitude_setpoint_m,
            "altitude_m": self.telemetry.altitude_m,
            "vertical_speed_m_s": self.telemetry.vertical_speed_m_s,
            "roll_deg": self.telemetry.roll_deg,
            "pitch_deg": self.telemetry.pitch_deg,
            "yaw_deg": self.telemetry.yaw_deg,
            "joystick_throttle_pwm": self._requested_channels[THROTTLE],
            "output_throttle_pwm": None if output is None else output[THROTTLE],
            "output_correction_pwm": correction,
            "output_saturated": int(saturated),
            "output_roll_pwm": None if output is None else output[0],
            "output_pitch_pwm": None if output is None else output[1],
            "output_yaw_pwm": None if output is None else output[3],
        }
        row.update({name: self.parameter_values.get(name) for name in PARAMETERS})
        self._csv_writer.writerow(row)
        self._csv_file.flush()

    def _open_recording(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._csv_file = self.output_path.open("w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self.FIELDNAMES)
        self._csv_writer.writeheader()
        self._csv_file.flush()

    def _close_recording(self) -> None:
        if self._csv_file is not None:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None

    def _set_phase(self, message: str) -> None:
        self._phase_name = message
        self._phase(message)

    def _print_banner(self) -> None:
        print(SCENARIO_BANNER, flush=True)
        print(f"CSV output: {self.output_path.resolve()}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = build_base_parser()
    parser.description = SCENARIO_BANNER
    parser.set_defaults(alt_hold_duration=15.0, descent_throttle=1600)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/takeoff_diagnostic.csv"),
        help="CSV destination (default: logs/takeoff_diagnostic.csv)",
    )
    parser.add_argument(
        "--parameter-port",
        type=int,
        default=14551,
        help="bt-app MAVLink telemetry/parameter service UDP port",
    )
    parser.add_argument(
        "--parameter-timeout",
        type=float,
        default=8.0,
        help="seconds allowed to read all takeoff parameters",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0:
        raise SystemExit("--rate-hz must be greater than zero")
    if args.state_timeout <= 0 or args.landing_timeout <= 0:
        raise SystemExit("timeouts must be greater than zero")
    if args.parameter_timeout <= 0:
        raise SystemExit("--parameter-timeout must be greater than zero")
    if args.alt_hold_duration < 0:
        raise SystemExit("--alt-hold-duration cannot be negative")
    if args.touchdown_altitude < 0:
        raise SystemExit("--touchdown-altitude cannot be negative")
    if not 1000 <= args.descent_throttle <= 1650:
        raise SystemExit("--descent-throttle must be between 1000 and 1650")

    scenario = TakeoffDiagnosticScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.landing_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=args.alt_hold_duration,
        descent_throttle=args.descent_throttle,
        output_path=args.output,
        parameter_destination=(args.destination_host, args.parameter_port),
        parameter_timeout_s=args.parameter_timeout,
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

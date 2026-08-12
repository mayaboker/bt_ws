#!/usr/bin/env python3
"""Take off, run the guarded visual GLIDE intercept, and record diagnostics."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
import time
from typing import Sequence

from pymavlink import mavutil

from send_rc import (
    ALT_HOLD_ARMED,
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    ARM_IN_MANUAL,
    AUTO_TAKEOFF,
    AUTO_TAKEOFF_ARMED,
    NEUTRAL_DISARMED,
    RC_MAX,
    STATE_ALT_HOLD,
    STATE_GLIDE,
    STATE_IDLE,
    STATE_MANUAL,
    STATE_TAKEOFF,
    TRACKER_MODE,
    ScenarioError,
)
from send_rc_takeoff_diagnostic import (
    PARAMETERS as TAKEOFF_PARAMETERS,
    TakeoffDiagnosticScenario,
    build_base_parser,
)

GLIDE_PARAMETERS = (
    "GLIDE_PITCH_FF",
    "GLIDE_PITCH_MAX",
    "GLIDE_VX_KP",
    "GLIDE_VX_KI",
    "GLIDE_VY_KP",
    "GLIDE_VY_KI",
    "GLIDE_VY_OUT",
    "GLIDE_YAW_KP",
    "GLIDE_YAW_MAX",
    "GLIDE_YAW_DB",
    "GLIDE_YAW_SLEW",
    "GLIDE_CENTER_KY",
    "GLIDE_DEPTH_EMA",
)
REQUEST_TAKEOFF_ALT_M = 5.0

SCENARIO_BANNER = """\
==============================================================================
bt-app Automatic Takeoff / Visual GLIDE Intercept Scenario
==============================================================================
Simulates this joystick flight sequence:
  1. Arm in MANUAL and request automatic takeoff.
  2. In ALT_HOLD, select TRACKING with the glide switch released.
  3. Raise the glide switch to request ACQUIRE and wait for GLIDE/TRACK.
  4. Record TRACK and the frozen COMMIT command until return to ALT_HOLD.
  5. Switch to MANUAL, land, disarm, and verify IDLE.

The red-box tracker and visual result publisher must already be running, with
the target visible and centered. CSV data includes target distance, measured
attitude and velocity, complete controller RC output, and active controller
parameters. bt-app's structured log provides the internal glide phase.
=============================================================================="""


def tracking_glide_channels(*, switch_high: bool) -> tuple[int, ...]:
    """Select TRACKING while controlling the glide request switch."""
    channels = list(ALT_HOLD_ARMED)
    channels[TRACKER_MODE] = RC_MAX
    channels[AUTO_TAKEOFF] = RC_MAX if switch_high else 1000
    return tuple(channels)


TRACKING_GLIDE_RELEASED = tracking_glide_channels(switch_high=False)
GLIDE_REQUEST_ARMED = tracking_glide_channels(switch_high=True)


class GlideDiagnosticScenario(TakeoffDiagnosticScenario):
    PARAMETERS = (*TAKEOFF_PARAMETERS, *GLIDE_PARAMETERS)
    FIELDNAMES = (
        *TakeoffDiagnosticScenario.FIELDNAMES[:-len(TAKEOFF_PARAMETERS)],
        *PARAMETERS,
    )

    def __init__(self, **kwargs) -> None:
        self.acquisition_attempt_s = float(kwargs.pop("acquisition_attempt_s", 2.0))
        super().__init__(**kwargs)
        self._next_glide_console_log_s = 0.0
        self._original_takeoff_alt: float | int | None = None

    def _write_snapshot(self, sample_source: str = "test") -> None:
        if (
            sample_source == "GLOBAL_POSITION_INT"
            and self.telemetry.state == STATE_GLIDE
            and time.monotonic() >= self._next_glide_console_log_s
        ):
            self._next_glide_console_log_s = time.monotonic() + 0.5
            output = self.telemetry.output_channels
            output_throttle = None if output is None else output[2]
            baseline = self.parameter_values.get("HOV_BASELINE")
            correction = (
                None
                if output_throttle is None or baseline is None
                else output_throttle - baseline
            )
            setpoint = self.telemetry.vertical_speed_setpoint_m_s
            altitude = self.telemetry.altitude_m
            speed = self.telemetry.vertical_speed_m_s
            target_distance = self.telemetry.target_distance_m
            self._phase(
                "GLIDE "
                f"velocity_setpoint={'unknown' if setpoint is None else f'{setpoint:+.2f} m/s'} "
                f"altitude={'unknown' if altitude is None else f'{altitude:.2f} m'} "
                f"vertical_speed={'unknown' if speed is None else f'{speed:+.2f} m/s'} "
                f"target_distance={'unknown' if target_distance is None else f'{target_distance:.2f} m'} "
                f"throttle={'unknown' if output_throttle is None else output_throttle} "
                f"correction={'unknown' if correction is None else f'{correction:+g} PWM'}"
            )
        super()._write_snapshot(sample_source)

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
            self._original_takeoff_alt = self.parameter_values["TAKEOFF_ALT"]
            self._set_parameter("TAKEOFF_ALT", REQUEST_TAKEOFF_ALT_M)
            self._set_phase("Arming in MANUAL mode")
            self._wait_for_state(ARM_IN_MANUAL, STATE_MANUAL, self.state_timeout_s)
            self._set_phase("Requesting automatic takeoff from MANUAL")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_TAKEOFF,
                self.state_timeout_s,
            )
            self._airborne = True
            self._set_phase("Waiting for automatic takeoff to enter ALT_HOLD")
            self._wait_for_state(
                AUTO_TAKEOFF_ARMED,
                STATE_ALT_HOLD,
                self.landing_timeout_s,
            )
            self._set_phase(
                "Selecting TRACKING with GLIDE released; target must be visible"
            )
            self._send_for(TRACKING_GLIDE_RELEASED, 2.0)
            if self.telemetry.state != STATE_ALT_HOLD:
                raise ScenarioError(
                    "Vehicle left ALT_HOLD before GLIDE request; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            self._set_phase("Requesting ACQUIRE and waiting for GLIDE/TRACK")
            self._wait_for_glide_entry()
            self._set_phase("Recording TRACK/COMMIT until return to ALT_HOLD")
            self._wait_for(
                GLIDE_REQUEST_ARMED,
                lambda: self.telemetry.state == STATE_ALT_HOLD,
                self.landing_timeout_s,
                "GLIDE abort or COMMIT timeout return to ALT_HOLD",
            )
            self._set_phase("Switching to MANUAL for controlled landing")
            self._wait_for_state(
                self.manual_descent_channels,
                STATE_MANUAL,
                self.state_timeout_s,
            )
            self._land_and_disarm()
            self._completed = True
            self._set_phase(f"Scenario completed; CSV saved to {self.output_path}")
        finally:
            if self._original_takeoff_alt is not None and self.telemetry.armed:
                self._set_phase(
                    "Waiting for disarm before restoring TAKEOFF_ALT"
                )
                self._wait_for_disarm_without_rc()
            if self._original_takeoff_alt is not None and not self.telemetry.armed:
                self._restore_takeoff_alt()
            elif self._original_takeoff_alt is not None:
                self._phase(
                    "TAKEOFF_ALT not restored because the vehicle is still armed; "
                    f"restore it manually to {self._original_takeoff_alt:g}"
                )
            self._cleanup()
            self._close_recording()

    def _wait_for_glide_entry(self) -> None:
        """Retry the required low-to-high edge until visual entry succeeds.

        A request made before the first fresh tracker result is intentionally
        rejected by bt-app. Once bt-app reports ACQUIRE, the switch remains
        high until engagement or the overall timeout; an active acquisition
        must never be cancelled merely to create another request edge.
        """
        deadline = time.monotonic() + self.state_timeout_s
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            self._set_phase(f"GLIDE acquisition attempt {attempt}: switch released")
            self._send_for(TRACKING_GLIDE_RELEASED, 0.5)
            self._set_phase(f"GLIDE acquisition attempt {attempt}: switch raised")
            attempt_deadline = min(
                deadline, time.monotonic() + self.acquisition_attempt_s
            )
            while time.monotonic() < attempt_deadline:
                self._send_rc(GLIDE_REQUEST_ARMED)
                self._receive_pending()
                if self.telemetry.state == STATE_GLIDE:
                    return
                if self.telemetry.glide_phase_code == 1:
                    attempt_deadline = deadline
                if self.telemetry.state != STATE_ALT_HOLD:
                    raise ScenarioError(
                        "Vehicle left ALT_HOLD during acquisition; "
                        f"last telemetry: {self.telemetry.describe()}"
                    )
                time.sleep(self.period_s)
        raise ScenarioError(
            "Timed out waiting for GLIDE; verify TRACKING session, fresh red-box "
            f"detections, and centering. Last telemetry: {self.telemetry.describe()}"
        )

    def _read_takeoff_parameters(self) -> None:
        """Require takeoff parameters but treat GLIDE diagnostics as optional.

        A running/deployed bt-app can use the new controller while its MAVLink
        parameter registry still exposes an older schema. Missing GLIDE values
        reduce CSV detail but must not prevent the flight scenario.
        """
        self._set_phase("Reading required takeoff parameters")
        self.PARAMETERS = TAKEOFF_PARAMETERS
        try:
            super()._read_takeoff_parameters()
        finally:
            del self.PARAMETERS

        self._set_phase("Reading optional GLIDE diagnostic parameters")
        pending = set(GLIDE_PARAMETERS)
        deadline = time.monotonic() + min(2.0, self.parameter_timeout_s)
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
            self._phase(
                "Continuing without unavailable GLIDE parameter telemetry: "
                + ", ".join(sorted(pending))
            )
        available = [name for name in GLIDE_PARAMETERS if name in self.parameter_values]
        if available:
            self._phase(
                "Active GLIDE parameters: "
                + " ".join(
                    f"{name}={self.parameter_values[name]:g}" for name in available
                )
            )

    def _set_parameter(self, name: str, value: float) -> None:
        self.parameter_values.pop(name, None)
        deadline = time.monotonic() + self.parameter_timeout_s
        next_parameter_send_s = 0.0
        while time.monotonic() < deadline:
            now_s = time.monotonic()
            self._send_rc(NEUTRAL_DISARMED)
            if now_s >= next_parameter_send_s:
                message = self._encoder.param_set_encode(
                    APP_SYSTEM_ID,
                    APP_COMPONENT_ID,
                    name.encode("ascii"),
                    float(value),
                    mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
                )
                if self._socket is not None:
                    self._socket.sendto(
                        message.pack(self._encoder), self.parameter_destination
                    )
                next_parameter_send_s = now_s + 0.5
            self._receive_pending()
            received = self.parameter_values.get(name)
            if received is not None and math.isclose(
                float(received), value, rel_tol=1e-5, abs_tol=1e-5
            ):
                self._phase(f"Parameter {name}={received:g} verified")
                return
            time.sleep(min(0.01, self.period_s))
        raise ScenarioError(f"Timed out setting parameter {name}={value:g}")

    def _restore_takeoff_alt(self) -> None:
        original = self._original_takeoff_alt
        if original is None:
            return
        self._set_phase(f"Restoring TAKEOFF_ALT={original:g} after disarm")
        self._set_parameter("TAKEOFF_ALT", float(original))
        self._original_takeoff_alt = None

    def _wait_for_disarm_without_rc(self) -> None:
        deadline = time.monotonic() + self.landing_timeout_s
        while self.telemetry.armed and time.monotonic() < deadline:
            self._receive_pending()
            time.sleep(0.05)

    def _print_banner(self) -> None:
        print(SCENARIO_BANNER, flush=True)
        print(f"CSV output: {self.output_path.resolve()}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = build_base_parser()
    parser.description = SCENARIO_BANNER
    parser.set_defaults(landing_timeout=180.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/glide_diagnostic.csv"),
    )
    parser.add_argument("--parameter-port", type=int, default=14551)
    parser.add_argument("--parameter-timeout", type=float, default=10.0)
    parser.add_argument(
        "--acquisition-attempt",
        type=float,
        default=2.0,
        help="seconds to hold each GLIDE request high before retrying the edge",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rate_hz <= 0 or args.state_timeout <= 0 or args.landing_timeout <= 0:
        raise SystemExit("rate and timeouts must be positive")
    if args.parameter_timeout <= 0:
        raise SystemExit("--parameter-timeout must be positive")
    if args.acquisition_attempt <= 0:
        raise SystemExit("--acquisition-attempt must be positive")
    scenario = GlideDiagnosticScenario(
        destination=(args.destination_host, args.destination_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.landing_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=0.0,
        descent_throttle=1600,
        output_path=args.output,
        parameter_destination=(args.destination_host, args.parameter_port),
        parameter_timeout_s=args.parameter_timeout,
        acquisition_attempt_s=args.acquisition_attempt,
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

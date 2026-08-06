#!/usr/bin/env python3
"""Run the red-detector PRE_TRACKING/TRACKING scenario against SITL.

If PRE_TRACKING is not locked, the vehicle searches with one measured clockwise
yaw turn while ALT_HOLD owns throttle. A full turn without lock lands normally.
The operator presses Enter when the visually observed intercept occurs. Ctrl-C
or an unexpected airborne error stops RC output so bt-app's failsafe can recover.
"""

from __future__ import annotations

import argparse
import math
import select
import sys
import time
from typing import Any, Sequence

import msgpack
from pymavlink import mavutil
import zmq

from send_rc import (
    ALT_HOLD_ARMED,
    APP_COMPONENT_ID,
    APP_SYSTEM_ID,
    ARM_IN_MANUAL,
    AUTO_TAKEOFF_ARMED,
    ENABLER,
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
    THROTTLE,
    YAW,
    ScenarioError,
)
from send_rc_auto_yaw import YawTelemetry
from send_rc_manual_reentry import ManualReentryScenario


TRACKER_MODE = 8
TRACKER_DISABLED = RC_MIN
TRACKER_SELECTED = RC_MAX
STATE_TRACKING = 2
STATE_NAMES[STATE_TRACKING] = "TRACKING"
LOCK_FRESHNESS_S = 0.25
ENABLE_CONFIRM_GRACE_S = 1.25
ENABLE_CENTER_HYSTERESIS = 1.5
ANSI_BOLD_RED = "\033[1;31m"

POC_PARAMETERS = {
    "TAKEOFF_ALT": 4.0,
    "VIS_FWD_PITCH": -5.0,
    "VIS_KP_YAW": 15.0,
    "VIS_MAX_YAW": 15.0,
}


def tracker_channels(
    base: Sequence[int],
    *,
    selected: bool,
    enabler: bool = False,
) -> tuple[int, ...]:
    channels = list(base)
    if len(channels) <= TRACKER_MODE:
        channels.extend([RC_MIN] * (TRACKER_MODE + 1 - len(channels)))
    channels[ENABLER] = RC_MAX if enabler else RC_MIN
    channels[TRACKER_MODE] = TRACKER_SELECTED if selected else TRACKER_DISABLED
    return tuple(channels)


PRE_TRACKING = tracker_channels(ALT_HOLD_ARMED, selected=True)
TRACKING_ENABLE = tracker_channels(
    ALT_HOLD_ARMED,
    selected=True,
    enabler=True,
)
TRACKING_DISABLED = tracker_channels(ALT_HOLD_ARMED, selected=False)


class SearchError(ScenarioError):
    """Raised when the target search cannot be completed safely."""


class TrackingScenario(ManualReentryScenario):
    def __init__(
        self,
        *,
        parameter_destination: tuple[str, int],
        visual_endpoint: str,
        search_yaw_rc: int,
        search_timeout_s: float,
        lock_dwell_s: float,
        image_width_px: int,
        center_tolerance_px: int,
        alignment_yaw_kp: float,
        alignment_yaw_min: int,
        alignment_yaw_limit: int,
        alignment_timeout_s: float,
        vision_timeout_s: float,
        search_log_rate_hz: float,
        tracking_timeout_s: float,
        settle_duration_s: float,
        parameter_timeout_s: float,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.telemetry = YawTelemetry()
        self.parameter_destination = parameter_destination
        self.visual_endpoint = visual_endpoint
        self.search_yaw_rc = search_yaw_rc
        self.search_timeout_s = search_timeout_s
        self.lock_dwell_s = lock_dwell_s
        self.image_width_px = image_width_px
        self.center_tolerance_px = center_tolerance_px
        self.alignment_yaw_kp = alignment_yaw_kp
        self.alignment_yaw_min = alignment_yaw_min
        self.alignment_yaw_limit = alignment_yaw_limit
        self.alignment_timeout_s = alignment_timeout_s
        self.vision_timeout_s = vision_timeout_s
        self.search_log_period_s = 1.0 / search_log_rate_hz
        self.tracking_timeout_s = tracking_timeout_s
        self.settle_duration_s = settle_duration_s
        self.parameter_timeout_s = parameter_timeout_s
        self._zmq_context: zmq.Context | None = None
        self._visual_socket: zmq.Socket | None = None
        self._last_detection: dict[str, Any] | None = None
        self._last_detection_received_at = float("-inf")
        self._invalid_visual_frames = 0
        self._last_invalid_visual_warning_at = float("-inf")
        self._parameter_values: dict[str, float] = {}
        self._original_parameters: dict[str, float] = {}

    def run(self) -> None:
        self._open()
        self._open_visual_subscriber()
        try:
            self._phase("Waiting for bt-app telemetry and red-detection ZMQ data")
            self._wait_for(
                NEUTRAL_DISARMED,
                lambda: self.telemetry.state is not None,
                self.state_timeout_s,
                "application heartbeat",
            )
            self._configure_poc_parameters()

            self._phase("Arming in MANUAL mode")
            self._wait_for_state(ARM_IN_MANUAL, STATE_MANUAL, self.state_timeout_s)

            self._phase("Requesting automatic takeoff to 4.00 m")
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

            self._phase(
                f"Settling in ALT_HOLD for {self.settle_duration_s:.1f} seconds"
            )
            self._send_for(TRACKING_DISABLED, self.settle_duration_s)

            self._phase("Selecting TRACKING and starting PRE_TRACKING search")
            try:
                target_locked = self._search_and_enable_tracking()
            except SearchError as exc:
                if self.telemetry.state == STATE_ALT_HOLD and self.telemetry.armed:
                    self._land_and_disarm("SEARCH FAILED; safely landed")
                raise ScenarioError(str(exc)) from exc
            if not target_locked:
                self._land_and_disarm("NO TARGET FOUND; safely landed")
                return

            self._monitor_tracking()
            self._land_and_disarm("Tracking scenario completed successfully")
        finally:
            if self._original_parameters and self.telemetry.armed:
                self._phase(
                    "Waiting for failsafe disarm before restoring parameters"
                )
                self._wait_for_disarm_without_rc()
            if self._original_parameters and not self.telemetry.armed:
                self._restore_parameters()
            elif self._original_parameters:
                values = ", ".join(
                    f"{name}={value:g}"
                    for name, value in self._original_parameters.items()
                )
                self._phase(f"Parameters not restored; restore manually: {values}")
            self._close_visual_subscriber()
            self._cleanup()

    def _open_visual_subscriber(self) -> None:
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 1)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        socket.connect(self.visual_endpoint)
        self._zmq_context = context
        self._visual_socket = socket

    def _close_visual_subscriber(self) -> None:
        if self._visual_socket is not None:
            self._visual_socket.close(linger=0)
            self._visual_socket = None
        if self._zmq_context is not None:
            self._zmq_context.term()
            self._zmq_context = None

    def _receive_pending(self) -> None:
        if self._socket is not None:
            while True:
                try:
                    payload, _address = self._socket.recvfrom(4096)
                except BlockingIOError:
                    break
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
                        self._parameter_values[name] = float(message.param_value)
                    previous_state = self.telemetry.state
                    if self.telemetry.consume(message):
                        state_changed = self.telemetry.state != previous_state
                        if state_changed or message.get_type() != "ATTITUDE":
                            self._phase(
                                self.telemetry.describe(),
                                color="\033[1;36m" if state_changed else None,
                            )
        self._receive_visual_pending()

    def _receive_visual_pending(self) -> None:
        socket = self._visual_socket
        if socket is None:
            return
        while True:
            try:
                payload = socket.recv(flags=zmq.NOBLOCK)
            except zmq.Again:
                return
            try:
                data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
            except (ValueError, TypeError, msgpack.exceptions.UnpackException) as exc:
                self._record_invalid_visual_frame(str(exc))
                continue
            if not isinstance(data, dict):
                self._record_invalid_visual_frame("payload is not a map")
                continue
            if data.get("type") != "red-detection":
                continue
            required = ("frame_id", "found", "x", "y", "width", "height")
            if any(field not in data for field in required):
                self._record_invalid_visual_frame("red-detection fields are missing")
                continue
            if not isinstance(data["found"], bool) or not isinstance(
                data.get("locked", False), bool
            ):
                self._record_invalid_visual_frame("lock fields must be booleans")
                continue
            numeric_fields = (
                "frame_id",
                "x",
                "y",
                "width",
                "height",
                "lock_found_frames",
                "lock_missing_frames",
            )
            if any(
                field in data
                and (isinstance(data[field], bool) or not isinstance(data[field], int))
                for field in numeric_fields
            ):
                self._record_invalid_visual_frame("numeric fields must be integers")
                continue
            self._last_detection = data
            self._last_detection_received_at = time.monotonic()

    def _record_invalid_visual_frame(self, reason: str) -> None:
        self._invalid_visual_frames += 1
        now = time.monotonic()
        if now - self._last_invalid_visual_warning_at < 2.0:
            return
        self._last_invalid_visual_warning_at = now
        self._phase(
            "Ignoring invalid visual frame "
            f"count={self._invalid_visual_frames} reason={reason}"
        )

    def _fresh_detector_lock(self) -> bool:
        detection = self._last_detection
        return bool(
            detection
            and detection.get("found", False)
            and detection.get("locked", False)
            and time.monotonic() - self._last_detection_received_at
            <= LOCK_FRESHNESS_S
        )

    @staticmethod
    def _wrapped_yaw_delta(previous_deg: float, current_deg: float) -> float:
        return (current_deg - previous_deg + 180.0) % 360.0 - 180.0

    def _search_channels(self) -> tuple[int, ...]:
        channels = list(PRE_TRACKING)
        channels[YAW] = self.search_yaw_rc
        return tuple(channels)

    def _target_horizontal_error_px(self) -> float | None:
        detection = self._last_detection
        if not detection or not detection.get("found", False):
            return None
        target_center_x = float(detection["x"]) + float(detection["width"]) / 2.0
        return target_center_x - self.image_width_px / 2.0

    def _alignment_channels(self, error_px: float) -> tuple[int, ...]:
        correction = round(error_px * self.alignment_yaw_kp)
        if abs(error_px) > self.center_tolerance_px:
            correction_sign = 1 if error_px > 0 else -1
            correction = correction_sign * max(
                self.alignment_yaw_min,
                abs(correction),
            )
        correction = max(
            -self.alignment_yaw_limit,
            min(self.alignment_yaw_limit, correction),
        )
        channels = list(PRE_TRACKING)
        channels[YAW] = RC_MID + correction
        return tuple(channels)

    def _search_and_enable_tracking(self) -> bool:
        self._phase(
            f"Holding centered PRE_TRACKING for {self.lock_dwell_s:.1f} seconds"
        )
        search_started_at = time.monotonic()
        attitude_samples_at_start = self.telemetry.attitude_samples
        self._send_for(PRE_TRACKING, self.lock_dwell_s)
        self._ensure_search_inputs(search_started_at, attitude_samples_at_start)
        if self._fresh_detector_lock():
            return self._settle_and_enable_lock()

        previous_yaw = self.telemetry.yaw_deg
        if previous_yaw is None:
            raise SearchError("No attitude yaw telemetry available for measured search")
        previous_attitude_samples = self.telemetry.attitude_samples
        last_attitude_received_at = time.monotonic()
        accumulated_yaw = 0.0
        search_channels = self._search_channels()
        deadline = search_started_at + self.search_timeout_s
        next_send = 0.0
        next_log = 0.0
        self._phase(
            "No lock; starting measured clockwise search "
            f"yaw_rc={self.search_yaw_rc} limit=360 deg"
        )

        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(search_channels)
                next_send = now + self.period_s
            self._receive_pending()
            self._check_search_health(now)

            if self.telemetry.attitude_samples != previous_attitude_samples:
                previous_attitude_samples = self.telemetry.attitude_samples
                last_attitude_received_at = now
                current_yaw = self.telemetry.yaw_deg
                if current_yaw is not None:
                    accumulated_yaw += self._wrapped_yaw_delta(
                        previous_yaw,
                        current_yaw,
                    )
                    previous_yaw = current_yaw
            elif now - last_attitude_received_at > self.vision_timeout_s:
                raise SearchError(
                    f"No fresh attitude telemetry for {self.vision_timeout_s:.1f}s"
                )

            if now >= next_log:
                self._log_search_progress(accumulated_yaw)
                next_log = now + self.search_log_period_s

            if self._fresh_detector_lock():
                if self._settle_and_enable_lock():
                    return True
                previous_yaw = self.telemetry.yaw_deg or previous_yaw
                previous_attitude_samples = self.telemetry.attitude_samples
                last_attitude_received_at = time.monotonic()

            if abs(accumulated_yaw) >= 360.0:
                self._phase(
                    "Measured full search turn complete; centering for final "
                    f"{self.lock_dwell_s:.1f} second lock grace"
                )
                self._send_for(PRE_TRACKING, self.lock_dwell_s)
                self._check_search_health(time.monotonic())
                if self._fresh_detector_lock() and self._settle_and_enable_lock():
                    return True
                return False
            time.sleep(min(0.005, self.period_s))

        raise SearchError(
            f"Search timed out after {self.search_timeout_s:.1f}s before a "
            f"measured full turn; accumulated={accumulated_yaw:+.1f} deg"
        )

    def _ensure_search_inputs(
        self,
        started_at: float,
        attitude_samples_at_start: int,
    ) -> None:
        deadline = started_at + self.vision_timeout_s
        while time.monotonic() < deadline:
            self._receive_pending()
            if (
                self._last_detection_received_at >= started_at
                and (
                    self._fresh_detector_lock()
                    or self.telemetry.attitude_samples > attitude_samples_at_start
                )
            ):
                return
            self._send_rc(PRE_TRACKING)
            time.sleep(self.period_s)
        if self._last_detection_received_at < started_at:
            raise SearchError("No red-detection telemetry after PRE_TRACKING start")
        if (
            self.telemetry.attitude_samples <= attitude_samples_at_start
            and not self._fresh_detector_lock()
        ):
            raise SearchError("No fresh attitude yaw telemetry for measured search")

    def _check_search_health(self, now: float) -> None:
        if self.telemetry.state != STATE_ALT_HOLD:
            raise SearchError(
                "Vehicle left ALT_HOLD during target search; "
                f"last telemetry: {self.telemetry.describe()}"
            )
        if now - self._last_detection_received_at > self.vision_timeout_s:
            raise SearchError(
                f"No valid red-detection telemetry for {self.vision_timeout_s:.1f}s"
            )

    def _settle_and_enable_lock(self) -> bool:
        detection = self._last_detection or {}
        self._phase(
            "Detector locked; aligning target with camera center "
            f"frame={detection.get('frame_id')} "
            f"bbox=({detection.get('x')}, {detection.get('y')}, "
            f"{detection.get('width')}, {detection.get('height')})"
        )
        deadline = time.monotonic() + self.alignment_timeout_s
        centered_since: float | None = None
        next_log = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            self._receive_pending()
            self._check_search_health(now)
            error_px = self._target_horizontal_error_px()
            if error_px is None:
                self._phase("Detector target lost while aligning; resuming search")
                return False

            centered = abs(error_px) <= self.center_tolerance_px
            locked = self._fresh_detector_lock()
            if centered and locked:
                if centered_since is None:
                    centered_since = now
                channels = PRE_TRACKING
            else:
                centered_since = None
                channels = self._alignment_channels(error_px)
            self._send_rc(channels)

            if now >= next_log:
                self._phase(
                    "Target alignment "
                    f"error_x={error_px:+.1f}px yaw_rc={channels[YAW]} "
                    f"centered={centered} locked={locked}"
                )
                next_log = now + self.search_log_period_s

            if (
                centered_since is not None
                and now - centered_since >= self.lock_dwell_s
            ):
                self._phase(
                    "Target centered with stable lock "
                    f"for {self.lock_dwell_s:.1f}s"
                )
                break
            time.sleep(min(0.005, self.period_s))
        else:
            self._phase("Target alignment timed out; resuming search")
            return False

        self._phase(
            "Pulsing enabler and requesting TRACKING",
            color=ANSI_BOLD_RED,
        )
        self._send_for(PRE_TRACKING, 0.1)
        self._send_for(TRACKING_ENABLE, 0.5)
        confirmation_started_at = time.monotonic()
        deadline = confirmation_started_at + min(3.0, self.state_timeout_s)
        while time.monotonic() < deadline:
            self._send_rc(PRE_TRACKING)
            self._receive_pending()
            if self.telemetry.state == STATE_TRACKING:
                return True
            if self.telemetry.state != STATE_ALT_HOLD:
                raise SearchError(
                    "Vehicle entered unexpected state after tracker enable; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            error_px = self._target_horizontal_error_px()
            # The state heartbeat is slower than RC and detector updates. Give
            # it time to acknowledge TRACKING, and use hysteresis so a target
            # at 60/61 px does not chatter across the acquisition boundary.
            if time.monotonic() - confirmation_started_at < ENABLE_CONFIRM_GRACE_S:
                time.sleep(self.period_s)
                continue
            if not self._fresh_detector_lock():
                self._phase(
                    "Tracker enable was not accepted: detector lock was lost "
                    f"found={bool((self._last_detection or {}).get('found', False))} "
                    f"locked={bool((self._last_detection or {}).get('locked', False))}"
                )
                return False
            release_tolerance = (
                self.center_tolerance_px * ENABLE_CENTER_HYSTERESIS
            )
            if error_px is None or abs(error_px) > release_tolerance:
                self._phase(
                    "Tracker enable was not accepted: target left centered region "
                    f"error_x={error_px} release_tolerance={release_tolerance:.1f}px"
                )
                return False
            time.sleep(self.period_s)
        detection = self._last_detection or {}
        raise SearchError(
            "bt-app did not acknowledge TRACKING after a fresh centered lock; "
            f"frame={detection.get('frame_id')} "
            f"found={detection.get('found')} locked={detection.get('locked')} "
            f"error_x={self._target_horizontal_error_px()}"
        )

    def _log_search_progress(self, accumulated_yaw: float) -> None:
        detection = self._last_detection or {}
        self._phase(
            f"Search yaw_rc={self.search_yaw_rc} "
            f"progress={accumulated_yaw:+.1f}/360.0 deg "
            f"heading={self.telemetry.yaw_deg} "
            f"found={bool(detection.get('found', False))} "
            f"locked={bool(detection.get('locked', False))} "
            f"lock_frames=({detection.get('lock_found_frames', 0)},"
            f"{detection.get('lock_missing_frames', 0)}) "
            f"bbox=({detection.get('x', 0)}, {detection.get('y', 0)}, "
            f"{detection.get('width', 0)}, {detection.get('height', 0)})"
        )

    def _land_and_disarm(self, completion_message: str) -> None:
        self._phase("Disabling tracker selector and requesting ALT_HOLD")
        self._wait_for_state(
            TRACKING_DISABLED,
            STATE_ALT_HOLD,
            self.state_timeout_s,
        )
        self._send_for(TRACKING_DISABLED, self.settle_duration_s)
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
            lambda: self.telemetry.state == STATE_IDLE and not self.telemetry.armed,
            self.state_timeout_s,
            "IDLE with armed flag cleared",
        )
        self._send_for(MANUAL_DISARMED, 0.5)
        self._restore_parameters()
        self._completed = True
        self._phase(completion_message)

    def _monitor_tracking(self) -> None:
        self._phase(
            "TRACKING active; press Enter on visual collision "
            f"(hard timeout {self.tracking_timeout_s:.1f} s)"
        )
        deadline = time.monotonic() + self.tracking_timeout_s
        next_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                self._send_rc(PRE_TRACKING)
                next_send = now + self.period_s
            self._receive_pending()
            if self.telemetry.state == STATE_ALT_HOLD:
                self._phase("TRACKING ended because detector lock was lost")
                return
            if self.telemetry.state != STATE_TRACKING:
                raise ScenarioError(
                    "Vehicle left TRACKING unexpectedly; "
                    f"last telemetry: {self.telemetry.describe()}"
                )
            if self._enter_pressed():
                self._phase("Operator reported visual collision")
                return
            time.sleep(min(0.005, self.period_s))
        self._phase("TRACKING hard timeout reached")

    @staticmethod
    def _enter_pressed() -> bool:
        if not sys.stdin.isatty():
            return False
        ready, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not ready:
            return False
        sys.stdin.readline()
        return True

    def _configure_poc_parameters(self) -> None:
        for name, value in POC_PARAMETERS.items():
            original = self._read_parameter(name)
            self._original_parameters[name] = original
            self._set_parameter(name, value)

    def _restore_parameters(self) -> None:
        if not self._original_parameters:
            return
        self._phase("Restoring original tracking parameters")
        pending = dict(self._original_parameters)
        for name, value in pending.items():
            self._set_parameter(name, value)
            self._original_parameters.pop(name, None)

    def _read_parameter(self, name: str) -> float:
        self._parameter_values.pop(name, None)
        deadline = time.monotonic() + self.parameter_timeout_s
        next_parameter_send = 0.0
        next_rc_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_rc_send:
                # Parameter transactions can take several seconds. Keep the
                # joystick link alive so bt-app does not enter its failsafe
                # while the vehicle is still safely disarmed on the ground.
                self._send_rc(NEUTRAL_DISARMED)
                next_rc_send = now + self.period_s
            if now >= next_parameter_send:
                message = self._encoder.param_request_read_encode(
                    APP_SYSTEM_ID,
                    APP_COMPONENT_ID,
                    name.encode("ascii"),
                    -1,
                )
                self._socket.sendto(
                    message.pack(self._encoder), self.parameter_destination
                )
                next_parameter_send = now + 0.5
            self._receive_pending()
            if name in self._parameter_values:
                return self._parameter_values[name]
            time.sleep(0.01)
        raise ScenarioError(f"Timed out reading parameter {name}")

    def _set_parameter(self, name: str, value: float) -> None:
        self._parameter_values.pop(name, None)
        deadline = time.monotonic() + self.parameter_timeout_s
        next_parameter_send = 0.0
        next_rc_send = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_rc_send:
                self._send_rc(NEUTRAL_DISARMED)
                next_rc_send = now + self.period_s
            if now >= next_parameter_send:
                message = self._encoder.param_set_encode(
                    APP_SYSTEM_ID,
                    APP_COMPONENT_ID,
                    name.encode("ascii"),
                    float(value),
                    mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
                )
                self._socket.sendto(
                    message.pack(self._encoder), self.parameter_destination
                )
                next_parameter_send = now + 0.5
            self._receive_pending()
            received = self._parameter_values.get(name)
            if received is not None and math.isclose(
                received,
                value,
                rel_tol=1e-5,
                abs_tol=1e-5,
            ):
                self._phase(f"Parameter {name}={received:g} verified")
                return
            time.sleep(0.01)
        raise ScenarioError(f"Timed out setting parameter {name}={value:g}")

    def _wait_for_disarm_without_rc(self) -> None:
        deadline = time.monotonic() + self.landing_timeout_s
        while self.telemetry.armed and time.monotonic() < deadline:
            self._receive_pending()
            time.sleep(0.05)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination-host", default="127.0.0.1")
    parser.add_argument("--destination-port", type=int, default=14560)
    parser.add_argument(
        "--parameter-port",
        type=int,
        default=14551,
        help="bt-app MAVLink telemetry/parameter service UDP port",
    )
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=14550)
    parser.add_argument("--visual-endpoint", default="tcp://127.0.0.1:5556")
    parser.add_argument("--rate-hz", type=float, default=50.0)
    parser.add_argument("--state-timeout", type=float, default=20.0)
    parser.add_argument("--flight-timeout", type=float, default=120.0)
    parser.add_argument(
        "--search-yaw-rc",
        type=int,
        default=1750,
        help="clockwise PRE_TRACKING yaw PWM",
    )
    parser.add_argument(
        "--search-timeout",
        type=float,
        default=240.0,
        help="maximum seconds allowed to measure the full search turn",
    )
    parser.add_argument(
        "--lock-dwell",
        type=float,
        default=1.5,
        help="continuous centered-lock seconds required before enabling tracking",
    )
    parser.add_argument("--image-width", type=int, default=640)
    parser.add_argument("--center-tolerance", type=int, default=60)
    parser.add_argument(
        "--alignment-yaw-kp",
        type=float,
        default=0.6,
        help="yaw RC correction per horizontal pixel of target error",
    )
    parser.add_argument(
        "--alignment-yaw-limit",
        type=int,
        default=175,
        help="maximum RC offset from 1500 while centering the target",
    )
    parser.add_argument(
        "--alignment-yaw-min",
        type=int,
        default=120,
        help="minimum RC offset outside the center window to overcome yaw deadband",
    )
    parser.add_argument("--alignment-timeout", type=float, default=60.0)
    parser.add_argument(
        "--vision-timeout",
        type=float,
        default=1.0,
        help="maximum age of vision or attitude telemetry during search",
    )
    parser.add_argument(
        "--search-log-rate",
        type=float,
        default=2.0,
        help="search progress messages per second",
    )
    parser.add_argument("--tracking-timeout", type=float, default=20.0)
    parser.add_argument("--settle-duration", type=float, default=2.0)
    parser.add_argument("--parameter-timeout", type=float, default=5.0)
    parser.add_argument("--descent-rate", type=float, default=0.5)
    parser.add_argument("--descent-velocity-kp", type=float, default=50.0)
    parser.add_argument("--descent-min-throttle", type=int, default=1500)
    parser.add_argument("--descent-hover-throttle", type=int, default=1660)
    parser.add_argument("--descent-max-throttle", type=int, default=1800)
    parser.add_argument("--touchdown-altitude", type=float, default=0.15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    positive = (
        args.rate_hz,
        args.state_timeout,
        args.flight_timeout,
        args.search_timeout,
        args.alignment_yaw_kp,
        args.alignment_timeout,
        args.vision_timeout,
        args.search_log_rate,
        args.tracking_timeout,
        args.parameter_timeout,
        args.descent_rate,
        args.descent_velocity_kp,
    )
    if any(value <= 0 for value in positive):
        raise SystemExit("rates, gains, and timeouts must be greater than zero")
    if args.settle_duration < 0 or args.lock_dwell < 0:
        raise SystemExit("settle and lock dwell durations cannot be negative")
    if args.touchdown_altitude < 0:
        raise SystemExit("touchdown altitude cannot be negative")
    if args.image_width <= 0 or args.center_tolerance < 0:
        raise SystemExit("image width must be positive and center tolerance non-negative")
    if not 1 <= args.alignment_yaw_min <= args.alignment_yaw_limit <= 499:
        raise SystemExit("--alignment-yaw-limit must be between 1 and 499")
    if not 1500 < args.search_yaw_rc <= RC_MAX:
        raise SystemExit("--search-yaw-rc must be between 1501 and 2000")
    if not (
        RC_MIN
        <= args.descent_min_throttle
        < args.descent_hover_throttle
        < args.descent_max_throttle
        <= RC_MAX
    ):
        raise SystemExit("invalid descent throttle range")

    scenario = TrackingScenario(
        destination=(args.destination_host, args.destination_port),
        parameter_destination=(args.destination_host, args.parameter_port),
        listen=(args.listen_host, args.listen_port),
        rate_hz=args.rate_hz,
        state_timeout_s=args.state_timeout,
        landing_timeout_s=args.flight_timeout,
        touchdown_altitude_m=args.touchdown_altitude,
        alt_hold_duration_s=args.settle_duration,
        descent_throttle=args.descent_min_throttle,
        target_altitude_m=4.0,
        first_alt_hold_duration_s=0.0,
        manual_hold_duration_s=0.0,
        second_alt_hold_duration_s=0.0,
        descent_rate_m_s=args.descent_rate,
        descent_velocity_kp=args.descent_velocity_kp,
        descent_min_throttle=args.descent_min_throttle,
        descent_hover_throttle=args.descent_hover_throttle,
        descent_max_throttle=args.descent_max_throttle,
        visual_endpoint=args.visual_endpoint,
        search_yaw_rc=args.search_yaw_rc,
        search_timeout_s=args.search_timeout,
        lock_dwell_s=args.lock_dwell,
        image_width_px=args.image_width,
        center_tolerance_px=args.center_tolerance,
        alignment_yaw_kp=args.alignment_yaw_kp,
        alignment_yaw_min=args.alignment_yaw_min,
        alignment_yaw_limit=args.alignment_yaw_limit,
        alignment_timeout_s=args.alignment_timeout,
        vision_timeout_s=args.vision_timeout,
        search_log_rate_hz=args.search_log_rate,
        tracking_timeout_s=args.tracking_timeout,
        settle_duration_s=args.settle_duration,
        parameter_timeout_s=args.parameter_timeout,
    )
    try:
        scenario.run()
    except KeyboardInterrupt:
        print("Interrupted; RC output stopped", file=sys.stderr)
        return 130
    except ScenarioError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

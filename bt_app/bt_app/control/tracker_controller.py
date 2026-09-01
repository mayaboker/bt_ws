"""Optical time-to-contact controller for the TRACK flight state."""

from __future__ import annotations

import csv
import math
import threading
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from loguru import logger as log

from bt_app.common import NO_RC_CHANNELS
from bt_app.control.rc_mapper import BetaflightRcMapper, clamp
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey
from bt_app.services import TrackerObservation


DEFAULT_TRACKER_CSV_PATH = Path("logs/tracker_controller.csv")
_VERTICAL_SPEED_TIMEOUT_S = 0.30
_VERTICAL_ACCEL_LIMIT_M_S2 = 5.0


class TrackerPhase(StrEnum):
    ALIGN = "align"
    TRACKING = "tracking"
    TERMINAL = "terminal"  # Retained for API compatibility; TTC uses COMMIT directly.
    COMMIT = "commit"


@dataclass(frozen=True, slots=True)
class TrackerConfig:
    pitch_initial_deg: float
    pitch_minimum_deg: float
    pitch_slew_deg_s: float
    pitch_recovery_slew_deg_s: float
    inverse_ttc_kp: float
    scale_alpha: float
    scale_beta: float
    inverse_ttc_max_hz: float
    logged_ttc_max_s: float
    lock_frames: int
    lock_history_s: float
    target_timeout_s: float
    scale_jump_fraction: float
    target_height_m: float
    nominal_vertical_speed_m_s: float
    vertical_speed_min_m_s: float
    vertical_speed_max_m_s: float
    minimum_target_ttc_s: float
    vertical_alignment_kp: float
    vertical_alignment_max_m_s: float
    near_field_alignment_max_m_s: float
    vertical_velocity_kp: float
    vertical_velocity_ki: float
    vertical_velocity_kd: float
    vertical_accel_filter_alpha: float
    vertical_integral_max_rc: float
    vertical_accel_limit_m_s2: float
    throttle_max_correction_rc: float
    commit_fill_fraction: float
    clipped_commit_fill_fraction: float
    commit_alignment: float
    commit_frames: int
    alignment_pitch_deg: float
    horizontal_alignment_threshold: float
    alignment_frames: int
    commit_ttc_s: float
    commit_duration_s: float
    yaw_kp: float
    yaw_max_dps: float
    yaw_slew_dps2: float
    yaw_sign: int
    deadband: float
    angle_limit_deg: float
    hover_baseline_rc: float
    yaw_stick_rate_dps: float
    yaw_center_sensitivity_dps: float
    yaw_rate_expo: float
    camera_width_px: int
    camera_height_px: int
    camera_cx_px: float
    camera_cy_px: float

    @classmethod
    def from_parameters(cls, parameters: Parameters) -> "TrackerConfig":
        return cls(
            pitch_initial_deg=parameters.get(ParameterKey.TTC_PIT_INIT),
            pitch_minimum_deg=parameters.get(ParameterKey.TTC_PIT_MIN),
            pitch_slew_deg_s=parameters.get(ParameterKey.TTC_PIT_SLEW),
            pitch_recovery_slew_deg_s=parameters.get(ParameterKey.TTC_PIT_REC),
            inverse_ttc_kp=parameters.get(ParameterKey.TTC_INV_KP),
            scale_alpha=parameters.get(ParameterKey.TTC_SCALE_A),
            scale_beta=parameters.get(ParameterKey.TTC_SCALE_B),
            inverse_ttc_max_hz=parameters.get(ParameterKey.TTC_INV_MAX),
            logged_ttc_max_s=parameters.get(ParameterKey.TTC_LOG_MAX),
            lock_frames=parameters.get(ParameterKey.TTC_LOCK_FR),
            lock_history_s=parameters.get(ParameterKey.TTC_LOCK_S),
            target_timeout_s=parameters.get(ParameterKey.TTC_TIMEOUT),
            scale_jump_fraction=parameters.get(ParameterKey.TTC_SCALE_JMP),
            target_height_m=parameters.get(ParameterKey.TGT_HEIGHT_M),
            nominal_vertical_speed_m_s=parameters.get(ParameterKey.TTC_VY_NOM),
            vertical_speed_min_m_s=parameters.get(ParameterKey.TTC_VY_MIN),
            vertical_speed_max_m_s=parameters.get(ParameterKey.TTC_VY_MAX),
            minimum_target_ttc_s=parameters.get(ParameterKey.TTC_MIN_S),
            vertical_alignment_kp=parameters.get(ParameterKey.TTC_DY_KP),
            vertical_alignment_max_m_s=parameters.get(ParameterKey.TTC_DY_VMAX),
            near_field_alignment_max_m_s=parameters.get(ParameterKey.TTC_DY_NEAR),
            vertical_velocity_kp=parameters.get(ParameterKey.TTC_VY_KP),
            vertical_velocity_ki=parameters.get(ParameterKey.TTC_VY_KI),
            vertical_velocity_kd=parameters.get(ParameterKey.TTC_VY_KD),
            vertical_accel_filter_alpha=parameters.get(ParameterKey.TTC_AZ_ALPHA),
            vertical_integral_max_rc=parameters.get(ParameterKey.TTC_VY_I_MAX),
            vertical_accel_limit_m_s2=parameters.get(ParameterKey.TRK_VZ_ACCEL),
            throttle_max_correction_rc=parameters.get(ParameterKey.TTC_THR_MAX),
            commit_fill_fraction=parameters.get(ParameterKey.TTC_FILL),
            clipped_commit_fill_fraction=parameters.get(ParameterKey.TTC_CLIP_FILL),
            commit_alignment=parameters.get(ParameterKey.TTC_ALIGN),
            commit_frames=parameters.get(ParameterKey.TTC_COMMIT_FR),
            alignment_pitch_deg=parameters.get(ParameterKey.TTC_ALN_PIT),
            horizontal_alignment_threshold=parameters.get(ParameterKey.TTC_ALN_XY),
            alignment_frames=parameters.get(ParameterKey.TTC_ALN_FR),
            commit_ttc_s=parameters.get(ParameterKey.TTC_MIN_S),
            commit_duration_s=parameters.get(ParameterKey.TRK_COMMIT_S),
            yaw_kp=parameters.get(ParameterKey.TRK_YAW_KP),
            yaw_max_dps=parameters.get(ParameterKey.TRK_YAW_MAX),
            yaw_slew_dps2=parameters.get(ParameterKey.TRK_YAW_SLEW),
            yaw_sign=parameters.get(ParameterKey.TRK_YAW_SIGN),
            deadband=parameters.get(ParameterKey.TRK_DEADBAND),
            angle_limit_deg=parameters.get(ParameterKey.BF_ANGLE_LIMIT),
            hover_baseline_rc=parameters.get(ParameterKey.HOV_BASELINE),
            yaw_stick_rate_dps=parameters.get(ParameterKey.BF_YAW_RATE),
            yaw_center_sensitivity_dps=parameters.get(ParameterKey.BF_YAW_CENTER),
            yaw_rate_expo=parameters.get(ParameterKey.BF_YAW_EXPO),
            camera_width_px=parameters.get(ParameterKey.CAM_WIDTH_PX),
            camera_height_px=parameters.get(ParameterKey.CAM_HEIGHT_PX),
            camera_cx_px=parameters.get(ParameterKey.CAM_CX_PX),
            camera_cy_px=parameters.get(ParameterKey.CAM_CY_PX),
        )

    def __post_init__(self) -> None:
        if not self.pitch_minimum_deg <= self.pitch_initial_deg <= 0.0:
            raise ValueError("initial TTC pitch must be inside pitch limits")
        if abs(self.pitch_minimum_deg) > self.angle_limit_deg:
            raise ValueError("minimum TTC pitch exceeds Betaflight angle limit")
        if (
            self.yaw_center_sensitivity_dps <= 0.0
            or self.yaw_stick_rate_dps < self.yaw_center_sensitivity_dps
            or not 0.0 <= self.yaw_rate_expo <= 1.0
        ):
            raise ValueError("invalid Betaflight Actual-rates yaw configuration")
        if self.yaw_sign not in (-1, 1):
            raise ValueError("tracker yaw sign must be -1 or 1")
        if (
            self.pitch_slew_deg_s <= 0.0
            or self.pitch_recovery_slew_deg_s <= 0.0
            or self.yaw_slew_dps2 <= 0.0
            or self.nominal_vertical_speed_m_s <= 0.0
            or self.vertical_accel_limit_m_s2 <= 0.0
        ):
            raise ValueError("TTC slew, yaw slew, speed, and acceleration must be positive")
        if not 0.0 <= self.scale_alpha <= 1.0 or not 0.0 <= self.scale_beta <= 1.0:
            raise ValueError("TTC alpha-beta gains must be in [0, 1]")
        if self.vertical_speed_min_m_s >= 0.0 or self.vertical_speed_max_m_s < 0.0:
            raise ValueError("TTC vertical limits must include descent and hover")
        if (
            self.vertical_alignment_max_m_s < 0.0
            or self.near_field_alignment_max_m_s < self.vertical_alignment_max_m_s
            or self.vertical_velocity_ki < 0.0
            or self.vertical_integral_max_rc < 0.0
        ):
            raise ValueError(
                "TTC vertical alignment limits must be ordered and integral limits nonnegative"
            )
        if self.vertical_velocity_kd < 0.0:
            raise ValueError("TTC vertical acceleration gain must be nonnegative")
        if not 0.0 <= self.vertical_accel_filter_alpha <= 1.0:
            raise ValueError("TTC acceleration filter alpha must be in [0, 1]")
        if self.lock_frames < 2 or self.commit_frames < 1:
            raise ValueError("TTC acquisition and commit frame counts are invalid")
        if (
            self.alignment_frames < 1
            or not 0.0 < self.horizontal_alignment_threshold <= 1.0
        ):
            raise ValueError("TTC alignment acquisition settings are invalid")
        if not self.pitch_minimum_deg <= self.alignment_pitch_deg <= 0.0:
            raise ValueError("TTC alignment pitch must be inside pitch limits")
        if not 0.0 < self.commit_fill_fraction <= 1.0:
            raise ValueError("TTC commit fill must be in (0, 1]")
        if not self.commit_fill_fraction <= self.clipped_commit_fill_fraction <= 1.0:
            raise ValueError("clipped commit fill must be at least TTC commit fill")


@dataclass(frozen=True, slots=True)
class ScaleUpdate:
    accepted: bool
    new_frame: bool
    scale_px: float | None
    log_scale: float | None
    innovation: float | None
    reason: str | None = None


class OpticalTtcFilter:
    """Alpha-beta estimate of logarithmic bbox scale and expansion rate."""

    def __init__(self) -> None:
        self.log_scale: float | None = None
        self.rate_hz = 0.0
        self.time_s: float | None = None
        self.frame_id: int | None = None
        self.tracker_id: int | None = None

    def reset(self) -> None:
        self.log_scale = None
        self.rate_hz = 0.0
        self.time_s = None
        self.frame_id = None
        self.tracker_id = None

    def update(
        self,
        observation: TrackerObservation,
        config: TrackerConfig,
    ) -> ScaleUpdate:
        result = observation.result
        if self.tracker_id is not None and result.tracker_id != self.tracker_id:
            self.reset()
        if self.frame_id is not None and result.frame_id <= self.frame_id:
            return ScaleUpdate(False, False, None, None, None, "duplicate frame")
        self.frame_id = result.frame_id
        self.tracker_id = result.tracker_id
        if not result.locked:
            return ScaleUpdate(False, True, None, None, None, "tracker unlocked")
        if result.bbox_width <= 0 or result.bbox_height <= 0:
            return ScaleUpdate(False, True, None, None, None, "invalid bbox size")
        if (
            result.bbox_x <= 0
            or result.bbox_y <= 0
            or result.bbox_x + result.bbox_width >= config.camera_width_px
            or result.bbox_y + result.bbox_height >= config.camera_height_px
        ):
            return ScaleUpdate(False, True, None, None, None, "bbox clipped")
        scale = math.sqrt(result.bbox_width * result.bbox_height)
        measured_log = math.log(scale)
        if self.log_scale is None or self.time_s is None:
            self.log_scale = measured_log
            self.rate_hz = 0.0
            self.time_s = observation.received_at_s
            return ScaleUpdate(True, True, scale, measured_log, 0.0)
        dt_s = observation.received_at_s - self.time_s
        if dt_s <= 0.0:
            return ScaleUpdate(False, True, scale, measured_log, None, "timestamp order")
        predicted = self.log_scale + self.rate_hz * dt_s
        innovation = measured_log - predicted
        if abs(innovation) > math.log1p(config.scale_jump_fraction):
            return ScaleUpdate(
                False,
                True,
                scale,
                measured_log,
                innovation,
                "scale innovation",
            )
        self.log_scale = predicted + config.scale_alpha * innovation
        self.rate_hz += config.scale_beta * innovation / dt_s
        self.time_s = observation.received_at_s
        return ScaleUpdate(True, True, scale, self.log_scale, innovation)


@dataclass(frozen=True, slots=True)
class TrackerControlResult:
    channels: tuple[int, ...]
    phase: TrackerPhase
    error_x: float | None
    error_y: float | None
    pitch_command_deg: float
    yaw_rate_dps: float
    drone_vertical_speed_m_s: float | None
    drone_vertical_speed_age_s: float | None
    drone_vertical_speed_valid: bool
    vertical_speed_requested_m_s: float | None
    vertical_speed_limit_m_s: float | None
    vertical_speed_target_m_s: float | None
    vertical_speed_setpoint_m_s: float | None
    vertical_speed_error_m_s: float | None
    throttle_visual_correction_rc: float
    throttle_damping_correction_rc: float
    throttle_correction_rc: float
    terminal_ready: bool
    terminal_block_reason: str | None
    terminal_ready_elapsed_s: float | None
    terminal_elapsed_s: float | None
    valid: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LoopDiagnostics:
    new_camera_frame: bool = False
    scale_px: float | None = None
    log_scale: float | None = None
    scale_innovation: float | None = None
    scale_reason: str | None = None
    inverse_ttc_measured_hz: float = 0.0
    measured_ttc_s: float = 0.0
    target_ttc_s: float = 0.0
    inverse_ttc_target_hz: float = 0.0
    pitch_raw_deg: float = 0.0
    vertical_distance_m: float = 0.0
    vertical_nominal_m_s: float = 0.0
    vertical_alignment_m_s: float = 0.0
    raw_vertical_accel_m_s2: float = 0.0
    filtered_vertical_accel_m_s2: float = 0.0
    throttle_d_rc: float = 0.0
    bbox_fill: float = 0.0
    yaw_rate_target_dps: float = 0.0
    effective_ttc_s: float = 0.0
    ttc_prediction_age_s: float = 0.0


TRACKER_CSV_HEADER = (
    "sample_index", "time_monotonic_ns", "elapsed_s", "end_reason", "phase",
    "tracker_id", "frame_id", "camera_timestamp_ns", "camera_received_at_s",
    "camera_age_s", "new_camera_frame", "locked", "score", "bbox_x", "bbox_y",
    "bbox_width", "bbox_height", "dx_norm", "dy_norm", "bbox_fill",
    "scale_px", "log_scale", "scale_innovation", "scale_reason",
    "filtered_log_scale_rate_hz", "inverse_ttc_measured_hz", "measured_ttc_s",
    "effective_ttc_s", "ttc_prediction_age_s",
    "roll_deg", "pitch_deg", "heading_deg", "attitude_age_s",
    "altitude_m", "vertical_distance_m", "target_ttc_s", "inverse_ttc_target_hz",
    "pitch_initial_deg", "pitch_raw_deg", "pitch_command_deg",
    "vertical_nominal_m_s", "vertical_alignment_m_s", "vertical_target_m_s",
    "vertical_setpoint_m_s",
    "vario_m_s", "vario_age_s", "vertical_error_m_s", "throttle_p_rc",
    "throttle_i_rc", "raw_vertical_accel_m_s2",
    "filtered_vertical_accel_m_s2", "throttle_d_rc",
    "tilt_hover_rc", "throttle_command_rc", "yaw_rate_target_dps",
    "yaw_rate_dps", "alignment_count",
    "commit_count",
    "commit_block_reason", "exit_requested", "exit_reason", "result_valid",
    "result_reason", "ch1_roll", "ch2_pitch", "ch3_throttle", "ch4_yaw",
    "ch5_arm", "ch6_angle", "ch7_aux3", "ch8_aux4",
)


class TrackerController:
    """Control visual closing with optical TTC and altitude/vario feedback."""

    def __init__(
        self,
        parameters: Parameters,
        *,
        csv_path: str | Path | None = None,
    ) -> None:
        self._parameters = parameters
        self._config_lock = threading.Lock()
        self._config = TrackerConfig.from_parameters(parameters)
        self._filter = OpticalTtcFilter()
        self._latest_observation: TrackerObservation | None = None
        self._latest_valid_observation: TrackerObservation | None = None
        self._latest_control_observation: TrackerObservation | None = None
        self._last_scale_update = ScaleUpdate(False, False, None, None, None)
        self._first_valid_time_s: float | None = None
        self._valid_frame_count = 0
        self._ready_to_track = False
        self._active = False
        self._exit_requested = False
        self._exit_reason: str | None = None
        self._completion_latched = False
        self._phase = TrackerPhase.TRACKING
        self._commit_count = 0
        self._alignment_count = 0
        self._commit_deadline_s: float | None = None
        self._frozen_result: TrackerControlResult | None = None
        self._pitch_command_deg = 0.0
        self._yaw_rate_command_dps = 0.0
        self._last_update_s: float | None = None
        self._altitude_m: float | None = None
        self._vertical_speed_m_s: float | None = None
        self._vertical_setpoint_m_s: float | None = None
        self._vertical_integral_rc = 0.0
        self._previous_vario_m_s: float | None = None
        self._previous_vario_time_s: float | None = None
        self._raw_vertical_accel_m_s2 = 0.0
        self._filtered_vertical_accel_m_s2 = 0.0
        self._altitude_sample_time_s: float | None = None
        self._roll_deg: float | None = None
        self._attitude_pitch_deg: float | None = None
        self._heading_deg: float | None = None
        self._attitude_sample_time_s: float | None = None
        self._diagnostics = LoopDiagnostics()
        self._csv_path = None if csv_path is None else Path(csv_path)
        self._rows: list[dict[str, object]] = []
        self._log_started_s: float | None = None
        parameters.on_parameter_changed.subscribe(self.on_parameter_changed)

    @property
    def ready_to_track(self) -> bool:
        return self._ready_to_track

    @property
    def exit_requested(self) -> bool:
        return self._exit_requested

    @property
    def exit_reason(self) -> str | None:
        return self._exit_reason

    @property
    def completion_latched(self) -> bool:
        return self._completion_latched

    @property
    def phase(self) -> TrackerPhase:
        return self._phase

    def on_parameter_changed(self, _name: str, _value: object) -> None:
        try:
            updated = TrackerConfig.from_parameters(self._parameters)
        except (KeyError, TypeError, ValueError):
            log.exception("Rejected invalid TTC tracker parameter update")
            return
        with self._config_lock:
            self._config = updated

    def _config_snapshot(self) -> TrackerConfig:
        with self._config_lock:
            return self._config

    def vertical_speed_is_fresh(
        self,
        *,
        now_s: float,
        vertical_speed_m_s: float | None,
        sample_time_s: float | None,
    ) -> bool:
        return self._validate_vario(now_s, vertical_speed_m_s, sample_time_s)[2]

    def observe(
        self,
        observation: TrackerObservation | None,
        *,
        now_s: float,
        mode_selected: bool,
        altitude_m: float | None = None,
        vertical_speed_m_s: float | None = None,
        altitude_sample_time_s: float | None = None,
        roll_deg: float | None = None,
        pitch_deg: float | None = None,
        heading_deg: float | None = None,
        attitude_sample_time_s: float | None = None,
    ) -> bool:
        self._latest_observation = observation
        self._altitude_m = altitude_m
        self._vertical_speed_m_s = vertical_speed_m_s
        self._altitude_sample_time_s = altitude_sample_time_s
        self._roll_deg = roll_deg
        self._attitude_pitch_deg = pitch_deg
        self._heading_deg = heading_deg
        self._attitude_sample_time_s = attitude_sample_time_s
        if not mode_selected:
            if self._active:
                self._request_exit("tracker deselected")
            else:
                self._clear_acquisition()
            return False
        if self._phase == TrackerPhase.COMMIT:
            return False
        config = self._config_snapshot()
        if observation is None or now_s - observation.received_at_s > config.target_timeout_s:
            if not self._active:
                self._clear_acquisition()
            return False
        if self._is_control_observation_valid(observation, config):
            # Control may use a bbox touching an image edge to steer it back
            # into view. TTC scale estimation remains stricter because a
            # clipped bbox no longer represents the target's full size.
            self._latest_control_observation = observation
        update = self._filter.update(observation, config)
        self._last_scale_update = update
        if update.accepted:
            self._latest_valid_observation = observation
            if update.new_frame:
                if self._first_valid_time_s is None:
                    self._first_valid_time_s = observation.received_at_s
                self._valid_frame_count += 1
        elif not self._active and update.new_frame:
            self._clear_acquisition()
            return False
        if not self._active:
            current_live = (
                self._latest_valid_observation is not None
                and observation.result.frame_id
                == self._latest_valid_observation.result.frame_id
                and observation.result.tracker_id
                == self._latest_valid_observation.result.tracker_id
            )
            history_s = (
                0.0
                if self._first_valid_time_s is None
                else observation.received_at_s - self._first_valid_time_s
            )
            self._ready_to_track = (
                current_live
                and self._valid_frame_count >= config.lock_frames
                and history_s >= config.lock_history_s
            )
        return self._ready_to_track

    def start_tracking(
        self,
        *,
        now_s: float,
        vertical_speed_m_s: float,
        vertical_speed_sample_time_s: float,
    ) -> None:
        if not self._ready_to_track:
            raise ValueError("fresh TTC acquisition is required to start tracking")
        if not self.vertical_speed_is_fresh(
            now_s=now_s,
            vertical_speed_m_s=vertical_speed_m_s,
            sample_time_s=vertical_speed_sample_time_s,
        ):
            raise ValueError("fresh vertical speed is required to start tracking")
        config = self._config_snapshot()
        self._active = True
        self._ready_to_track = False
        self._exit_requested = False
        self._exit_reason = None
        self._completion_latched = False
        self._phase = TrackerPhase.ALIGN
        self._commit_count = 0
        self._alignment_count = 0
        self._commit_deadline_s = None
        self._frozen_result = None
        self._pitch_command_deg = config.alignment_pitch_deg
        self._yaw_rate_command_dps = 0.0
        self._vertical_setpoint_m_s = vertical_speed_m_s
        self._vertical_integral_rc = 0.0
        self._previous_vario_m_s = vertical_speed_m_s
        self._previous_vario_time_s = vertical_speed_sample_time_s
        self._raw_vertical_accel_m_s2 = 0.0
        self._filtered_vertical_accel_m_s2 = 0.0
        self._last_update_s = now_s
        self._rows = []
        self._log_started_s = None
        log.info(
            "TTC tracker phase: acquisition -> align; pitch_deg={:.2f} "
            "horizontal_gate={:.3f} required_frames={} vario_m_s={:.3f}",
            config.alignment_pitch_deg,
            config.horizontal_alignment_threshold,
            config.alignment_frames,
            vertical_speed_m_s,
        )

    def stop_tracking(self, *, end_reason: str = "unknown") -> None:
        if self._active:
            log.info(
                "TTC tracker phase: {} -> stopped; reason={}",
                self._phase.value,
                end_reason,
            )
        self._export_log(end_reason)
        self._active = False
        self._exit_requested = False
        self._exit_reason = None
        self._completion_latched = False
        self._phase = TrackerPhase.TRACKING
        self._commit_count = 0
        self._alignment_count = 0
        self._commit_deadline_s = None
        self._frozen_result = None
        self._pitch_command_deg = 0.0
        self._yaw_rate_command_dps = 0.0
        self._vertical_setpoint_m_s = None
        self._vertical_integral_rc = 0.0
        self._previous_vario_m_s = None
        self._previous_vario_time_s = None
        self._raw_vertical_accel_m_s2 = 0.0
        self._filtered_vertical_accel_m_s2 = 0.0
        self._last_update_s = None
        self._clear_acquisition()

    def update(
        self,
        *,
        now_s: float,
        vertical_speed_m_s: float | None = None,
        vertical_speed_sample_time_s: float | None = None,
    ) -> TrackerControlResult:
        """Advance the active tracker controller by one application-loop step.

        ``observe()`` must run before this method so the controller has the newest
        camera observation, altitude, and attitude diagnostics.  ``update()``
        receives the current vario sample separately because vertical velocity is
        feedback for the throttle PI-D loop and must be checked for freshness at
        the instant the command is calculated.

        The method performs the following flow:

        1. Return neutral/hover channels when tracking is inactive.
        2. While in ``COMMIT``, keep returning the frozen collision command until
           its deadline, then request that the application leave TRACK.
        3. Require an altitude value and validate the vario sample.  A missing
           altitude or missing, stale, future-dated, or non-finite vario requests
           a safe exit.
        4. Update the filtered vertical-acceleration estimate only when a new
           vario sample arrives.
        5. Validate camera freshness.  A duplicate frame may reuse the previous
           estimate, but it cannot advance alignment or commit counters.
        6. Call ``_control()`` to handle ALIGN/TRACKING phase logic, optical TTC,
           pitch and yaw commands, and the vertical PI-D throttle command.
        7. Record the returned result in the in-memory CSV diagnostics buffer.

        ``exit_requested`` is intentionally only a request.  The application
        state machine owns the actual TRACK-to-ALT_HOLD transition and later
        calls ``stop_tracking()`` to export diagnostics and reset this object.

        Mermaid source for the control flow (rendering requires Mermaid support
        in the documentation generator):

        ```mermaid
            flowchart TD
                A[update] --> B{Controller active?}
                B -- No --> C[Return safe hover result]
                B -- Yes --> D{Phase is COMMIT?}
                D -- Yes --> E[Hold frozen RC command]
                E --> F{Commit deadline reached?}
                F -- Yes --> G[Request TRACK exit]
                F -- No --> H[Record result]
                G --> H
                D -- No --> I{Vario and altitude fresh?}
                I -- No --> J[Request exit and safe hover]
                J --> H
                I -- Yes --> K[Update vertical acceleration]
                K --> L{Camera observation fresh?}
                L -- No --> M[Request exit and safe hover]
                M --> H
                L -- Yes --> N[_control: phase, TTC, pitch, yaw, throttle]
                N --> H
                H --> O[Return TrackerControlResult]
        ```

        Args:
            now_s: Current local monotonic time for freshness checks and loop dt.
            vertical_speed_m_s: Latest vario velocity in metres per second;
                positive is upward and negative is descent.
            vertical_speed_sample_time_s: Local monotonic receive time belonging
                to ``vertical_speed_m_s``.

        Returns:
            The complete eight-channel RC request plus controller diagnostics.
            Inspect ``valid`` before using active control values; invalid results
            contain safe centered pitch/yaw and hover throttle.
        """
        config = self._config_snapshot()
        if not self._active:
            return self._safe_result(config, "tracker controller is inactive")
        if self._phase == TrackerPhase.COMMIT:
            if self._commit_deadline_s is not None and now_s >= self._commit_deadline_s:
                self._completion_latched = True
                self._request_exit("commit complete")
            result = self._frozen_result or self._safe_result(config, "commit unavailable")
            return self._record(result, now_s)
        speed, speed_age, speed_valid = self._validate_vario(
            now_s,
            vertical_speed_m_s,
            vertical_speed_sample_time_s,
        )
        self._vertical_speed_m_s = speed
        self._altitude_sample_time_s = vertical_speed_sample_time_s
        if not speed_valid or speed is None or self._altitude_m is None:
            self._request_exit("altitude or vario stale")
            return self._record(self._safe_result(config, "altitude or vario stale"), now_s)
        self._update_vertical_acceleration(
            speed,
            vertical_speed_sample_time_s,
            config,
        )
        observation = self._latest_control_observation
        if observation is None or now_s - observation.received_at_s > config.target_timeout_s:
            self._request_exit("tracker observation stale")
            return self._record(self._safe_result(config, "tracker observation stale"), now_s)
        dt_s = max(0.0, now_s - (self._last_update_s or now_s))
        self._last_update_s = now_s
        result = self._control(config, observation, speed, speed_age, dt_s, now_s)
        return self._record(result, now_s)

    def _control(
        self,
        config: TrackerConfig,
        observation: TrackerObservation,
        vario: float,
        vario_age_s: float | None,
        dt_s: float,
        now_s: float,
    ) -> TrackerControlResult:
        result = observation.result
        dx, dy = self._normalized_errors(result, config)
        live_frame = self._last_scale_update.accepted and self._last_scale_update.new_frame
        if self._phase == TrackerPhase.ALIGN and self._last_scale_update.new_frame:
            if live_frame and abs(dx) <= config.horizontal_alignment_threshold:
                self._alignment_count += 1
            else:
                self._alignment_count = 0
            if self._alignment_count >= config.alignment_frames:
                self._phase = TrackerPhase.TRACKING
                # Do not treat scale changes during staging as forward closing.
                self._filter.rate_hz = 0.0
                log.info(
                    "TTC tracker phase: align -> tracking; dx={:.3f} dy={:.3f} "
                    "altitude_m={:.2f} aligned_frames={}",
                    dx,
                    dy,
                    self._altitude_m,
                    self._alignment_count,
                )
        inverse_measured = clamp(
            max(0.0, self._filter.rate_hz),
            0.0,
            config.inverse_ttc_max_hz,
        )
        measured_ttc = (
            config.logged_ttc_max_s
            if inverse_measured <= 1.0 / config.logged_ttc_max_s
            else 1.0 / inverse_measured
        )
        ttc_prediction_age_s = (
            0.0
            if self._filter.time_s is None
            else max(0.0, now_s - self._filter.time_s)
        )
        effective_ttc = max(
            measured_ttc - ttc_prediction_age_s,
            config.minimum_target_ttc_s,
        )
        inverse_effective = 1.0 / effective_ttc
        vertical_distance = config.target_height_m - self._altitude_m
        target_ttc = max(
            abs(vertical_distance) / config.nominal_vertical_speed_m_s,
            config.minimum_target_ttc_s,
        )
        inverse_target = 1.0 / target_ttc
        if self._phase == TrackerPhase.ALIGN:
            pitch_raw = config.alignment_pitch_deg
        else:
            ttc_pitch_raw = config.pitch_initial_deg - config.inverse_ttc_kp * (
                inverse_target - inverse_effective
            )
            # Blend continuously instead of waiting for perfect vertical
            # alignment before accelerating forward. At the image edge the
            # conservative alignment pitch dominates; near center TTC has full
            # pitch authority.
            alignment_weight = clamp(abs(dy), 0.0, 1.0)
            pitch_raw = (
                (1.0 - alignment_weight) * ttc_pitch_raw
                + alignment_weight * config.alignment_pitch_deg
            )
        pitch_raw = clamp(pitch_raw, config.pitch_minimum_deg, 0.0)
        pitch_error = pitch_raw - self._pitch_command_deg
        pitch_slew = (
            config.pitch_recovery_slew_deg_s
            if pitch_error > 0.0
            else config.pitch_slew_deg_s
        )
        max_pitch_step = pitch_slew * dt_s
        self._pitch_command_deg += clamp(
            pitch_error,
            -max_pitch_step,
            max_pitch_step,
        )
        if self._phase == TrackerPhase.ALIGN:
            # Keep the conservative alignment pitch, but correct vertical image
            # error before forward tracking. A target below image center needs
            # descent now; holding altitude lets it reach the lower frame edge.
            dy_deadbanded = self._deadband(dy, config.deadband)
            vertical_nominal = 0.0
            vertical_alignment = clamp(
                config.vertical_alignment_kp * dy_deadbanded,
                -config.vertical_alignment_max_m_s,
                config.vertical_alignment_max_m_s,
            )
            vertical_target = clamp(
                vertical_alignment,
                config.vertical_speed_min_m_s,
                config.vertical_speed_max_m_s,
            )
        else:
            dy_deadbanded = self._deadband(dy, config.deadband)
            # Match altitude arrival time to the observed optical arrival time.
            # This couples descent to forward closing and avoids spending most
            # altitude before the vehicle has accelerated toward the target.
            vertical_nominal = vertical_distance / effective_ttc
            alignment_limit = (
                config.near_field_alignment_max_m_s
                if self._last_scale_update.reason == "bbox clipped"
                else config.vertical_alignment_max_m_s
            )
            vertical_alignment = clamp(
                config.vertical_alignment_kp * dy_deadbanded,
                -alignment_limit,
                alignment_limit,
            )
            vertical_target = clamp(
                vertical_nominal + vertical_alignment,
                config.vertical_speed_min_m_s,
                config.vertical_speed_max_m_s,
            )
        previous_vertical_setpoint = (
            vario
            if self._vertical_setpoint_m_s is None
            else self._vertical_setpoint_m_s
        )
        max_vertical_step = config.vertical_accel_limit_m_s2 * dt_s
        vertical_setpoint = previous_vertical_setpoint + clamp(
            vertical_target - previous_vertical_setpoint,
            -max_vertical_step,
            max_vertical_step,
        )
        self._vertical_setpoint_m_s = vertical_setpoint
        vertical_error = vertical_setpoint - vario
        throttle_p = config.vertical_velocity_kp * vertical_error
        throttle_d = -config.vertical_velocity_kd * self._filtered_vertical_accel_m_s2
        integral_candidate = clamp(
            self._vertical_integral_rc
            + config.vertical_velocity_ki * vertical_error * dt_s,
            -config.vertical_integral_max_rc,
            config.vertical_integral_max_rc,
        )
        correction_candidate = throttle_p + integral_candidate + throttle_d
        correction_limit = config.throttle_max_correction_rc
        integration_reduces_saturation = (
            correction_candidate > correction_limit and vertical_error < 0.0
        ) or (
            correction_candidate < -correction_limit and vertical_error > 0.0
        )
        if (
            abs(correction_candidate) <= correction_limit
            or integration_reduces_saturation
        ):
            self._vertical_integral_rc = integral_candidate
        throttle_correction = clamp(
            throttle_p + self._vertical_integral_rc + throttle_d,
            -correction_limit,
            correction_limit,
        )
        tilt_hover = RC_MIN + (config.hover_baseline_rc - RC_MIN) / max(
            math.cos(math.radians(self._pitch_command_deg)),
            0.35,
        )
        yaw_rate_target = clamp(
            config.yaw_sign * config.yaw_kp * self._deadband(dx, config.deadband),
            -config.yaw_max_dps,
            config.yaw_max_dps,
        )
        max_yaw_rate_step = config.yaw_slew_dps2 * dt_s
        self._yaw_rate_command_dps += clamp(
            yaw_rate_target - self._yaw_rate_command_dps,
            -max_yaw_rate_step,
            max_yaw_rate_step,
        )
        yaw_rate = self._yaw_rate_command_dps
        mapper = BetaflightRcMapper(
            yaw_center_sensitivity_dps=config.yaw_center_sensitivity_dps,
            yaw_max_rate_dps=config.yaw_stick_rate_dps,
            yaw_expo=config.yaw_rate_expo,
        )
        channels = self._channels(
            pitch=mapper.angle_to_rc(
                self._pitch_command_deg,
                angle_limit_deg=config.angle_limit_deg,
                sign=-1.0,
            ),
            throttle=round(tilt_hover + throttle_correction),
            yaw=mapper.yaw_rate_to_rc(yaw_rate),
        )
        fill = max(
            result.bbox_width / config.camera_width_px,
            result.bbox_height / config.camera_height_px,
        )
        clipped_near_field = (
            self._last_scale_update.reason == "bbox clipped"
            and fill >= config.clipped_commit_fill_fraction
        )
        commit_block = None if clipped_near_field else self._commit_block(
            config, fill=fill, measured_ttc=effective_ttc, dx=dx, dy=dy
        )
        if self._phase == TrackerPhase.TRACKING and self._last_scale_update.new_frame:
            if (live_frame or clipped_near_field) and commit_block is None:
                self._commit_count += 1
            else:
                self._commit_count = 0
        terminal_ready = self._commit_count >= config.commit_frames
        self._diagnostics = LoopDiagnostics(
            new_camera_frame=self._last_scale_update.new_frame,
            scale_px=self._last_scale_update.scale_px,
            log_scale=self._filter.log_scale,
            scale_innovation=self._last_scale_update.innovation,
            scale_reason=self._last_scale_update.reason,
            inverse_ttc_measured_hz=inverse_measured,
            measured_ttc_s=measured_ttc,
            effective_ttc_s=effective_ttc,
            ttc_prediction_age_s=ttc_prediction_age_s,
            target_ttc_s=target_ttc,
            inverse_ttc_target_hz=inverse_target,
            pitch_raw_deg=pitch_raw,
            vertical_distance_m=vertical_distance,
            vertical_nominal_m_s=vertical_nominal,
            vertical_alignment_m_s=vertical_alignment,
            raw_vertical_accel_m_s2=self._raw_vertical_accel_m_s2,
            filtered_vertical_accel_m_s2=self._filtered_vertical_accel_m_s2,
            throttle_d_rc=throttle_d,
            bbox_fill=fill,
            yaw_rate_target_dps=yaw_rate_target,
        )
        control_result = TrackerControlResult(
            channels=channels,
            phase=self._phase,
            error_x=dx,
            error_y=dy,
            pitch_command_deg=self._pitch_command_deg,
            yaw_rate_dps=yaw_rate,
            drone_vertical_speed_m_s=vario,
            drone_vertical_speed_age_s=vario_age_s,
            drone_vertical_speed_valid=True,
            vertical_speed_requested_m_s=vertical_nominal,
            vertical_speed_limit_m_s=abs(config.vertical_speed_min_m_s),
            vertical_speed_target_m_s=vertical_target,
            vertical_speed_setpoint_m_s=vertical_setpoint,
            vertical_speed_error_m_s=vertical_error,
            throttle_visual_correction_rc=vertical_alignment,
            throttle_damping_correction_rc=throttle_p,
            throttle_correction_rc=throttle_correction,
            terminal_ready=terminal_ready,
            terminal_block_reason=commit_block,
            terminal_ready_elapsed_s=None,
            terminal_elapsed_s=None,
            valid=True,
        )
        if terminal_ready:
            self._phase = TrackerPhase.COMMIT
            self._commit_deadline_s = now_s + config.commit_duration_s
            control_result = replace(control_result, phase=TrackerPhase.COMMIT)
            self._frozen_result = control_result
            log.info(
                "TTC tracker phase: tracking -> commit; fill={:.3f} "
                "ttc_s={:.3f} dx={:.3f} dy={:.3f} duration_s={:.2f}",
                fill,
                measured_ttc,
                dx,
                dy,
                config.commit_duration_s,
            )
        return control_result

    @staticmethod
    def _commit_block(
        config: TrackerConfig,
        *,
        fill: float,
        measured_ttc: float,
        dx: float,
        dy: float,
    ) -> str | None:
        if fill < config.commit_fill_fraction:
            return "bbox fill"
        if measured_ttc > config.commit_ttc_s:
            return "ttc"
        if abs(dx) > config.commit_alignment:
            return "horizontal alignment"
        if abs(dy) > config.commit_alignment:
            return "vertical alignment"
        return None

    @staticmethod
    def _normalized_errors(result, config: TrackerConfig) -> tuple[float, float]:
        center_x = result.bbox_x + result.bbox_width / 2.0
        center_y = result.bbox_y + result.bbox_height / 2.0
        dx = (center_x - config.camera_cx_px) / (config.camera_width_px / 2.0)
        dy = (config.camera_cy_px - center_y) / (config.camera_height_px / 2.0)
        return clamp(dx, -1.0, 1.0), clamp(dy, -1.0, 1.0)

    @staticmethod
    def _is_control_observation_valid(
        observation: TrackerObservation,
        config: TrackerConfig,
    ) -> bool:
        """Accept a locked bbox that intersects the image, including its edges."""
        result = observation.result
        return (
            result.locked
            and result.bbox_width > 0
            and result.bbox_height > 0
            and result.bbox_x < config.camera_width_px
            and result.bbox_y < config.camera_height_px
            and result.bbox_x + result.bbox_width > 0
            and result.bbox_y + result.bbox_height > 0
        )

    @staticmethod
    def _deadband(value: float, deadband: float) -> float:
        if abs(value) <= deadband:
            return 0.0
        return math.copysign(abs(value) - deadband, value)

    @staticmethod
    def _validate_vario(
        now_s: float,
        speed: float | None,
        sample_time_s: float | None,
    ) -> tuple[float | None, float | None, bool]:
        if speed is None or sample_time_s is None:
            return None, None, False
        age_s = now_s - sample_time_s
        valid = math.isfinite(speed) and 0.0 <= age_s <= _VERTICAL_SPEED_TIMEOUT_S
        return (float(speed) if valid else None), age_s, valid

    def _update_vertical_acceleration(
        self,
        speed_m_s: float,
        sample_time_s: float | None,
        config: TrackerConfig,
    ) -> None:
        if sample_time_s is None:
            return
        previous_time = self._previous_vario_time_s
        previous_speed = self._previous_vario_m_s
        if previous_time is None or previous_speed is None:
            self._previous_vario_time_s = sample_time_s
            self._previous_vario_m_s = speed_m_s
            return
        if sample_time_s <= previous_time:
            return
        dt_s = sample_time_s - previous_time
        raw_accel = clamp(
            (speed_m_s - previous_speed) / dt_s,
            -_VERTICAL_ACCEL_LIMIT_M_S2,
            _VERTICAL_ACCEL_LIMIT_M_S2,
        )
        self._raw_vertical_accel_m_s2 = raw_accel
        alpha = config.vertical_accel_filter_alpha
        self._filtered_vertical_accel_m_s2 += alpha * (
            raw_accel - self._filtered_vertical_accel_m_s2
        )
        self._previous_vario_time_s = sample_time_s
        self._previous_vario_m_s = speed_m_s

    def _request_exit(self, reason: str) -> None:
        if not self._exit_requested:
            self._exit_requested = True
            self._exit_reason = reason
            log.warning("TTC tracker exit requested: {}", reason)

    def _clear_acquisition(self) -> None:
        self._filter.reset()
        self._latest_valid_observation = None
        self._latest_control_observation = None
        self._first_valid_time_s = None
        self._valid_frame_count = 0
        self._ready_to_track = False

    def _safe_result(self, config: TrackerConfig, reason: str) -> TrackerControlResult:
        return TrackerControlResult(
            channels=self._channels(
                pitch=RC_MID,
                throttle=round(config.hover_baseline_rc),
                yaw=RC_MID,
            ),
            phase=self._phase,
            error_x=None,
            error_y=None,
            pitch_command_deg=0.0,
            yaw_rate_dps=0.0,
            drone_vertical_speed_m_s=None,
            drone_vertical_speed_age_s=None,
            drone_vertical_speed_valid=False,
            vertical_speed_requested_m_s=None,
            vertical_speed_limit_m_s=None,
            vertical_speed_target_m_s=None,
            vertical_speed_setpoint_m_s=None,
            vertical_speed_error_m_s=None,
            throttle_visual_correction_rc=0.0,
            throttle_damping_correction_rc=0.0,
            throttle_correction_rc=0.0,
            terminal_ready=False,
            terminal_block_reason=None,
            terminal_ready_elapsed_s=None,
            terminal_elapsed_s=None,
            valid=False,
            reason=reason,
        )

    @staticmethod
    def _channels(*, pitch: int, throttle: int, yaw: int) -> tuple[int, ...]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.PITCH] = int(clamp(pitch, RC_MIN, RC_MAX))
        channels[RCChannel.THROTTLE] = int(clamp(throttle, RC_MIN, RC_MAX))
        channels[RCChannel.YAW] = int(clamp(yaw, RC_MIN, RC_MAX))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        channels[RCChannel.AUX3] = RC_MIN
        channels[RCChannel.AUX4] = RC_MIN
        return tuple(channels)

    def _record(self, result: TrackerControlResult, now_s: float) -> TrackerControlResult:
        if self._csv_path is None:
            return result
        if self._log_started_s is None:
            self._log_started_s = now_s
        observation = self._latest_observation
        message = None if observation is None else observation.result
        config = self._config_snapshot()
        d = self._diagnostics
        channels = result.channels
        row = {
            "sample_index": len(self._rows),
            "time_monotonic_ns": round(now_s * 1_000_000_000),
            "elapsed_s": now_s - self._log_started_s,
            "end_reason": "",
            "phase": result.phase.value,
            "tracker_id": None if message is None else message.tracker_id,
            "frame_id": None if message is None else message.frame_id,
            "camera_timestamp_ns": None if message is None else message.timestamp_ns,
            "camera_received_at_s": None if observation is None else observation.received_at_s,
            "camera_age_s": None if observation is None else now_s - observation.received_at_s,
            "new_camera_frame": d.new_camera_frame,
            "locked": None if message is None else message.locked,
            "score": None if message is None else message.score,
            "bbox_x": None if message is None else message.bbox_x,
            "bbox_y": None if message is None else message.bbox_y,
            "bbox_width": None if message is None else message.bbox_width,
            "bbox_height": None if message is None else message.bbox_height,
            "dx_norm": result.error_x,
            "dy_norm": result.error_y,
            "bbox_fill": d.bbox_fill,
            "scale_px": d.scale_px,
            "log_scale": d.log_scale,
            "scale_innovation": d.scale_innovation,
            "scale_reason": d.scale_reason,
            "filtered_log_scale_rate_hz": self._filter.rate_hz,
            "inverse_ttc_measured_hz": d.inverse_ttc_measured_hz,
            "measured_ttc_s": d.measured_ttc_s,
            "effective_ttc_s": d.effective_ttc_s,
            "ttc_prediction_age_s": d.ttc_prediction_age_s,
            "roll_deg": self._roll_deg,
            "pitch_deg": self._attitude_pitch_deg,
            "heading_deg": self._heading_deg,
            "attitude_age_s": (
                None
                if self._attitude_sample_time_s is None
                else now_s - self._attitude_sample_time_s
            ),
            "altitude_m": self._altitude_m,
            "vertical_distance_m": d.vertical_distance_m,
            "target_ttc_s": d.target_ttc_s,
            "inverse_ttc_target_hz": d.inverse_ttc_target_hz,
            "pitch_initial_deg": config.pitch_initial_deg,
            "pitch_raw_deg": d.pitch_raw_deg,
            "pitch_command_deg": result.pitch_command_deg,
            "vertical_nominal_m_s": d.vertical_nominal_m_s,
            "vertical_alignment_m_s": d.vertical_alignment_m_s,
            "vertical_target_m_s": result.vertical_speed_target_m_s,
            "vertical_setpoint_m_s": result.vertical_speed_setpoint_m_s,
            "vario_m_s": result.drone_vertical_speed_m_s,
            "vario_age_s": result.drone_vertical_speed_age_s,
            "vertical_error_m_s": result.vertical_speed_error_m_s,
            "throttle_p_rc": result.throttle_damping_correction_rc,
            "throttle_i_rc": self._vertical_integral_rc,
            "raw_vertical_accel_m_s2": d.raw_vertical_accel_m_s2,
            "filtered_vertical_accel_m_s2": d.filtered_vertical_accel_m_s2,
            "throttle_d_rc": d.throttle_d_rc,
            "tilt_hover_rc": (
                None
                if result.vertical_speed_error_m_s is None
                else channels[RCChannel.THROTTLE] - result.throttle_correction_rc
            ),
            "throttle_command_rc": channels[RCChannel.THROTTLE],
            "yaw_rate_target_dps": d.yaw_rate_target_dps,
            "yaw_rate_dps": result.yaw_rate_dps,
            "alignment_count": self._alignment_count,
            "commit_count": self._commit_count,
            "commit_block_reason": result.terminal_block_reason,
            "exit_requested": self._exit_requested,
            "exit_reason": self._exit_reason,
            "result_valid": result.valid,
            "result_reason": result.reason,
            "ch1_roll": channels[0], "ch2_pitch": channels[1],
            "ch3_throttle": channels[2], "ch4_yaw": channels[3],
            "ch5_arm": channels[4], "ch6_angle": channels[5],
            "ch7_aux3": channels[6], "ch8_aux4": channels[7],
        }
        self._rows.append(row)
        return result

    def _export_log(self, end_reason: str) -> None:
        if self._csv_path is None or not self._rows:
            return
        temporary = self._csv_path.with_name(f".{self._csv_path.name}.tmp")
        try:
            self._csv_path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=TRACKER_CSV_HEADER)
                writer.writeheader()
                for row in self._rows:
                    row["end_reason"] = end_reason
                    writer.writerow(row)
            temporary.replace(self._csv_path)
        except OSError:
            log.exception("Failed to export TTC tracker CSV {}", self._csv_path)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                log.exception("Failed to remove temporary TTC CSV {}", temporary)
        finally:
            self._rows = []
            self._log_started_s = None

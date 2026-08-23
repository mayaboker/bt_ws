"""Visual target-centering controller for the TRACK flight state."""

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
from bt_app.services import TargetEstimate


DEFAULT_TRACKER_CSV_PATH = Path("logs/tracker_controller.csv")
TRACKER_CSV_HEADER = (
    "sample_index",
    "time_monotonic_ns",
    "elapsed_s",
    "end_reason",
    "observed_frame_id",
    "observed_timestamp_ns",
    "observed_valid",
    "observed_reason",
    "observed_depth_m",
    "observed_slant_range_m",
    "observed_dx_norm",
    "observed_dy_norm",
    "observed_vx_m_s",
    "observed_vy_m_s",
    "control_frame_id",
    "control_estimate_age_s",
    "control_depth_m",
    "control_slant_range_m",
    "control_dx_norm",
    "control_dy_norm",
    "control_dx_deadbanded",
    "control_dy_deadbanded",
    "control_vx_m_s",
    "control_vy_m_s",
    "phase",
    "result_valid",
    "result_reason",
    "exit_requested",
    "completion_latched",
    "pitch_command_deg",
    "yaw_rate_dps",
    "drone_vertical_speed_m_s",
    "drone_vertical_speed_age_s",
    "drone_vertical_speed_valid",
    "vertical_speed_requested_m_s",
    "vertical_speed_target_m_s",
    "vertical_speed_setpoint_m_s",
    "vertical_speed_error_m_s",
    "throttle_visual_correction_rc",
    "throttle_damping_correction_rc",
    "throttle_correction_rc",
    "ch1_roll",
    "ch2_pitch",
    "ch3_throttle",
    "ch4_yaw",
    "ch5_arm",
    "ch6_angle",
    "ch7_aux3",
    "ch8_aux4",
    "trk_pitch_deg",
    "trk_pitch_rate_deg_s",
    "trk_yaw_kp",
    "trk_yaw_max_dps",
    "trk_throttle_kp",
    "trk_vertical_speed_kd",
    "trk_vertical_speed_max_m_s",
    "trk_vertical_speed_accel_m_s2",
    "trk_throttle_max_rc",
    "trk_deadband",
    "trk_timeout_s",
    "trk_lock_frames",
    "trk_commit_depth_m",
    "trk_commit_s",
    "bf_angle_limit_deg",
    "hover_baseline_rc",
    "bf_yaw_rate_dps",
)

_APPROACH_START_FRACTION = 0.60
_APPROACH_TERMINAL_PITCH_DEG = -5.0
_VERTICAL_SPEED_TIMEOUT_S = 0.30


class TrackerPhase(StrEnum):
    TRACKING = "tracking"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True)
class TrackerConfig:
    pitch_deg: float
    pitch_rate_deg_s: float
    yaw_kp: float
    yaw_max_dps: float
    throttle_kp: float
    vertical_speed_kd: float
    vertical_speed_max_m_s: float
    vertical_speed_accel_m_s2: float
    throttle_max_rc: float
    deadband: float
    timeout_s: float
    lock_frames: int
    commit_depth_m: float
    commit_s: float
    angle_limit_deg: float
    hover_baseline_rc: float
    yaw_stick_rate_dps: float

    def __post_init__(self) -> None:
        numeric = (
            self.pitch_deg,
            self.pitch_rate_deg_s,
            self.yaw_kp,
            self.yaw_max_dps,
            self.throttle_kp,
            self.vertical_speed_kd,
            self.vertical_speed_max_m_s,
            self.vertical_speed_accel_m_s2,
            self.throttle_max_rc,
            self.deadband,
            self.timeout_s,
            self.commit_depth_m,
            self.commit_s,
            self.angle_limit_deg,
            self.hover_baseline_rc,
            self.yaw_stick_rate_dps,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("tracker configuration must be finite")
        if self.pitch_deg > 0 or abs(self.pitch_deg) > self.angle_limit_deg:
            raise ValueError("tracker pitch must be forward and within angle limit")
        if self.pitch_rate_deg_s <= 0:
            raise ValueError("tracker pitch rate must be positive")
        if self.yaw_kp < 0 or self.yaw_max_dps < 0:
            raise ValueError("tracker yaw values must be nonnegative")
        if (
            self.throttle_kp < 0
            or self.vertical_speed_kd <= 0
            or self.vertical_speed_max_m_s <= 0
            or self.vertical_speed_accel_m_s2 <= 0
            or self.throttle_max_rc < 0
        ):
            raise ValueError("tracker throttle values must be nonnegative")
        if not 0 <= self.deadband < 1:
            raise ValueError("tracker deadband must be in [0, 1)")
        if self.timeout_s <= 0 or self.lock_frames <= 0:
            raise ValueError("tracker timeout and lock frames must be positive")
        if self.commit_depth_m <= 0 or self.commit_s < 0:
            raise ValueError("tracker commit values are invalid")
        if self.angle_limit_deg <= 0 or self.yaw_stick_rate_dps <= 0:
            raise ValueError("flight-controller mapping limits must be positive")
        if not RC_MIN <= self.hover_baseline_rc <= RC_MAX:
            raise ValueError("hover baseline must be inside the RC range")

    @classmethod
    def from_parameters(cls, parameters: Parameters) -> "TrackerConfig":
        return cls(
            pitch_deg=parameters.get(ParameterKey.TRK_PITCH_DEG),
            pitch_rate_deg_s=parameters.get(ParameterKey.TRK_PITCH_RATE),
            yaw_kp=parameters.get(ParameterKey.TRK_YAW_KP),
            yaw_max_dps=parameters.get(ParameterKey.TRK_YAW_MAX),
            throttle_kp=parameters.get(ParameterKey.TRK_THR_KP),
            vertical_speed_kd=parameters.get(ParameterKey.TRK_VZ_KD),
            vertical_speed_max_m_s=parameters.get(ParameterKey.TRK_VZ_MAX),
            vertical_speed_accel_m_s2=parameters.get(ParameterKey.TRK_VZ_ACCEL),
            throttle_max_rc=parameters.get(ParameterKey.TRK_THR_MAX),
            deadband=parameters.get(ParameterKey.TRK_DEADBAND),
            timeout_s=parameters.get(ParameterKey.TRK_TIMEOUT_S),
            lock_frames=parameters.get(ParameterKey.TRK_LOCK_FRAMES),
            commit_depth_m=parameters.get(ParameterKey.TRK_COMMIT_M),
            commit_s=parameters.get(ParameterKey.TRK_COMMIT_S),
            angle_limit_deg=parameters.get(ParameterKey.BF_ANGLE_LIMIT),
            hover_baseline_rc=parameters.get(ParameterKey.HOV_BASELINE),
            yaw_stick_rate_dps=parameters.get(ParameterKey.BF_YAW_RATE),
        )


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
    vertical_speed_target_m_s: float | None
    vertical_speed_setpoint_m_s: float | None
    vertical_speed_error_m_s: float | None
    throttle_visual_correction_rc: float
    throttle_damping_correction_rc: float
    throttle_correction_rc: float
    valid: bool
    reason: str | None = None


_PARAMETER_FIELDS = {
    ParameterKey.TRK_PITCH_DEG: "pitch_deg",
    ParameterKey.TRK_PITCH_RATE: "pitch_rate_deg_s",
    ParameterKey.TRK_YAW_KP: "yaw_kp",
    ParameterKey.TRK_YAW_MAX: "yaw_max_dps",
    ParameterKey.TRK_THR_KP: "throttle_kp",
    ParameterKey.TRK_VZ_KD: "vertical_speed_kd",
    ParameterKey.TRK_VZ_MAX: "vertical_speed_max_m_s",
    ParameterKey.TRK_VZ_ACCEL: "vertical_speed_accel_m_s2",
    ParameterKey.TRK_THR_MAX: "throttle_max_rc",
    ParameterKey.TRK_DEADBAND: "deadband",
    ParameterKey.TRK_TIMEOUT_S: "timeout_s",
    ParameterKey.TRK_LOCK_FRAMES: "lock_frames",
    ParameterKey.TRK_COMMIT_M: "commit_depth_m",
    ParameterKey.TRK_COMMIT_S: "commit_s",
    ParameterKey.BF_ANGLE_LIMIT: "angle_limit_deg",
    ParameterKey.HOV_BASELINE: "hover_baseline_rc",
    ParameterKey.BF_YAW_RATE: "yaw_stick_rate_dps",
}


class TrackerController:
    """Acquire a fresh target, center it, and freeze output near impact."""

    def __init__(
        self,
        parameters: Parameters,
        *,
        csv_path: str | Path | None = None,
    ) -> None:
        self._config_lock = threading.Lock()
        self._config = TrackerConfig.from_parameters(parameters)
        self._latest_estimate: TargetEstimate | None = None
        self._current_observation: TargetEstimate | None = None
        self._last_observed_frame_id: int | None = None
        self._valid_frame_count = 0
        self._ready_to_track = False
        self._active = False
        self._exit_requested = False
        self._completion_latched = False
        self._phase = TrackerPhase.TRACKING
        self._commit_deadline_s: float | None = None
        self._last_result: TrackerControlResult | None = None
        self._frozen_result: TrackerControlResult | None = None
        self._command_pitch_deg = 0.0
        self._last_pitch_update_s: float | None = None
        self._vertical_speed_setpoint_m_s: float | None = None
        self._last_vertical_speed_setpoint_update_s: float | None = None
        self._approach_initial_depth_m: float | None = None
        self._approach_start_depth_m: float | None = None
        self._approach_closest_depth_m: float | None = None
        self._observation_valid = False
        self._csv_path = None if csv_path is None else Path(csv_path)
        self._log_rows: list[dict[str, object]] = []
        self._log_started_at_s: float | None = None
        parameters.on_parameter_changed.subscribe(self.on_parameter_changed)

    @property
    def ready_to_track(self) -> bool:
        return self._ready_to_track

    @property
    def exit_requested(self) -> bool:
        return self._exit_requested

    @property
    def completion_latched(self) -> bool:
        return self._completion_latched

    @property
    def phase(self) -> TrackerPhase:
        return self._phase

    def vertical_speed_is_fresh(
        self,
        *,
        now_s: float,
        vertical_speed_m_s: float | None,
        sample_time_s: float | None,
    ) -> bool:
        """Return whether FC vertical-speed feedback is usable for TRACK."""
        _, _, valid = self._validate_vertical_speed(
            now_s=now_s,
            vertical_speed_m_s=vertical_speed_m_s,
            sample_time_s=sample_time_s,
        )
        return valid

    def observe(
        self,
        estimate: TargetEstimate | None,
        *,
        now_s: float,
        mode_selected: bool,
    ) -> bool:
        """Observe one App-loop snapshot and update readiness/exit state."""
        self._current_observation = estimate
        if not mode_selected:
            self._completion_latched = False
            self._clear_acquisition()
            if self._active:
                self._exit_requested = True
            return False

        if self._active and self._phase == TrackerPhase.COMMIT:
            if (
                self._commit_deadline_s is not None
                and now_s >= self._commit_deadline_s
            ):
                self._completion_latched = True
                self._exit_requested = True
            return False

        fresh = self._is_fresh_valid(estimate, now_s)
        if self._active:
            if not fresh:
                self._observation_valid = False
                if not self._is_fresh_valid(self._latest_estimate, now_s):
                    self._exit_requested = True
                return False
            self._observation_valid = True
            self._latest_estimate = estimate
            return False

        if not fresh:
            self._clear_acquisition()
            return False

        self._latest_estimate = estimate
        if estimate is not None and estimate.frame_id != self._last_observed_frame_id:
            self._last_observed_frame_id = estimate.frame_id
            self._valid_frame_count += 1
        self._ready_to_track = (
            self._valid_frame_count >= self._config_snapshot().lock_frames
        )
        return self.ready_to_track

    def start_tracking(
        self,
        *,
        now_s: float,
        vertical_speed_m_s: float,
        vertical_speed_sample_time_s: float,
    ) -> None:
        speed, _, speed_valid = self._validate_vertical_speed(
            now_s=now_s,
            vertical_speed_m_s=vertical_speed_m_s,
            sample_time_s=vertical_speed_sample_time_s,
        )
        if not speed_valid or speed is None:
            raise ValueError("fresh vertical speed is required to start tracking")
        config = self._config_snapshot()
        self._active = True
        self._exit_requested = False
        self._completion_latched = False
        self._ready_to_track = False
        self._phase = TrackerPhase.TRACKING
        self._commit_deadline_s = None
        self._last_result = None
        self._frozen_result = None
        self._command_pitch_deg = 0.0
        self._last_pitch_update_s = None
        self._vertical_speed_setpoint_m_s = clamp(
            speed,
            -config.vertical_speed_max_m_s,
            config.vertical_speed_max_m_s,
        )
        self._last_vertical_speed_setpoint_update_s = now_s
        initial_depth_m = (
            None if self._latest_estimate is None else self._latest_estimate.depth_m
        )
        self._approach_initial_depth_m = initial_depth_m
        self._approach_start_depth_m = (
            None
            if initial_depth_m is None
            else initial_depth_m * _APPROACH_START_FRACTION
        )
        self._approach_closest_depth_m = initial_depth_m
        self._observation_valid = True
        self._log_rows = []
        self._log_started_at_s = None

    def stop_tracking(self, *, end_reason: str = "unknown") -> None:
        self._export_log(end_reason=end_reason)
        self._active = False
        self._exit_requested = False
        self._phase = TrackerPhase.TRACKING
        self._commit_deadline_s = None
        self._last_result = None
        self._frozen_result = None
        self._command_pitch_deg = 0.0
        self._last_pitch_update_s = None
        self._vertical_speed_setpoint_m_s = None
        self._last_vertical_speed_setpoint_update_s = None
        self._approach_initial_depth_m = None
        self._approach_start_depth_m = None
        self._approach_closest_depth_m = None
        self._observation_valid = False
        self._current_observation = None
        self._clear_acquisition()

    def update(
        self,
        *,
        now_s: float,
        vertical_speed_m_s: float | None = None,
        vertical_speed_sample_time_s: float | None = None,
    ) -> TrackerControlResult:
        config = self._config_snapshot()
        if not self._active:
            return self._safe_result(config, "tracker controller is inactive")

        if self._phase == TrackerPhase.COMMIT:
            if (
                self._commit_deadline_s is not None
                and now_s >= self._commit_deadline_s
            ):
                self._completion_latched = True
                self._exit_requested = True
                return self._record_result(
                    self._safe_result(config, "commit timeout"), now_s, config
                )
            if self._frozen_result is not None:
                return self._record_result(self._frozen_result, now_s, config)

        vertical_speed, vertical_speed_age_s, vertical_speed_valid = (
            self._validate_vertical_speed(
                now_s=now_s,
                vertical_speed_m_s=vertical_speed_m_s,
                sample_time_s=vertical_speed_sample_time_s,
            )
        )
        if not vertical_speed_valid or vertical_speed is None:
            self._exit_requested = True
            stale_result = replace(
                self._safe_result(config, "vertical speed is invalid or stale"),
                drone_vertical_speed_m_s=vertical_speed,
                drone_vertical_speed_age_s=vertical_speed_age_s,
                vertical_speed_setpoint_m_s=self._vertical_speed_setpoint_m_s,
            )
            return self._record_result(
                stale_result,
                now_s,
                config,
            )

        estimate = self._latest_estimate
        if not self._is_fresh_valid(estimate, now_s):
            self._exit_requested = True
            return self._record_result(
                self._safe_result(config, "target estimate is invalid or stale"),
                now_s,
                config,
            )
        if estimate is None:
            self._exit_requested = True
            return self._record_result(
                self._safe_result(config, "target estimate is unavailable"),
                now_s,
                config,
            )

        if not self._observation_valid:
            self._last_pitch_update_s = now_s
            self._last_vertical_speed_setpoint_update_s = now_s
            if self._last_result is not None:
                return self._record_result(self._last_result, now_s, config)
            return self._record_result(
                self._safe_result(config, "target estimate is temporarily invalid"),
                now_s,
                config,
            )

        target_pitch_deg = self._approach_pitch_target(estimate, config)
        self._command_pitch_deg = self._slew_pitch(
            config,
            now_s,
            target_pitch_deg=target_pitch_deg,
        )
        result = self._tracking_result(
            estimate,
            config,
            now_s=now_s,
            pitch_command_deg=self._command_pitch_deg,
            vertical_speed_m_s=vertical_speed,
            vertical_speed_age_s=vertical_speed_age_s,
            vertical_speed_valid=vertical_speed_valid,
        )
        if estimate.depth_m is not None and estimate.depth_m <= config.commit_depth_m:
            self._phase = TrackerPhase.COMMIT
            self._commit_deadline_s = now_s + config.commit_s
            result = replace(result, phase=TrackerPhase.COMMIT)
            self._frozen_result = result
        self._last_result = result
        return self._record_result(result, now_s, config)

    def on_parameter_changed(self, name: str, value: object) -> None:
        field = _PARAMETER_FIELDS.get(name)
        if field is None:
            return
        with self._config_lock:
            try:
                self._config = replace(self._config, **{field: value})
            except (TypeError, ValueError) as exc:
                log.warning("Rejected tracker parameter update {}={}: {}", name, value, exc)

    def _tracking_result(
        self,
        estimate: TargetEstimate,
        config: TrackerConfig,
        *,
        now_s: float,
        pitch_command_deg: float,
        vertical_speed_m_s: float | None,
        vertical_speed_age_s: float | None,
        vertical_speed_valid: bool,
    ) -> TrackerControlResult:
        if estimate.error_x is None or estimate.error_y is None:
            raise ValueError("valid target estimate is missing center errors")
        error_x = self._deadband(estimate.error_x, config.deadband)
        error_y = self._deadband(estimate.error_y, config.deadband)
        yaw_rate = clamp(
            config.yaw_kp * error_x,
            -config.yaw_max_dps,
            config.yaw_max_dps,
        )
        if not vertical_speed_valid or vertical_speed_m_s is None:
            raise ValueError("tracking result requires valid vertical speed")
        vertical_speed_requested = (
            config.throttle_kp / config.vertical_speed_kd * error_y
        )
        vertical_speed_target = clamp(
            vertical_speed_requested,
            -config.vertical_speed_max_m_s,
            config.vertical_speed_max_m_s,
        )
        vertical_speed_setpoint = self._slew_vertical_speed_setpoint(
            config,
            now_s,
            target_m_s=vertical_speed_target,
        )
        vertical_speed_error = vertical_speed_setpoint - vertical_speed_m_s
        throttle_visual_correction = (
            config.vertical_speed_kd * vertical_speed_setpoint
        )
        throttle_damping_correction = (
            -config.vertical_speed_kd * vertical_speed_m_s
        )
        throttle_correction = clamp(
            config.vertical_speed_kd * vertical_speed_error,
            -config.throttle_max_rc,
            config.throttle_max_rc,
        )
        mapper = BetaflightRcMapper(
            yaw_rate_full_stick_dps=config.yaw_stick_rate_dps
        )
        pitch_rc = mapper.angle_to_rc(
            pitch_command_deg,
            angle_limit_deg=config.angle_limit_deg,
            sign=-1.0,
        )
        hover_fraction = (config.hover_baseline_rc - RC_MIN) / (RC_MAX - RC_MIN)
        throttle_ff = RC_MIN + (RC_MAX - RC_MIN) * hover_fraction / max(
            math.cos(math.radians(pitch_command_deg)),
            0.35,
        )
        channels = self._channels(
            pitch=pitch_rc,
            throttle=round(throttle_ff + throttle_correction),
            yaw=mapper.yaw_rate_to_rc(yaw_rate),
        )
        return TrackerControlResult(
            channels=channels,
            phase=TrackerPhase.TRACKING,
            error_x=estimate.error_x,
            error_y=estimate.error_y,
            pitch_command_deg=pitch_command_deg,
            yaw_rate_dps=yaw_rate,
            drone_vertical_speed_m_s=vertical_speed_m_s,
            drone_vertical_speed_age_s=vertical_speed_age_s,
            drone_vertical_speed_valid=vertical_speed_valid,
            vertical_speed_requested_m_s=vertical_speed_requested,
            vertical_speed_target_m_s=vertical_speed_target,
            vertical_speed_setpoint_m_s=vertical_speed_setpoint,
            vertical_speed_error_m_s=vertical_speed_error,
            throttle_visual_correction_rc=throttle_visual_correction,
            throttle_damping_correction_rc=throttle_damping_correction,
            throttle_correction_rc=throttle_correction,
            valid=True,
        )

    def _approach_pitch_target(
        self,
        estimate: TargetEstimate,
        config: TrackerConfig,
    ) -> float:
        """Schedule pitch from cruise to terminal using closest observed depth."""
        if estimate.depth_m is None:
            return config.pitch_deg

        if self._approach_initial_depth_m is None:
            self._approach_initial_depth_m = estimate.depth_m
            self._approach_start_depth_m = (
                estimate.depth_m * _APPROACH_START_FRACTION
            )
            self._approach_closest_depth_m = estimate.depth_m
        else:
            closest_depth_m = self._approach_closest_depth_m
            self._approach_closest_depth_m = (
                estimate.depth_m
                if closest_depth_m is None
                else min(closest_depth_m, estimate.depth_m)
            )

        start_depth_m = self._approach_start_depth_m
        closest_depth_m = self._approach_closest_depth_m
        if start_depth_m is None or closest_depth_m is None:
            return config.pitch_deg

        transition_span_m = start_depth_m - config.commit_depth_m
        if transition_span_m <= 0:
            return config.pitch_deg

        progress = clamp(
            (start_depth_m - closest_depth_m) / transition_span_m,
            0.0,
            1.0,
        )
        smooth_progress = (
            6.0 * progress**5 - 15.0 * progress**4 + 10.0 * progress**3
        )
        return config.pitch_deg + (
            _APPROACH_TERMINAL_PITCH_DEG - config.pitch_deg
        ) * smooth_progress

    def _slew_pitch(
        self,
        config: TrackerConfig,
        now_s: float,
        *,
        target_pitch_deg: float,
    ) -> float:
        if self._last_pitch_update_s is None:
            self._last_pitch_update_s = now_s
            return self._command_pitch_deg

        dt_s = max(0.0, now_s - self._last_pitch_update_s)
        self._last_pitch_update_s = now_s
        maximum_step = config.pitch_rate_deg_s * dt_s
        target = target_pitch_deg
        if self._command_pitch_deg < target:
            return min(target, self._command_pitch_deg + maximum_step)
        if self._command_pitch_deg > target:
            return max(target, self._command_pitch_deg - maximum_step)
        return self._command_pitch_deg

    def _slew_vertical_speed_setpoint(
        self,
        config: TrackerConfig,
        now_s: float,
        *,
        target_m_s: float,
    ) -> float:
        current = self._vertical_speed_setpoint_m_s
        previous_time_s = self._last_vertical_speed_setpoint_update_s
        if current is None or previous_time_s is None:
            current = 0.0
            previous_time_s = now_s

        maximum_step = config.vertical_speed_accel_m_s2 * max(
            0.0,
            now_s - previous_time_s,
        )
        if current < target_m_s:
            current = min(target_m_s, current + maximum_step)
        elif current > target_m_s:
            current = max(target_m_s, current - maximum_step)
        current = clamp(
            current,
            -config.vertical_speed_max_m_s,
            config.vertical_speed_max_m_s,
        )
        self._vertical_speed_setpoint_m_s = current
        self._last_vertical_speed_setpoint_update_s = now_s
        return current

    @staticmethod
    def _validate_vertical_speed(
        *,
        now_s: float,
        vertical_speed_m_s: float | None,
        sample_time_s: float | None,
    ) -> tuple[float | None, float | None, bool]:
        if vertical_speed_m_s is None or sample_time_s is None:
            return vertical_speed_m_s, None, False
        try:
            speed = float(vertical_speed_m_s)
            sample_time = float(sample_time_s)
        except (TypeError, ValueError):
            return None, None, False
        if not math.isfinite(speed) or not math.isfinite(sample_time):
            return speed, None, False
        age_s = now_s - sample_time
        return speed, age_s, 0.0 <= age_s <= _VERTICAL_SPEED_TIMEOUT_S

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
            vertical_speed_target_m_s=None,
            vertical_speed_setpoint_m_s=self._vertical_speed_setpoint_m_s,
            vertical_speed_error_m_s=None,
            throttle_visual_correction_rc=0.0,
            throttle_damping_correction_rc=0.0,
            throttle_correction_rc=0.0,
            valid=False,
            reason=reason,
        )

    def _record_result(
        self,
        result: TrackerControlResult,
        now_s: float,
        config: TrackerConfig,
    ) -> TrackerControlResult:
        if self._csv_path is None:
            return result
        if self._log_started_at_s is None:
            self._log_started_at_s = now_s

        observed = self._current_observation
        control = self._latest_estimate
        control_dx = None if control is None else control.error_x
        control_dy = None if control is None else control.error_y
        channels = result.channels
        row: dict[str, object] = {
            "sample_index": len(self._log_rows),
            "time_monotonic_ns": round(now_s * 1_000_000_000),
            "elapsed_s": now_s - self._log_started_at_s,
            "end_reason": "",
            "observed_frame_id": self._estimate_value(observed, "frame_id"),
            "observed_timestamp_ns": self._estimate_value(observed, "timestamp_ns"),
            "observed_valid": self._estimate_value(observed, "valid"),
            "observed_reason": self._estimate_value(observed, "reason"),
            "observed_depth_m": self._estimate_value(observed, "depth_m"),
            "observed_slant_range_m": self._estimate_value(
                observed, "slant_range_m"
            ),
            "observed_dx_norm": self._estimate_value(observed, "error_x"),
            "observed_dy_norm": self._estimate_value(observed, "error_y"),
            "observed_vx_m_s": self._estimate_value(observed, "vx_m_s"),
            "observed_vy_m_s": self._estimate_value(observed, "vy_m_s"),
            "control_frame_id": self._estimate_value(control, "frame_id"),
            "control_estimate_age_s": (
                None if control is None else now_s - control.received_at_s
            ),
            "control_depth_m": self._estimate_value(control, "depth_m"),
            "control_slant_range_m": self._estimate_value(control, "slant_range_m"),
            "control_dx_norm": control_dx,
            "control_dy_norm": control_dy,
            "control_dx_deadbanded": (
                None
                if control_dx is None
                else self._deadband(control_dx, config.deadband)
            ),
            "control_dy_deadbanded": (
                None
                if control_dy is None
                else self._deadband(control_dy, config.deadband)
            ),
            "control_vx_m_s": self._estimate_value(control, "vx_m_s"),
            "control_vy_m_s": self._estimate_value(control, "vy_m_s"),
            "phase": result.phase.value,
            "result_valid": result.valid,
            "result_reason": result.reason,
            "exit_requested": self._exit_requested,
            "completion_latched": self._completion_latched,
            "pitch_command_deg": result.pitch_command_deg,
            "yaw_rate_dps": result.yaw_rate_dps,
            "drone_vertical_speed_m_s": result.drone_vertical_speed_m_s,
            "drone_vertical_speed_age_s": result.drone_vertical_speed_age_s,
            "drone_vertical_speed_valid": result.drone_vertical_speed_valid,
            "vertical_speed_requested_m_s": result.vertical_speed_requested_m_s,
            "vertical_speed_target_m_s": result.vertical_speed_target_m_s,
            "vertical_speed_setpoint_m_s": result.vertical_speed_setpoint_m_s,
            "vertical_speed_error_m_s": result.vertical_speed_error_m_s,
            "throttle_visual_correction_rc": (
                result.throttle_visual_correction_rc
            ),
            "throttle_damping_correction_rc": (
                result.throttle_damping_correction_rc
            ),
            "throttle_correction_rc": result.throttle_correction_rc,
            "ch1_roll": channels[0],
            "ch2_pitch": channels[1],
            "ch3_throttle": channels[2],
            "ch4_yaw": channels[3],
            "ch5_arm": channels[4],
            "ch6_angle": channels[5],
            "ch7_aux3": channels[6],
            "ch8_aux4": channels[7],
            "trk_pitch_deg": config.pitch_deg,
            "trk_pitch_rate_deg_s": config.pitch_rate_deg_s,
            "trk_yaw_kp": config.yaw_kp,
            "trk_yaw_max_dps": config.yaw_max_dps,
            "trk_throttle_kp": config.throttle_kp,
            "trk_vertical_speed_kd": config.vertical_speed_kd,
            "trk_vertical_speed_max_m_s": config.vertical_speed_max_m_s,
            "trk_vertical_speed_accel_m_s2": config.vertical_speed_accel_m_s2,
            "trk_throttle_max_rc": config.throttle_max_rc,
            "trk_deadband": config.deadband,
            "trk_timeout_s": config.timeout_s,
            "trk_lock_frames": config.lock_frames,
            "trk_commit_depth_m": config.commit_depth_m,
            "trk_commit_s": config.commit_s,
            "bf_angle_limit_deg": config.angle_limit_deg,
            "hover_baseline_rc": config.hover_baseline_rc,
            "bf_yaw_rate_dps": config.yaw_stick_rate_dps,
        }
        self._log_rows.append(row)
        return result

    @staticmethod
    def _estimate_value(
        estimate: TargetEstimate | None,
        field: str,
    ) -> object:
        return None if estimate is None else getattr(estimate, field)

    def _export_log(self, *, end_reason: str) -> None:
        path = self._csv_path
        rows = self._log_rows
        self._log_rows = []
        self._log_started_at_s = None
        if path is None or not rows:
            return

        temporary_path = path.with_name(f".{path.name}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=TRACKER_CSV_HEADER)
                writer.writeheader()
                for row in rows:
                    row["end_reason"] = end_reason
                    writer.writerow(row)
            temporary_path.replace(path)
        except Exception as exc:
            log.exception("Failed to export tracker CSV {}: {}", path, exc)
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                log.exception("Failed to remove tracker CSV temporary file {}", temporary_path)

    @staticmethod
    def _channels(*, pitch: int, throttle: int, yaw: int) -> tuple[int, ...]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.ROLL] = RC_MID
        channels[RCChannel.PITCH] = int(clamp(pitch, RC_MIN, RC_MAX))
        channels[RCChannel.THROTTLE] = int(clamp(throttle, RC_MIN, RC_MAX))
        channels[RCChannel.YAW] = int(clamp(yaw, RC_MIN, RC_MAX))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        channels[RCChannel.AUX3] = RC_MIN
        channels[RCChannel.AUX4] = RC_MIN
        return tuple(channels)

    @staticmethod
    def _deadband(value: float, deadband: float) -> float:
        if abs(value) <= deadband:
            return 0.0
        return math.copysign(abs(value) - deadband, value)

    def _is_fresh_valid(
        self,
        estimate: TargetEstimate | None,
        now_s: float,
    ) -> bool:
        if (
            estimate is None
            or not estimate.valid
            or estimate.depth_m is None
            or estimate.error_x is None
            or estimate.error_y is None
        ):
            return False
        age_s = now_s - estimate.received_at_s
        return 0 <= age_s <= self._config_snapshot().timeout_s

    def _config_snapshot(self) -> TrackerConfig:
        with self._config_lock:
            return self._config

    def _clear_acquisition(self) -> None:
        self._valid_frame_count = 0
        self._ready_to_track = False
        self._last_observed_frame_id = None

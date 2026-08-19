"""Visual target-centering controller for the TRACK flight state."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, replace
from enum import StrEnum

from loguru import logger as log

from bt_app.common import NO_RC_CHANNELS
from bt_app.control.rc_mapper import BetaflightRcMapper, clamp
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey
from bt_app.services import TargetEstimate


class TrackerPhase(StrEnum):
    TRACKING = "tracking"
    COMMIT = "commit"


@dataclass(frozen=True, slots=True)
class TrackerConfig:
    pitch_deg: float
    yaw_kp: float
    yaw_max_dps: float
    throttle_kp: float
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
            self.yaw_kp,
            self.yaw_max_dps,
            self.throttle_kp,
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
        if self.yaw_kp < 0 or self.yaw_max_dps < 0:
            raise ValueError("tracker yaw values must be nonnegative")
        if self.throttle_kp < 0 or self.throttle_max_rc < 0:
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
            yaw_kp=parameters.get(ParameterKey.TRK_YAW_KP),
            yaw_max_dps=parameters.get(ParameterKey.TRK_YAW_MAX),
            throttle_kp=parameters.get(ParameterKey.TRK_THR_KP),
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
    throttle_correction_rc: float
    valid: bool
    reason: str | None = None


_PARAMETER_FIELDS = {
    ParameterKey.TRK_PITCH_DEG: "pitch_deg",
    ParameterKey.TRK_YAW_KP: "yaw_kp",
    ParameterKey.TRK_YAW_MAX: "yaw_max_dps",
    ParameterKey.TRK_THR_KP: "throttle_kp",
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

    def __init__(self, parameters: Parameters) -> None:
        self._config_lock = threading.Lock()
        self._config = TrackerConfig.from_parameters(parameters)
        self._latest_estimate: TargetEstimate | None = None
        self._last_observed_frame_id: int | None = None
        self._last_command_frame_id: int | None = None
        self._valid_frame_count = 0
        self._ready_to_track = False
        self._active = False
        self._exit_requested = False
        self._completion_latched = False
        self._phase = TrackerPhase.TRACKING
        self._commit_deadline_s: float | None = None
        self._last_result: TrackerControlResult | None = None
        self._frozen_result: TrackerControlResult | None = None
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

    def observe(
        self,
        estimate: TargetEstimate | None,
        *,
        now_s: float,
        mode_selected: bool,
    ) -> bool:
        """Observe one App-loop snapshot and update readiness/exit state."""
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
                self._latest_estimate = estimate
                self._exit_requested = True
                return False
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

    def start_tracking(self) -> None:
        self._active = True
        self._exit_requested = False
        self._completion_latched = False
        self._ready_to_track = False
        self._phase = TrackerPhase.TRACKING
        self._commit_deadline_s = None
        self._last_command_frame_id = None
        self._last_result = None
        self._frozen_result = None

    def stop_tracking(self) -> None:
        self._active = False
        self._exit_requested = False
        self._phase = TrackerPhase.TRACKING
        self._commit_deadline_s = None
        self._last_command_frame_id = None
        self._last_result = None
        self._frozen_result = None
        self._clear_acquisition()

    def update(self, *, now_s: float) -> TrackerControlResult:
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
                return self._safe_result(config, "commit timeout")
            if self._frozen_result is not None:
                return self._frozen_result

        estimate = self._latest_estimate
        if not self._is_fresh_valid(estimate, now_s):
            self._exit_requested = True
            return self._safe_result(config, "target estimate is invalid or stale")
        if estimate is None:
            self._exit_requested = True
            return self._safe_result(config, "target estimate is unavailable")
        if (
            estimate.frame_id == self._last_command_frame_id
            and self._last_result is not None
        ):
            return self._last_result

        result = self._tracking_result(estimate, config)
        self._last_command_frame_id = estimate.frame_id
        if estimate.depth_m is not None and estimate.depth_m <= config.commit_depth_m:
            self._phase = TrackerPhase.COMMIT
            self._commit_deadline_s = now_s + config.commit_s
            result = replace(result, phase=TrackerPhase.COMMIT)
            self._frozen_result = result
        self._last_result = result
        return result

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
        throttle_correction = clamp(
            config.throttle_kp * error_y,
            -config.throttle_max_rc,
            config.throttle_max_rc,
        )
        mapper = BetaflightRcMapper(
            yaw_rate_full_stick_dps=config.yaw_stick_rate_dps
        )
        pitch_rc = mapper.angle_to_rc(
            config.pitch_deg,
            angle_limit_deg=config.angle_limit_deg,
        )
        hover_fraction = (config.hover_baseline_rc - RC_MIN) / (RC_MAX - RC_MIN)
        throttle_ff = RC_MIN + (RC_MAX - RC_MIN) * hover_fraction / max(
            math.cos(math.radians(config.pitch_deg)),
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
            pitch_command_deg=config.pitch_deg,
            yaw_rate_dps=yaw_rate,
            throttle_correction_rc=throttle_correction,
            valid=True,
        )

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
            throttle_correction_rc=0.0,
            valid=False,
            reason=reason,
        )

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

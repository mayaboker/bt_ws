"""Isolated visual TRACK controller for the slant-intercept design."""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

from bt_app.common import NO_RC_CHANNELS
from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.estimators import GlideObservation
from bt_app.glide_diagnostic_recorder import (
    GlideDiagnosticRecorder,
    GlideDiagnosticSample,
    NullGlideDiagnosticRecorder,
)
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey


VARIO_STALE_TIMEOUT_S = 0.25
VISUAL_HOLD_TIMEOUT_S = 0.25
YAW_INTEGRAL_OUTPUT_LIMIT_DPS = 3.0
EDGE_CLIPPED_REASON = "bounding box clipped by image edge"
EDGE_REASON_PREFIX = "bounding box clipped by "
EDGE_COMMIT_MAX_HORIZONTAL_ERROR = 0.15
EDGE_COMMIT_MAX_DEPTH_M = 2.0
EDGE_RECOVERY_VX_M_S = 0.5


class GlidePhase(str, Enum):
    """Lifecycle of one guarded visual-intercept attempt."""

    IDLE = "idle"
    ACQUIRE = "acquire"
    TRACK = "track"
    COMMIT = "commit"
    ABORTED = "aborted"
    COMMIT_TIMEOUT = "commit_timeout"


@dataclass(frozen=True)
class GlideControlResult:
    channels: tuple[int, ...]
    frame_id: int | None
    vx_desired_m_s: float
    vx_measured_m_s: float | None
    vy_desired_m_s: float
    vy_measured_m_s: float
    pitch_feedforward_deg: float
    pitch_feedback_deg: float
    pitch_command_deg: float
    yaw_rate_dps: float
    throttle_correction_rc: float
    forward_feedback_active: bool
    pitch_saturated: bool
    throttle_saturated: bool
    valid: bool
    reason: str | None = None
    phase: GlidePhase = GlidePhase.IDLE
    abort_reason: str | None = None


@dataclass(frozen=True)
class GlideAircraftState:
    altitude_m: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float


class GlideController:
    """Own acquisition, visual tracking, commit, and abort phases.

    New visual frames update depth-derived forward speed and the forward PI.
    New vario timestamps update the vertical PI. Duplicate application cycles
    hold both corrections. The class is intentionally isolated from ``App`` and
    the flight state machine.  COMMIT freezes the last valid command so a
    transient visual loss at the opening cannot reverse the intercept.
    """

    def __init__(
        self,
        params: Any,
        *,
        max_vertical_speed_m_s: float = 3.0,
        center_deadband: float = 0.05,
        acquisition_error_max: float = 0.40,
        lock_frame_count: int = 2,
        commit_depth_m: float = 1.0,
        commit_timeout_s: float = 1.0,
        diagnostic_enabled: bool = False,
        diagnostic_path: str = "logs/glide_control.csv",
        diagnostic_flush_interval_s: float = 1.0,
        diagnostic_queue_size: int = 3000,
    ) -> None:
        self.params = params
        self._max_vertical_speed = float(max_vertical_speed_m_s)
        self._center_deadband = float(center_deadband)
        self._acquisition_error_max = float(acquisition_error_max)
        self._lock_frame_count = int(lock_frame_count)
        self._commit_depth_m = float(commit_depth_m)
        self._commit_timeout_s = float(commit_timeout_s)
        self._diagnostic_recorder = (
            GlideDiagnosticRecorder(
                diagnostic_path,
                flush_interval_s=diagnostic_flush_interval_s,
                queue_size=diagnostic_queue_size,
            )
            if diagnostic_enabled
            else NullGlideDiagnosticRecorder()
        )
        if self._lock_frame_count <= 0:
            raise ValueError("lock_frame_count must be positive")
        if self._commit_depth_m <= 0.0 or self._commit_timeout_s <= 0.0:
            raise ValueError("commit limits must be positive")
        if not self._center_deadband < self._acquisition_error_max <= 1.0:
            raise ValueError(
                "acquisition_error_max must be greater than center_deadband "
                "and no greater than 1"
            )
        self._load_parameters()
        self._mapper = BetaflightRcMapper(
            yaw_rate_full_stick_dps=self._bf_yaw_rate,
        )
        self.reset()
        params.on_parameter_changed.subscribe(self.on_parameter_changed)

    def _load_parameters(self) -> None:
        get = self.params.get
        self._baseline = float(get(ParameterKey.HOV_BASELINE))
        self._pitch_ff_at_max = float(get(ParameterKey.GLIDE_PITCH_FF))
        self._pitch_max = abs(float(get(ParameterKey.GLIDE_PITCH_MAX)))
        self._vx_kp = float(get(ParameterKey.GLIDE_VX_KP))
        self._vx_ki = float(get(ParameterKey.GLIDE_VX_KI))
        self._vy_kp = float(get(ParameterKey.GLIDE_VY_KP))
        self._vy_ki = float(get(ParameterKey.GLIDE_VY_KI))
        self._vy_output_limit = abs(float(get(ParameterKey.GLIDE_VY_OUT)))
        self._yaw_kp = float(get(ParameterKey.GLIDE_YAW_KP))
        self._yaw_ki = float(get(ParameterKey.GLIDE_YAW_KI))
        self._yaw_max = abs(float(get(ParameterKey.GLIDE_YAW_MAX)))
        self._yaw_deadband = abs(float(get(ParameterKey.GLIDE_YAW_DB)))
        self._yaw_slew = abs(float(get(ParameterKey.GLIDE_YAW_SLEW)))
        self._center_ky = float(get(ParameterKey.GLIDE_CENTER_KY))
        self._depth_alpha = float(get(ParameterKey.GLIDE_DEPTH_EMA))
        self._angle_limit = abs(float(get(ParameterKey.BF_ANGLE_LIMIT)))
        self._bf_yaw_rate = float(get(ParameterKey.BF_YAW_RATE))

    def reset(self, *_args: Any, **_kwargs: Any) -> None:
        """Return to IDLE and clear the complete intercept attempt."""
        self.phase = GlidePhase.IDLE
        self.abort_reason: str | None = None
        self._acquisition_count = 0
        self._acquisition_frame_id: int | None = None
        self._commit_started_at_s: float | None = None
        self._frozen_result: GlideControlResult | None = None
        self._last_valid_result: GlideControlResult | None = None
        self._reset_control_state()

    def _reset_control_state(self) -> None:
        self._last_frame_id: int | None = None
        self._last_depth_m: float | None = None
        self._last_depth_time_s: float | None = None
        self._vx_window: deque[float] = deque(maxlen=3)
        self._vx_measured: float | None = None
        self._vx_integral = 0.0
        self._pitch_feedback = 0.0
        self._pitch_feedback_saturated = False
        self._last_vario_time_s: float | None = None
        self._vy_integral = 0.0
        self._throttle_correction = 0.0
        self._yaw_rate_command = 0.0
        self._last_yaw_update_s: float | None = None
        self._last_yaw_control_s: float | None = None
        self._last_yaw_error = 0.0
        self._yaw_integral = 0.0
        self._last_guidance_observation: GlideObservation | None = None

    @property
    def ready_to_engage(self) -> bool:
        return (
            self.phase == GlidePhase.ACQUIRE
            and self._acquisition_count >= self._lock_frame_count
        )

    @property
    def acquisition_count(self) -> int:
        return self._acquisition_count

    def begin_acquisition(self) -> None:
        """Start counting distinct, consecutive, centered visual frames."""
        self.reset()
        self.phase = GlidePhase.ACQUIRE

    def observe_acquisition(self, observation: GlideObservation) -> bool:
        """Consume one observation and return whether the lock gate is ready.

        Repeated application cycles for the same camera frame neither advance
        nor reset the gate.  A new invalid or off-center frame resets the
        consecutive count.
        """
        if self.phase != GlidePhase.ACQUIRE:
            return False
        if observation.frame_id == self._acquisition_frame_id:
            return self.ready_to_engage
        self._acquisition_frame_id = observation.frame_id
        centered = (
            observation.valid
            and observation.frame_id is not None
            and observation.ex is not None
            and observation.ey is not None
            and math.isfinite(float(observation.ex))
            and math.isfinite(float(observation.ey))
            and math.hypot(
                float(observation.ex), float(observation.ey)
            ) <= self._acquisition_error_max
        )
        self._acquisition_count = self._acquisition_count + 1 if centered else 0
        return self.ready_to_engage

    def engage(self) -> bool:
        """Enter TRACK only after the acquisition gate has completed."""
        if not self.ready_to_engage:
            return False
        self._reset_control_state()
        self.phase = GlidePhase.TRACK
        self._diagnostic_recorder.start()
        return True

    def close_attempt(self) -> None:
        """Drain diagnostics and clear controller state after leaving GLIDE."""
        self._diagnostic_recorder.stop()
        self.reset()

    def stop(self) -> None:
        """Shutdown fallback for an active or partially initialized attempt."""
        self._diagnostic_recorder.stop()

    def abort(self, reason: str) -> None:
        """Abort an attempt; COMMIT deliberately ignores ordinary aborts."""
        if self.phase == GlidePhase.COMMIT:
            return
        self.abort_reason = reason
        self.phase = GlidePhase.ABORTED
        self._reset_control_state()

    def update(
        self,
        observation: GlideObservation,
        *,
        vertical_speed_m_s: float,
        vertical_speed_received_at_s: float,
        aircraft_state: GlideAircraftState | None = None,
        now_s: float | None = None,
    ) -> GlideControlResult:
        """Advance control and record exactly one diagnostic sample."""
        result = self._update_control(
            observation,
            vertical_speed_m_s=vertical_speed_m_s,
            vertical_speed_received_at_s=vertical_speed_received_at_s,
            now_s=now_s,
        )
        state = aircraft_state or GlideAircraftState(0.0, 0.0, 0.0, 0.0)
        self._record_diagnostic(observation, result, state)
        return result

    def _record_diagnostic(
        self,
        observation: GlideObservation,
        result: GlideControlResult,
        aircraft_state: GlideAircraftState,
    ) -> None:
        self._diagnostic_recorder.record(
            GlideDiagnosticSample(
                time.monotonic_ns(), result.phase.value, result.frame_id,
                result.valid, result.reason, result.abort_reason or self.abort_reason,
                observation.ex, observation.ey, result.vx_desired_m_s,
                result.vx_measured_m_s, result.vy_desired_m_s,
                result.vy_measured_m_s, aircraft_state.altitude_m,
                observation.depth_m, aircraft_state.roll_deg,
                aircraft_state.pitch_deg, aircraft_state.yaw_deg,
                result.yaw_rate_dps, int(result.channels[RCChannel.YAW]),
                int(result.channels[RCChannel.THROTTLE]),
            )
        )

    def _update_control(
        self,
        observation: GlideObservation,
        *,
        vertical_speed_m_s: float,
        vertical_speed_received_at_s: float,
        now_s: float | None = None,
    ) -> GlideControlResult:
        """Advance TRACK/COMMIT and return the command for this control cycle.

        TRACK validates visual and vario inputs, updates the depth/vertical
        loops, and enters COMMIT at the configured centered depth.  COMMIT
        replays the frozen entry command until its deadline; the following
        cycle returns neutral with ``COMMIT_TIMEOUT`` so the state machine can
        return to altitude hold.
        """
        now = time.monotonic() if now_s is None else float(now_s)
        if self.phase == GlidePhase.COMMIT:
            if now - float(self._commit_started_at_s) < self._commit_timeout_s:
                return self._frozen_result  # type: ignore[return-value]
            self.phase = GlidePhase.COMMIT_TIMEOUT
            return self._neutral_result(None, "commit timeout")
        if self.phase != GlidePhase.TRACK:
            return self._neutral_result(None, f"controller phase is {self.phase.value}")
        allow_commit = observation.valid
        if not observation.valid:
            clipped_reason = observation.reason or ""
            edge_clipped = (
                clipped_reason == EDGE_CLIPPED_REASON
                or clipped_reason.startswith(EDGE_REASON_PREFIX)
            )
            side_clipped = edge_clipped and (
                "left" in clipped_reason or "right" in clipped_reason
            )
            last_visual = self._last_guidance_observation
            edge_commit_allowed = (
                edge_clipped
                and not side_clipped
                and self._last_valid_result is not None
                and last_visual is not None
                and last_visual.ex is not None
                and last_visual.depth_m is not None
                and abs(float(last_visual.ex)) <= EDGE_COMMIT_MAX_HORIZONTAL_ERROR
                and float(last_visual.depth_m) <= EDGE_COMMIT_MAX_DEPTH_M
            )
            if edge_commit_allowed:
                self.phase = GlidePhase.COMMIT
                self._commit_started_at_s = now
                edge_yaw = 0.0
                channels = list(self._last_valid_result.channels)
                channels[RCChannel.YAW] = self._mapper.yaw_rate_to_rc(edge_yaw)
                self._frozen_result = replace(
                    self._last_valid_result,
                    channels=tuple(channels),
                    yaw_rate_dps=edge_yaw,
                    phase=GlidePhase.COMMIT,
                    reason=f"edge commit: {clipped_reason}",
                )
                return self._frozen_result
            cached = self._last_guidance_observation
            cached_at = None if cached is None else cached.received_at_s
            if (
                cached is None
                or cached_at is None
                or now - float(cached_at) > VISUAL_HOLD_TIMEOUT_S
            ):
                return self._abort_result(
                    observation.frame_id,
                    observation.reason or "invalid observation",
                )
            ex = cached.ex if observation.ex is None else observation.ex
            ey = cached.ey if observation.ey is None else observation.ey
            observation = replace(
                cached,
                ex=ex,
                ey=ey,
                centering_error=(
                    None if ex is None or ey is None else math.hypot(ex, ey)
                ),
                age_s=now - float(cached_at),
                reason=f"visual hold: {observation.reason or 'invalid observation'}",
            )
            if edge_clipped:
                observation = replace(
                    observation,
                    vx_geometry_m_s=min(
                        observation.vx_geometry_m_s, EDGE_RECOVERY_VX_M_S
                    ),
                )
        elif (
            self._last_guidance_observation is None
            or observation.frame_id != self._last_guidance_observation.frame_id
        ):
            self._last_guidance_observation = observation
        if observation.frame_id is None:
            return self._abort_result(None, "visual frame unavailable")
        required = (
            now,
            observation.received_at_s,
            observation.depth_m,
            observation.ex,
            observation.ey,
            observation.vx_geometry_m_s,
            observation.vy_geometry_m_s,
            vertical_speed_m_s,
            vertical_speed_received_at_s,
        )
        if any(value is None or not math.isfinite(float(value)) for value in required):
            return self._abort_result(observation.frame_id, "non-finite controller input")
        if float(observation.depth_m) <= 0.0:
            return self._abort_result(observation.frame_id, "non-positive depth")

        vario_age = now - float(vertical_speed_received_at_s)
        if vario_age < 0.0 or vario_age > VARIO_STALE_TIMEOUT_S:
            return self._abort_result(observation.frame_id, "vertical speed stale")

        new_frame = observation.frame_id != self._last_frame_id
        feedback_active = self._vx_measured is not None
        if new_frame:
            feedback_active = self._update_forward(observation)

        vx_desired = float(observation.vx_geometry_m_s)
        pitch_ff = self._pitch_ff_at_max * vx_desired / 15.0
        pitch_unsaturated = pitch_ff + self._pitch_feedback
        pitch = self._clamp(pitch_unsaturated, -self._pitch_max, self._pitch_max)
        pitch_saturated = self._pitch_feedback_saturated or not math.isclose(
            pitch, pitch_unsaturated
        )

        ey = self._deadband(float(observation.ey))
        vy_desired = self._clamp(
            float(observation.vy_geometry_m_s) + self._center_ky * ey,
            -self._max_vertical_speed,
            self._max_vertical_speed,

        )
        throttle_saturated = self._update_vertical(
            vy_desired,
            float(vertical_speed_m_s),
            float(vertical_speed_received_at_s),
        )
        yaw_error = self._deadband(float(observation.ex), self._yaw_deadband)
        yaw_target = self._update_yaw_pi(yaw_error, now)
        yaw_rate = self._slew_yaw(yaw_target, now)
        channels = self._make_channels(pitch, yaw_rate, self._throttle_correction)
        result = GlideControlResult(
            tuple(channels), observation.frame_id, vx_desired, self._vx_measured,
            vy_desired, float(vertical_speed_m_s), pitch_ff,
            self._pitch_feedback, pitch, yaw_rate, self._throttle_correction,
            feedback_active, pitch_saturated, throttle_saturated, True,
            reason=observation.reason,
            phase=self.phase,
        )
        self._last_valid_result = result
        if (
            allow_commit
            and
            float(observation.depth_m) <= self._commit_depth_m
            and abs(float(observation.ex)) <= self._center_deadband
            and abs(float(observation.ey)) <= self._center_deadband
        ):
            self.phase = GlidePhase.COMMIT
            self._commit_started_at_s = now
            self._frozen_result = replace(result, phase=GlidePhase.COMMIT)
            return self._frozen_result
        return result

    def _update_forward(self, observation: GlideObservation) -> bool:
        depth = float(observation.depth_m)
        received_at = float(observation.received_at_s)
        feedback_active = False
        if self._last_depth_m is not None and self._last_depth_time_s is not None:
            dt = received_at - self._last_depth_time_s
            if dt > 0.0:
                raw = -(depth - self._last_depth_m) / dt
                self._vx_window.append(raw)
                median = statistics.median(self._vx_window)
                self._vx_measured = (
                    median if self._vx_measured is None
                    else self._depth_alpha * median + (1.0 - self._depth_alpha) * self._vx_measured
                )
                error = float(observation.vx_geometry_m_s) - self._vx_measured
                pitch_ff = (
                    self._pitch_ff_at_max
                    * float(observation.vx_geometry_m_s)
                    / 15.0
                )
                correction, self._vx_integral, saturated = self._pi(
                    error, dt, self._vx_integral,
                    -self._pitch_max - pitch_ff,
                    self._pitch_max - pitch_ff,
                    output_sign=-1.0, kp=self._vx_kp, ki=self._vx_ki,
                )
                self._pitch_feedback = correction
                self._pitch_feedback_saturated = saturated
                feedback_active = True
        self._last_depth_m = depth
        self._last_depth_time_s = received_at
        self._last_frame_id = observation.frame_id
        return feedback_active

    def _update_vertical(self, desired: float, measured: float, sample_time: float) -> bool:
        if self._last_vario_time_s is None:
            self._last_vario_time_s = sample_time
            error = desired - measured
            correction = self._vy_kp * error
            self._throttle_correction = self._clamp(
                correction,
                -self._vy_output_limit,
                self._vy_output_limit,
            )
            return not math.isclose(correction, self._throttle_correction)
        if sample_time <= self._last_vario_time_s:
            return abs(self._throttle_correction) >= self._vy_output_limit
        dt = sample_time - self._last_vario_time_s
        self._last_vario_time_s = sample_time
        self._throttle_correction, self._vy_integral, saturated = self._pi(
            desired - measured, dt, self._vy_integral,
            -self._vy_output_limit, self._vy_output_limit,
            output_sign=1.0, kp=self._vy_kp, ki=self._vy_ki,
        )
        return saturated

    @staticmethod
    def _pi(error, dt, integral, lower, upper, *, output_sign, kp, ki):
        candidate_integral = integral + error * max(0.0, dt)
        candidate = output_sign * (kp * error + ki * candidate_integral)
        output = max(lower, min(upper, candidate))
        saturated = not math.isclose(candidate, output)
        deepens = saturated and (
            (candidate > upper and output_sign * error > 0)
            or (candidate < lower and output_sign * error < 0)
        )
        if not deepens:
            integral = candidate_integral
            output = max(lower, min(upper, output_sign * (kp * error + ki * integral)))
        return output, integral, saturated

    def _abort_result(self, frame_id: int | None, reason: str) -> GlideControlResult:
        self.abort(reason)
        return self._neutral_result(frame_id, reason)

    def _neutral_result(self, frame_id: int | None, reason: str) -> GlideControlResult:
        channels = self._make_channels(0.0, 0.0, 0.0)
        return GlideControlResult(tuple(channels), frame_id, 0.0, None, 0.0, 0.0,
                                  0.0, 0.0, 0.0, 0.0, 0.0, False, False,
                                  False, False, reason, self.phase,
                                  self.abort_reason)

    def _make_channels(self, pitch_deg: float, yaw_rate: float, throttle_correction: float) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.PITCH] = self._mapper.angle_to_rc(
            pitch_deg, angle_limit_deg=self._angle_limit, sign=-1.0
        )
        channels[RCChannel.YAW] = self._mapper.yaw_rate_to_rc(yaw_rate)
        channels[RCChannel.THROTTLE] = int(self._clamp(
            round(self._baseline + throttle_correction), RC_MIN, RC_MAX
        ))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        return channels

    def _deadband(self, value: float, deadband: float | None = None) -> float:
        threshold = self._center_deadband if deadband is None else deadband
        if abs(value) <= threshold:
            return 0.0
        return math.copysign(abs(value) - threshold, value)

    def _slew_yaw(self, target: float, now_s: float) -> float:
        if self._last_yaw_update_s is None or now_s <= self._last_yaw_update_s:
            self._last_yaw_update_s = now_s
            self._yaw_rate_command = target
            return target
        maximum_change = self._yaw_slew * (now_s - self._last_yaw_update_s)
        self._last_yaw_update_s = now_s
        self._yaw_rate_command += self._clamp(
            target - self._yaw_rate_command, -maximum_change, maximum_change
        )
        return self._yaw_rate_command

    def _update_yaw_pi(self, error: float, now_s: float) -> float:
        dt = 0.0
        if self._last_yaw_control_s is not None:
            dt = max(0.0, now_s - self._last_yaw_control_s)
        self._last_yaw_control_s = now_s

        if error * self._last_yaw_error < 0.0:
            self._yaw_integral *= 0.25
        if error == 0.0:
            self._yaw_integral *= max(0.0, 1.0 - 2.0 * dt)

        candidate_integral = self._yaw_integral + error * dt
        if self._yaw_ki > 0.0:
            integral_limit = YAW_INTEGRAL_OUTPUT_LIMIT_DPS / self._yaw_ki
            candidate_integral = self._clamp(
                candidate_integral, -integral_limit, integral_limit
            )
        else:
            candidate_integral = 0.0

        candidate = self._yaw_kp * error + self._yaw_ki * candidate_integral
        output = self._clamp(candidate, -self._yaw_max, self._yaw_max)
        saturated_deeper = not math.isclose(candidate, output) and (
            (candidate > self._yaw_max and error > 0.0)
            or (candidate < -self._yaw_max and error < 0.0)
        )
        if not saturated_deeper:
            self._yaw_integral = candidate_integral
        self._last_yaw_error = error
        return output

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def on_parameter_changed(self, name: str, value: Any) -> None:
        del value
        supported = {
            ParameterKey.HOV_BASELINE, ParameterKey.GLIDE_PITCH_FF,
            ParameterKey.GLIDE_PITCH_MAX, ParameterKey.GLIDE_VX_KP,
            ParameterKey.GLIDE_VX_KI, ParameterKey.GLIDE_VY_KP,
            ParameterKey.GLIDE_VY_KI, ParameterKey.GLIDE_VY_OUT,
            ParameterKey.GLIDE_YAW_KP, ParameterKey.GLIDE_YAW_KI,
            ParameterKey.GLIDE_YAW_MAX,
            ParameterKey.GLIDE_YAW_DB,
            ParameterKey.GLIDE_YAW_SLEW,
            ParameterKey.GLIDE_CENTER_KY, ParameterKey.GLIDE_DEPTH_EMA,
            ParameterKey.BF_ANGLE_LIMIT, ParameterKey.BF_YAW_RATE,
        }
        if name in supported:
            self._load_parameters()
            self._mapper = BetaflightRcMapper(yaw_rate_full_stick_dps=self._bf_yaw_rate)

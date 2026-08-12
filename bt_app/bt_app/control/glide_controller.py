"""Isolated visual TRACK controller for the slant-intercept design."""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from bt_app.common import NO_RC_CHANNELS
from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.estimators import GlideObservation
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey


VARIO_STALE_TIMEOUT_S = 0.25


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


class GlideController:
    """Calculate TRACK RC commands without owning tracking or flight phases.

    New visual frames update depth-derived forward speed and the forward PI.
    New vario timestamps update the vertical PI. Duplicate application cycles
    hold both corrections. The class is intentionally isolated from ``App`` and
    the flight state machine until milestone 3.
    """

    def __init__(
        self,
        params: Any,
        *,
        max_vertical_speed_m_s: float = 3.0,
        center_deadband: float = 0.05,
    ) -> None:
        self.params = params
        self._max_vertical_speed = float(max_vertical_speed_m_s)
        self._center_deadband = float(center_deadband)
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
        self._yaw_max = abs(float(get(ParameterKey.GLIDE_YAW_MAX)))
        self._center_ky = float(get(ParameterKey.GLIDE_CENTER_KY))
        self._depth_alpha = float(get(ParameterKey.GLIDE_DEPTH_EMA))
        self._angle_limit = abs(float(get(ParameterKey.BF_ANGLE_LIMIT)))
        self._bf_yaw_rate = float(get(ParameterKey.BF_YAW_RATE))

    def reset(self, *_args: Any, **_kwargs: Any) -> None:
        """Clear filters, timestamps, PI integrals, and held corrections."""
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

    def update(
        self,
        observation: GlideObservation,
        *,
        vertical_speed_m_s: float,
        vertical_speed_received_at_s: float,
        now_s: float | None = None,
    ) -> GlideControlResult:
        """Return a typed TRACK command from visual and vario measurements."""
        now = time.monotonic() if now_s is None else float(now_s)
        if not observation.valid:
            return self._safe_result(observation.frame_id, observation.reason or "invalid observation")
        if observation.frame_id is None:
            return self._safe_result(None, "visual frame unavailable")
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
            return self._safe_result(observation.frame_id, "non-finite controller input")
        if float(observation.depth_m) <= 0.0:
            return self._safe_result(observation.frame_id, "non-positive depth")

        vario_age = now - float(vertical_speed_received_at_s)
        if vario_age < 0.0 or vario_age > VARIO_STALE_TIMEOUT_S:
            return self._safe_result(observation.frame_id, "vertical speed stale")

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
        yaw_rate = self._clamp(
            self._yaw_kp * self._deadband(float(observation.ex)),
            -self._yaw_max,
            self._yaw_max,
        )
        channels = self._make_channels(pitch, yaw_rate, self._throttle_correction)
        return GlideControlResult(
            tuple(channels), observation.frame_id, vx_desired, self._vx_measured,
            vy_desired, float(vertical_speed_m_s), pitch_ff,
            self._pitch_feedback, pitch, yaw_rate, self._throttle_correction,
            feedback_active, pitch_saturated, throttle_saturated, True,
        )

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
            return False
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

    def _safe_result(self, frame_id: int | None, reason: str) -> GlideControlResult:
        self.reset()
        channels = self._make_channels(0.0, 0.0, 0.0)
        return GlideControlResult(tuple(channels), frame_id, 0.0, None, 0.0, 0.0,
                                  0.0, 0.0, 0.0, 0.0, 0.0, False, False,
                                  False, False, reason)

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

    def _deadband(self, value: float) -> float:
        if abs(value) <= self._center_deadband:
            return 0.0
        return math.copysign(abs(value) - self._center_deadband, value)

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
            ParameterKey.GLIDE_YAW_KP, ParameterKey.GLIDE_YAW_MAX,
            ParameterKey.GLIDE_CENTER_KY, ParameterKey.GLIDE_DEPTH_EMA,
            ParameterKey.BF_ANGLE_LIMIT, ParameterKey.BF_YAW_RATE,
        }
        if name in supported:
            self._load_parameters()
            self._mapper = BetaflightRcMapper(yaw_rate_full_stick_dps=self._bf_yaw_rate)

"""Vertical-speed controller used while the state machine is in GLIDE."""

from __future__ import annotations

import time
from typing import Any, Callable

from loguru import logger as log

from bt_app.common import NO_RC_CHANNELS
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey
from bt_app.control.visual_range import TargetRangeEstimate, VisualRangeEstimator


VARIO_STALE_TIMEOUT_S = 0.25


class GlideController:
    """Control descent rate using Betaflight's measured vertical velocity.

    ``MSP_ALTITUDE`` reports vertical velocity with upward-positive sign.  The
    controller therefore uses a negative target while descending.  A PI
    correction is added to ``HOV_BASELINE``; altitude is used only to schedule
    the landing flare and confirm touchdown.

    The application runs faster than MSP altitude telemetry.  PI state is
    advanced only when ``altitude_sample_time_s`` changes, and the last command
    is held between fresh samples.  Stale telemetry freezes the integrator and
    returns throttle to the hover baseline.
    """

    def __init__(
        self,
        params: Any,
        *,
        visual_observation_supplier: Callable[[], Any | None] | None = None,
        visual_range_estimator: VisualRangeEstimator | None = None,
    ) -> None:
        self.params = params
        self._baseline = float(params.get(ParameterKey.HOV_BASELINE))
        self._descent_rate_m_s = abs(float(params.get(ParameterKey.GLIDE_DESC_RATE)))
        self._kp = float(params.get(ParameterKey.GLIDE_VEL_KP))
        self._ki = float(params.get(ParameterKey.GLIDE_VEL_KI))
        self._output_limit = abs(float(params.get(ParameterKey.GLIDE_OUT_LIMIT)))
        self._flare_altitude_m = float(params.get(ParameterKey.GLIDE_FLARE_ALT))
        self._flare_rate_m_s = abs(float(params.get(ParameterKey.GLIDE_FLARE_RATE)))
        self._land_altitude_m = float(params.get(ParameterKey.GLIDE_LAND_ALT))
        self._land_vertical_speed_m_s = float(params.get(ParameterKey.GLIDE_LAND_VS))
        self._land_confirm_s = float(params.get(ParameterKey.GLIDE_LAND_SEC))
        self._velocity_setpoint_m_s = 0.0
        self._integral = 0.0
        self._last_sample_time_s: float | None = None
        self._cached_correction = 0.0
        self._telemetry_stale = False
        self._land_candidate_since_s: float | None = None
        self._landed = False
        self._landed_event = False
        self._visual_observation_supplier = visual_observation_supplier
        self._visual_range_estimator = visual_range_estimator
        self._target_range = TargetRangeEstimate(
            None, None, None, False, "visual ranging disabled"
        )
        params.on_parameter_changed.subscribe(self.on_parameter_changed)

    @property
    def setpoint(self) -> float:
        """Return the active upward-positive vertical-speed setpoint."""
        return self._velocity_setpoint_m_s

    @property
    def velocity_setpoint_m_s(self) -> float:
        return self._velocity_setpoint_m_s

    @property
    def landed(self) -> bool:
        return self._landed

    @property
    def target_range(self) -> TargetRangeEstimate:
        return self._target_range

    @property
    def target_distance_m(self) -> float | None:
        return self._target_range.distance_m

    @property
    def target_raw_depth_m(self) -> float | None:
        return self._target_range.raw_depth_m

    def consume_landed_event(self) -> bool:
        if not self._landed_event:
            return False
        self._landed_event = False
        return True

    def reset(
        self,
        current_altitude: float,
        *,
        altitude_sample_time_s: float | None = None,
        vertical_speed_m_s: float = 0.0,
    ) -> None:
        """Reset PI and seed timing from the latest MSP altitude sample."""
        del vertical_speed_m_s
        self._velocity_setpoint_m_s = self._target_velocity(current_altitude)
        self._integral = 0.0
        self._last_sample_time_s = altitude_sample_time_s
        self._cached_correction = 0.0
        self._telemetry_stale = False
        self._land_candidate_since_s = None
        self._landed = False
        self._landed_event = False
        if self._visual_range_estimator is not None:
            self._target_range = self._visual_range_estimator.reset("GLIDE reset")

    def update(
        self,
        current_altitude: float,
        vertical_speed_m_s: float,
        altitude_sample_time_s: float | None = None,
    ) -> list[int]:
        """Return a complete RC command for the latest measured descent rate."""
        now_s = time.monotonic()
        self._update_visual_range()
        sample_time_s = now_s if altitude_sample_time_s is None else float(
            altitude_sample_time_s
        )
        fresh = now_s - sample_time_s <= VARIO_STALE_TIMEOUT_S
        self._velocity_setpoint_m_s = self._target_velocity(current_altitude)

        self._update_landing(
            current_altitude,
            vertical_speed_m_s,
            now_s,
            telemetry_fresh=fresh,
        )
        if self._landed:
            return self.make_disarm_channels()
        if not fresh:
            self._telemetry_stale = True
            self._cached_correction = 0.0
            return self.make_channels(0)

        if self._telemetry_stale:
            # Do not integrate across a telemetry outage.  Seed timing from
            # the first recovered sample and wait for the next fresh sample.
            self._telemetry_stale = False
            self._last_sample_time_s = sample_time_s
            return self.make_channels(0)

        if self._last_sample_time_s is None:
            self._last_sample_time_s = sample_time_s
        elif sample_time_s > self._last_sample_time_s:
            dt_s = sample_time_s - self._last_sample_time_s
            self._last_sample_time_s = sample_time_s
            self._cached_correction = self._update_pi(
                self._velocity_setpoint_m_s,
                float(vertical_speed_m_s),
                dt_s,
            )
        return self.make_channels(int(round(self._cached_correction)))

    def _update_visual_range(self) -> None:
        estimator = self._visual_range_estimator
        supplier = self._visual_observation_supplier
        if estimator is None or supplier is None:
            return
        try:
            observation = supplier()
        except Exception as exc:
            log.warning("Unable to read visual observation during GLIDE: {}", exc)
            self._target_range = estimator.reset("observation supplier failed")
            return
        if observation is None:
            self._target_range = estimator.reset("visual observation stale")
            return
        self._target_range = estimator.update(observation.detection)

    def _target_velocity(self, altitude_m: float) -> float:
        altitude_m = float(altitude_m)
        if altitude_m >= self._flare_altitude_m:
            return -self._descent_rate_m_s
        if altitude_m <= self._land_altitude_m:
            return -self._flare_rate_m_s
        span_m = self._flare_altitude_m - self._land_altitude_m
        if span_m <= 0.0:
            return -self._flare_rate_m_s
        fraction = (altitude_m - self._land_altitude_m) / span_m
        rate = self._flare_rate_m_s + fraction * (
            self._descent_rate_m_s - self._flare_rate_m_s
        )
        return -rate

    def _update_pi(self, target: float, measured: float, dt_s: float) -> float:
        error = target - measured
        candidate_integral = self._integral + error * max(0.0, dt_s)
        candidate_output = self._kp * error + self._ki * candidate_integral
        saturated_output = max(
            -self._output_limit,
            min(self._output_limit, candidate_output),
        )
        deepens_high_saturation = (
            candidate_output > self._output_limit and error > 0.0
        )
        deepens_low_saturation = (
            candidate_output < -self._output_limit and error < 0.0
        )
        if not (deepens_high_saturation or deepens_low_saturation):
            self._integral = candidate_integral
        output = self._kp * error + self._ki * self._integral
        return max(-self._output_limit, min(self._output_limit, output))

    def _update_landing(
        self,
        current_altitude: float,
        vertical_speed_m_s: float,
        now_s: float,
        *,
        telemetry_fresh: bool,
    ) -> None:
        candidate = (
            telemetry_fresh
            and float(current_altitude) <= self._land_altitude_m
            and abs(float(vertical_speed_m_s)) <= self._land_vertical_speed_m_s
        )
        if not candidate:
            self._land_candidate_since_s = None
            return
        if self._land_candidate_since_s is None:
            self._land_candidate_since_s = now_s
            return
        if now_s - self._land_candidate_since_s >= self._land_confirm_s:
            self._landed = True
            self._landed_event = True

    def make_channels(self, correction: int = 0) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS
        throttle = int(self._baseline + correction)
        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        return channels

    def make_disarm_channels(self) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.THROTTLE] = RC_MIN
        channels[RCChannel.ARM] = RC_MIN
        channels[RCChannel.ANGLE] = RC_MAX
        return channels

    def set_baseline(self, baseline: float) -> None:
        self._baseline = float(baseline)

    def on_parameter_changed(self, name: str, value: Any) -> None:
        log.info("Parameter changed: {} = {}", name, value)
        if name == ParameterKey.GLIDE_VEL_KP:
            self._kp = float(value)
        elif name == ParameterKey.GLIDE_VEL_KI:
            self._ki = float(value)
        elif name == ParameterKey.GLIDE_OUT_LIMIT:
            self._output_limit = abs(float(value))
        elif name == ParameterKey.GLIDE_DESC_RATE:
            self._descent_rate_m_s = abs(float(value))
        elif name == ParameterKey.GLIDE_FLARE_ALT:
            self._flare_altitude_m = float(value)
        elif name == ParameterKey.GLIDE_FLARE_RATE:
            self._flare_rate_m_s = abs(float(value))
        elif name == ParameterKey.GLIDE_LAND_ALT:
            self._land_altitude_m = float(value)
        elif name == ParameterKey.GLIDE_LAND_VS:
            self._land_vertical_speed_m_s = float(value)
        elif name == ParameterKey.GLIDE_LAND_SEC:
            self._land_confirm_s = float(value)
        elif name == ParameterKey.HOV_BASELINE:
            self._baseline = float(value)

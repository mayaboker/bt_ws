"""Requested velocity estimation for a two-dimensional glide path."""

from __future__ import annotations

import math
from dataclasses import dataclass

from bt_app.control.visual_range import TargetRangeEstimate


GEOMETRY_REL_TOL = 1e-9
GEOMETRY_ABS_TOL_M = 1e-9


@dataclass(frozen=True)
class GlideVelocityEstimate:
    """A horizontal/vertical velocity request in the target glide plane."""

    frame_id: int | None
    horizontal_distance_m: float | None
    vx_m_s: float
    vy_m_s: float
    achieved_speed_m_s: float
    limited: bool
    valid: bool
    reason: str | None = None


class GlideVelocityEstimator:
    """Point a velocity request at a target while limiting descent speed.

    ``vx`` is positive horizontally toward the target. ``vy`` follows the
    application's upward-positive convention and is therefore non-positive
    during descent. The supplied visual distance is treated as slant range.
    """

    def __init__(
        self,
        *,
        max_vertical_speed_m_s: float,
        target_speed_m_s: float = 15.0,
    ) -> None:
        self.max_vertical_speed_m_s = self._positive_finite(
            "max_vertical_speed_m_s", max_vertical_speed_m_s
        )
        self.target_speed_m_s = self._positive_finite(
            "target_speed_m_s", target_speed_m_s
        )
        self._estimate = self._invalid(None, "no estimate")

    @property
    def estimate(self) -> GlideVelocityEstimate:
        return self._estimate

    def reset(self, reason: str = "no estimate") -> GlideVelocityEstimate:
        self._estimate = self._invalid(None, reason)
        return self._estimate

    def update(
        self,
        altitude_m: float,
        range_estimate: TargetRangeEstimate | None,
    ) -> GlideVelocityEstimate:
        frame_id = None if range_estimate is None else range_estimate.frame_id
        if range_estimate is None:
            return self._set_invalid(frame_id, "range estimate unavailable")
        if not range_estimate.valid:
            reason = range_estimate.reason or "invalid range estimate"
            return self._set_invalid(frame_id, reason)

        altitude_m = float(altitude_m)
        range_m = range_estimate.distance_m
        if range_m is None:
            return self._set_invalid(frame_id, "range distance unavailable")
        range_m = float(range_m)
        if not math.isfinite(altitude_m):
            return self._set_invalid(frame_id, "non-finite altitude")
        if altitude_m < 0.0:
            return self._set_invalid(frame_id, "negative altitude")
        if not math.isfinite(range_m):
            return self._set_invalid(frame_id, "non-finite range")
        if range_m <= 0.0:
            return self._set_invalid(frame_id, "non-positive range")
        if range_m < altitude_m and not math.isclose(
            range_m,
            altitude_m,
            rel_tol=GEOMETRY_REL_TOL,
            abs_tol=GEOMETRY_ABS_TOL_M,
        ):
            return self._set_invalid(frame_id, "range shorter than altitude")

        horizontal_distance_m = math.sqrt(
            max(0.0, range_m * range_m - altitude_m * altitude_m)
        )
        direction_length_m = math.hypot(horizontal_distance_m, altitude_m)
        if direction_length_m == 0.0:
            return self._set_invalid(frame_id, "zero-length glide path")

        vx_m_s = (
            self.target_speed_m_s * horizontal_distance_m / direction_length_m
        )
        vy_m_s = -self.target_speed_m_s * altitude_m / direction_length_m
        limited = abs(vy_m_s) > self.max_vertical_speed_m_s
        if limited:
            scale = self.max_vertical_speed_m_s / abs(vy_m_s)
            vx_m_s *= scale
            vy_m_s *= scale

        self._estimate = GlideVelocityEstimate(
            frame_id=frame_id,
            horizontal_distance_m=horizontal_distance_m,
            vx_m_s=vx_m_s,
            vy_m_s=vy_m_s,
            achieved_speed_m_s=math.hypot(vx_m_s, vy_m_s),
            limited=limited,
            valid=True,
        )
        return self._estimate

    def _set_invalid(
        self, frame_id: int | None, reason: str
    ) -> GlideVelocityEstimate:
        self._estimate = self._invalid(frame_id, reason)
        return self._estimate

    @staticmethod
    def _invalid(frame_id: int | None, reason: str) -> GlideVelocityEstimate:
        return GlideVelocityEstimate(
            frame_id=frame_id,
            horizontal_distance_m=None,
            vx_m_s=0.0,
            vy_m_s=0.0,
            achieved_speed_m_s=0.0,
            limited=False,
            valid=False,
            reason=reason,
        )

    @staticmethod
    def _positive_finite(name: str, value: float) -> float:
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and greater than zero")
        return value

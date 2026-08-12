"""Target-relative velocity estimation for the visual intercept."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GlideVelocityEstimate:
    frame_id: int | None
    vx_m_s: float
    vy_m_s: float
    achieved_speed_m_s: float
    speed_quality: float
    vertical_limited: bool
    valid: bool
    reason: str | None = None


class GlideVelocityEstimator:
    """Point a velocity vector at a target expressed in camera coordinates."""

    def __init__(
        self,
        *,
        max_vertical_speed_m_s: float,
        target_speed_m_s: float = 15.0,
        center_deadband: float = 0.05,
        center_error_max: float = 0.40,
    ) -> None:
        self.max_vertical_speed_m_s = self._positive_finite(
            "max_vertical_speed_m_s", max_vertical_speed_m_s
        )
        self.target_speed_m_s = self._positive_finite(
            "target_speed_m_s", target_speed_m_s
        )
        self.center_deadband = float(center_deadband)
        self.center_error_max = float(center_error_max)
        if not all(math.isfinite(v) for v in (self.center_deadband, self.center_error_max)):
            raise ValueError("centering limits must be finite")
        if not 0.0 <= self.center_deadband < self.center_error_max <= 1.0:
            raise ValueError("centering limits must satisfy 0 <= deadband < maximum <= 1")
        self._estimate = self._invalid(None, "no estimate")

    @property
    def estimate(self) -> GlideVelocityEstimate:
        return self._estimate

    def reset(self, reason: str = "no estimate") -> GlideVelocityEstimate:
        self._estimate = self._invalid(None, reason)
        return self._estimate

    def update(
        self,
        *,
        frame_id: int | None,
        depth_m: float,
        vertical_offset_m: float,
        centering_error: float,
    ) -> GlideVelocityEstimate:
        values = (float(depth_m), float(vertical_offset_m), float(centering_error))
        depth_m, vertical_offset_m, centering_error = values
        if not all(math.isfinite(value) for value in values):
            return self._set_invalid(frame_id, "non-finite vector geometry")
        if depth_m <= 0.0:
            return self._set_invalid(frame_id, "non-positive depth")
        if centering_error < 0.0:
            return self._set_invalid(frame_id, "negative centering error")

        path_length = math.hypot(depth_m, vertical_offset_m)
        if path_length <= 0.0:
            return self._set_invalid(frame_id, "zero-length glide path")
        vx = self.target_speed_m_s * depth_m / path_length
        vy = self.target_speed_m_s * vertical_offset_m / path_length
        vertical_limited = abs(vy) > self.max_vertical_speed_m_s
        if vertical_limited:
            scale = self.max_vertical_speed_m_s / abs(vy)
            vx *= scale
            vy *= scale

        quality = self.speed_quality(centering_error)
        vx = min(self.target_speed_m_s, max(0.0, vx * quality))
        self._estimate = GlideVelocityEstimate(
            frame_id=frame_id,
            vx_m_s=vx,
            vy_m_s=vy,
            achieved_speed_m_s=math.hypot(vx, vy),
            speed_quality=quality,
            vertical_limited=vertical_limited,
            valid=True,
        )
        return self._estimate

    def speed_quality(self, centering_error: float) -> float:
        error = float(centering_error)
        if error <= self.center_deadband:
            return 1.0
        if error >= self.center_error_max:
            return 0.0
        return (self.center_error_max - error) / (
            self.center_error_max - self.center_deadband
        )

    def _set_invalid(self, frame_id: int | None, reason: str) -> GlideVelocityEstimate:
        self._estimate = self._invalid(frame_id, reason)
        return self._estimate

    @staticmethod
    def _invalid(frame_id: int | None, reason: str) -> GlideVelocityEstimate:
        return GlideVelocityEstimate(frame_id, 0.0, 0.0, 0.0, 0.0, False, False, reason)

    @staticmethod
    def _positive_finite(name: str, value: float) -> float:
        value = float(value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and greater than zero")
        return value

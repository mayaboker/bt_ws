"""Target-relative desired velocity calculation."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TargetVelocity:
    vx_m_s: float
    vy_m_s: float


class TargetVelocityEstimator:
    """Point a bounded forward/up velocity vector toward a visual target."""

    def __init__(
        self,
        *,
        target_speed_m_s: float,
    ) -> None:
        self.target_speed_m_s = float(target_speed_m_s)
        if not math.isfinite(self.target_speed_m_s) or self.target_speed_m_s <= 0:
            raise ValueError("target speed must be finite and positive")

    def estimate(
        self,
        *,
        depth_m: float,
        vertical_offset_m: float,
    ) -> TargetVelocity:
        path_length = math.hypot(depth_m, vertical_offset_m)
        if not math.isfinite(path_length) or path_length <= 0:
            raise ValueError("invalid target path")

        vx = self.target_speed_m_s * depth_m / path_length
        vy = self.target_speed_m_s * vertical_offset_m / path_length
        return TargetVelocity(vx_m_s=vx, vy_m_s=vy)

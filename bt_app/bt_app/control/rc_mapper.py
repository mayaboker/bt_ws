from __future__ import annotations

import math


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


class BetaflightRcMapper:
    def __init__(
        self,
        *,
        yaw_center_sensitivity_dps: float,
        yaw_max_rate_dps: float,
        yaw_expo: float,
        rc_mid: int = 1500,
        rc_mid_range: int = 500,
        rc_min: int = 1000,
        rc_max: int = 2000,
        yaw_sign: float = 1.0,
    ) -> None:
        """Map desired yaw rates to Betaflight RC yaw channel values.

        Args:
            yaw_center_sensitivity_dps: Actual-rates center sensitivity in
                degrees per second.
            yaw_max_rate_dps: Actual-rates maximum yaw rate in degrees per second.
            yaw_expo: Actual-rates expo as a fraction from 0 through 1.
            rc_mid: RC channel value at centered stick.
            rc_mid_range: Channel offset from center to full stick in either direction.
            rc_min: Minimum allowed RC channel value.
            rc_max: Maximum allowed RC channel value.
            yaw_sign: Direction multiplier for yaw output. Use 1.0 for normal direction
                or -1.0 to invert yaw.
        """
        rate_values = (yaw_center_sensitivity_dps, yaw_max_rate_dps, yaw_expo)
        if not all(math.isfinite(value) for value in rate_values):
            raise ValueError("yaw rate mapping values must be finite")
        if yaw_center_sensitivity_dps <= 0:
            raise ValueError("yaw center sensitivity must be greater than zero")
        if yaw_max_rate_dps < yaw_center_sensitivity_dps:
            raise ValueError("yaw maximum rate must not be below center sensitivity")
        if not 0.0 <= yaw_expo <= 1.0:
            raise ValueError("yaw expo must be in [0, 1]")

        self.yaw_center_sensitivity_dps = yaw_center_sensitivity_dps
        self.yaw_max_rate_dps = yaw_max_rate_dps
        self.yaw_expo = yaw_expo
        self.rc_mid = rc_mid
        self.rc_range = rc_mid_range
        self.rc_min = rc_min
        self.rc_max = rc_max
        self.yaw_sign = yaw_sign

    def yaw_norm_to_rate(self, yaw_norm: float) -> float:
        """Apply Betaflight's Actual-rates curve to normalized yaw stick."""
        if not math.isfinite(yaw_norm):
            raise ValueError("normalized yaw command must be finite")
        yaw_norm = clamp(yaw_norm, -1.0, 1.0)
        magnitude = abs(yaw_norm)
        curve = (
            self.yaw_expo * magnitude**6
            + (1.0 - self.yaw_expo) * magnitude**2
        )
        rate = (
            self.yaw_center_sensitivity_dps * magnitude
            + (self.yaw_max_rate_dps - self.yaw_center_sensitivity_dps) * curve
        )
        return math.copysign(rate, yaw_norm)

    def yaw_rate_to_norm(self, yaw_rate_dps: float) -> float:
        """Invert Betaflight's monotonic Actual-rates curve by bisection."""
        if not math.isfinite(yaw_rate_dps):
            raise ValueError("yaw rate must be finite")
        sign = -1.0 if yaw_rate_dps < 0.0 else 1.0
        target = min(abs(yaw_rate_dps), self.yaw_max_rate_dps)
        lower = 0.0
        upper = 1.0
        for _ in range(40):
            midpoint = (lower + upper) / 2.0
            if self.yaw_norm_to_rate(midpoint) < target:
                lower = midpoint
            else:
                upper = midpoint
        return sign * (lower + upper) / 2.0

    def yaw_rate_to_rc(self, yaw_rate_dps: float) -> int:
        yaw_norm = self.yaw_rate_to_norm(yaw_rate_dps)
        rc_yaw = round(self.rc_mid + self.yaw_sign * self.rc_range * yaw_norm)
        return int(clamp(rc_yaw, self.rc_min, self.rc_max))

    def angle_to_rc(
        self,
        angle_deg: float,
        *,
        angle_limit_deg: float,
        sign: float = 1.0,
    ) -> int:
        """Map a physical attitude angle to a centered RC channel."""
        values = (float(angle_deg), float(angle_limit_deg), float(sign))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("angle mapping values must be finite")
        if angle_limit_deg <= 0:
            raise ValueError("angle_limit_deg must be greater than zero")
        normalized = clamp(angle_deg / angle_limit_deg, -1.0, 1.0)
        rc_value = round(self.rc_mid + sign * self.rc_range * normalized)
        return int(clamp(rc_value, self.rc_min, self.rc_max))

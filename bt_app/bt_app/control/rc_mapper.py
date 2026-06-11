from __future__ import annotations


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


class BetaflightRcMapper:
    def __init__(
        self,
        *,
        yaw_rate_full_stick_dps: float,
        rc_mid: int = 1500,
        rc_mid_range: int = 500,
        rc_min: int = 1000,
        rc_max: int = 2000,
        yaw_sign: float = 1.0,
    ) -> None:
        if yaw_rate_full_stick_dps <= 0:
            raise ValueError("yaw_rate_full_stick_dps must be greater than zero")

        self.yaw_rate_full_stick_dps = yaw_rate_full_stick_dps
        self.rc_mid = rc_mid
        self.rc_range = rc_mid_range
        self.rc_min = rc_min
        self.rc_max = rc_max
        self.yaw_sign = yaw_sign

    def yaw_rate_to_norm(self, yaw_rate_dps: float) -> float:
        return clamp(
            yaw_rate_dps / self.yaw_rate_full_stick_dps,
            -1.0,
            1.0,
        )

    def yaw_rate_to_rc(self, yaw_rate_dps: float) -> int:
        yaw_norm = self.yaw_rate_to_norm(yaw_rate_dps)
        rc_yaw = round(self.rc_mid + self.yaw_sign * self.rc_range * yaw_norm)
        return int(clamp(rc_yaw, self.rc_min, self.rc_max))

import time


class LandDetector:
    def __init__(
        self,
        *,
        confirm_s: float,
        land_altitude_m: float,
        land_vertical_speed_m_s: float,
    ) -> None:
        self.confirm_s = confirm_s
        self.land_altitude_m = land_altitude_m
        self.land_vertical_speed_m_s = land_vertical_speed_m_s
        self._candidate_since_s: float | None = None

    def reset(self) -> None:
        self._candidate_since_s = None

    def update(self, current_altitude: float, vertical_speed_m_s: float) -> bool:
        now = time.monotonic()
        if not self._is_land_candidate(current_altitude, vertical_speed_m_s):
            self.reset()
            return False

        if self._candidate_since_s is None:
            self._candidate_since_s = now
            return False

        return now - self._candidate_since_s >= float(self.confirm_s)

    def _is_land_candidate(
        self,
        current_altitude: float,
        vertical_speed_m_s: float,
    ) -> bool:
        return (
            current_altitude <= float(self.land_altitude_m)
            and abs(vertical_speed_m_s) <= float(self.land_vertical_speed_m_s)
        )

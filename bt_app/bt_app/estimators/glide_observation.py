"""Immutable controller-facing visual observation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlideObservation:
    frame_id: int | None
    source_timestamp_ns: int | None
    received_at_s: float | None
    age_s: float | None
    bbox: tuple[int, int, int, int] | None
    ex: float | None
    ey: float | None
    centering_error: float | None
    speed_quality: float
    depth_m: float | None
    vertical_offset_m: float | None
    vx_geometry_m_s: float
    vy_geometry_m_s: float
    achieved_speed_m_s: float
    vertical_limited: bool
    valid: bool
    reason: str | None = None

    @classmethod
    def invalid(
        cls,
        reason: str,
        *,
        frame_id: int | None = None,
        source_timestamp_ns: int | None = None,
        received_at_s: float | None = None,
        age_s: float | None = None,
        bbox: tuple[int, int, int, int] | None = None,
        ex: float | None = None,
        ey: float | None = None,
        centering_error: float | None = None,
    ) -> "GlideObservation":
        return cls(
            frame_id, source_timestamp_ns, received_at_s, age_s, bbox,
            ex, ey, centering_error, 0.0, None, None, 0.0, 0.0, 0.0,
            False, False, reason,
        )

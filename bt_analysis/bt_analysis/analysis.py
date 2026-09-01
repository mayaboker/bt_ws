"""Pure calculations for blackbox session summaries and velocity series."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pyarrow as pa

from bt_analysis.errors import SessionDataError
from bt_analysis.repository import BlackboxRepository, BlackboxSession

ODOMETRY_COLUMNS = (
    "elapsed_s",
    "velocity_body_x_m_s",
    "velocity_body_y_m_s",
    "velocity_body_z_m_s",
)


def analyze_session(
    repository: BlackboxRepository,
    session: BlackboxSession,
) -> dict[str, Any]:
    metadata = session.metadata
    duration_s = _duration_s(metadata)
    events = repository.load_events(session)
    odometry = repository.load_odometry(session)
    velocity = (
        None
        if odometry is None or odometry.num_rows == 0
        else velocity_series(odometry)
    )
    velocity_statistics = (
        None if velocity is None else _velocity_statistics(velocity)
    )
    frame_count = _nonnegative_int(metadata.get("frame_count", 0))
    odometry_count = _nonnegative_int(
        metadata.get("odometry_count", 0 if odometry is None else odometry.num_rows)
    )
    return {
        "session": {
            "session_id": session.session_id,
            "status": metadata.get("status"),
            "end_reason": metadata.get("end_reason"),
            "schema_version": metadata.get("schema_version"),
            "start_utc_ns": metadata.get("start_utc_ns"),
            "end_utc_ns": metadata.get("end_utc_ns"),
            "duration_s": duration_s,
            "timezone": metadata.get("timezone"),
            "app_version": metadata.get("app_version"),
            "git_revision": metadata.get("git_revision"),
        },
        "quality": {
            "frame_count": frame_count,
            "odometry_count": odometry_count,
            "frame_rate_hz": _rate(frame_count, duration_s),
            "odometry_rate_hz": _rate(odometry_count, duration_s),
            "dropped_frames": _nonnegative_int(metadata.get("dropped_frames", 0)),
            "dropped_odometry": _nonnegative_int(
                metadata.get("dropped_odometry", 0)
            ),
            "writer_errors": _nonnegative_int(metadata.get("writer_errors", 0)),
        },
        "states": _state_intervals(events, duration_s),
        "velocity": {
            "available": velocity is not None,
            "frame": "FLU",
            "units": "m/s",
            "statistics": velocity_statistics,
        },
    }


def velocity_series(table: pa.Table) -> dict[str, list[float]]:
    missing = [name for name in ODOMETRY_COLUMNS if name not in table.column_names]
    if missing:
        raise SessionDataError(
            "Odometry schema is missing column(s): " + ", ".join(missing)
        )
    try:
        elapsed = _finite_array(table, "elapsed_s")
        forward = _finite_array(table, "velocity_body_x_m_s")
        left = -_finite_array(table, "velocity_body_y_m_s")
        up = -_finite_array(table, "velocity_body_z_m_s")
    except (TypeError, ValueError, pa.ArrowException) as exc:
        raise SessionDataError(f"Invalid odometry values: {exc}") from exc
    if not (len(elapsed) == len(forward) == len(left) == len(up)):
        raise SessionDataError("Odometry columns have inconsistent lengths")
    if len(elapsed) and np.any(np.diff(elapsed) < 0.0):
        raise SessionDataError("Odometry elapsed time is not monotonic")
    return {
        "elapsed_s": elapsed.tolist(),
        "vx_forward_m_s": forward.tolist(),
        "vy_left_m_s": left.tolist(),
        "vz_up_m_s": up.tolist(),
    }


def _duration_s(metadata: dict[str, Any]) -> float:
    try:
        duration = (
            int(metadata["end_monotonic_ns"])
            - int(metadata["start_monotonic_ns"])
        ) / 1e9
    except (KeyError, TypeError, ValueError):
        duration = 0.0
    return max(0.0, float(duration))


def _state_intervals(table: pa.Table | None, duration_s: float) -> list[dict[str, Any]]:
    if table is None or table.num_rows == 0:
        return []
    required = {"elapsed_s", "current_state_name"}
    if not required.issubset(table.column_names):
        raise SessionDataError("Event schema is missing state or elapsed time")
    rows = sorted(table.to_pylist(), key=lambda row: float(row["elapsed_s"]))
    intervals = []
    for index, row in enumerate(rows):
        start = max(0.0, float(row["elapsed_s"]))
        next_start = (
            max(start, float(rows[index + 1]["elapsed_s"]))
            if index + 1 < len(rows)
            else max(start, duration_s)
        )
        intervals.append(
            {
                "state": str(row["current_state_name"]),
                "start_s": start,
                "end_s": next_start,
                "duration_s": next_start - start,
            }
        )
    return intervals


def _velocity_statistics(series: dict[str, list[float]]) -> dict[str, Any]:
    elapsed = np.asarray(series["elapsed_s"], dtype=float)
    result: dict[str, Any] = {}
    for axis in ("vx_forward_m_s", "vy_left_m_s", "vz_up_m_s"):
        values = np.asarray(series[axis], dtype=float)
        if values.size == 0:
            result[axis] = None
            continue
        minimum_index = int(np.argmin(values))
        maximum_index = int(np.argmax(values))
        result[axis] = {
            "mean_m_s": float(np.mean(values)),
            "rms_m_s": float(math.sqrt(float(np.mean(values * values)))),
            "min": {
                "value_m_s": float(values[minimum_index]),
                "elapsed_s": float(elapsed[minimum_index]),
            },
            "max": {
                "value_m_s": float(values[maximum_index]),
                "elapsed_s": float(elapsed[maximum_index]),
            },
        }
    return result


def _finite_array(table: pa.Table, name: str) -> np.ndarray:
    values = np.asarray(table[name].to_pylist(), dtype=float)
    if not np.all(np.isfinite(values)):
        raise SessionDataError(f"Odometry column contains non-finite values: {name}")
    return values


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _rate(count: int, duration_s: float) -> float | None:
    return None if duration_s <= 0.0 else count / duration_s

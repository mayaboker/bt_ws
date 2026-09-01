from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def make_session(tmp_path):
    def create(
        session_id: str,
        *,
        start_utc_ns: int,
        status: str = "complete",
        with_odometry: bool = True,
    ) -> Path:
        directory = tmp_path / f"{session_id}_blackbox"
        directory.mkdir()
        chunks = [
            {
                "index": 0,
                "frames": "frames-000000.parquet",
                "events": "events-000000.parquet",
                "odometry": "odometry-000000.parquet" if with_odometry else None,
            }
        ]
        metadata = {
            "schema_version": 2 if with_odometry else 1,
            "session_id": session_id,
            "status": status,
            "start_utc_ns": start_utc_ns,
            "end_utc_ns": start_utc_ns + 4_000_000_000,
            "start_monotonic_ns": 10_000_000_000,
            "end_monotonic_ns": 14_000_000_000,
            "end_reason": "disarmed",
            "timezone": "UTC",
            "app_version": "test",
            "git_revision": "abcdef0123456789",
            "frame_count": 200,
            "odometry_count": 3 if with_odometry else 0,
            "dropped_frames": 1,
            "dropped_odometry": 2,
            "writer_errors": 0,
            "chunks": chunks,
        }
        (directory / "metadata.json").write_text(json.dumps(metadata))
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {"elapsed_s": 0.0, "current_state_name": "ARM"},
                    {"elapsed_s": 0.5, "current_state_name": "TAKEOFF"},
                    {"elapsed_s": 3.0, "current_state_name": "ALT_HOLD"},
                ]
            ),
            directory / "events-000000.parquet",
        )
        pq.write_table(
            pa.Table.from_pylist([{"elapsed_s": 0.0}]),
            directory / "frames-000000.parquet",
        )
        if with_odometry:
            pq.write_table(
                pa.Table.from_pylist(
                    [
                        {
                            "elapsed_s": 0.0,
                            "velocity_body_x_m_s": 1.0,
                            "velocity_body_y_m_s": 2.0,
                            "velocity_body_z_m_s": 3.0,
                        },
                        {
                            "elapsed_s": 1.0,
                            "velocity_body_x_m_s": -1.0,
                            "velocity_body_y_m_s": 0.0,
                            "velocity_body_z_m_s": -3.0,
                        },
                        {
                            "elapsed_s": 2.0,
                            "velocity_body_x_m_s": 2.0,
                            "velocity_body_y_m_s": -4.0,
                            "velocity_body_z_m_s": 1.0,
                        },
                    ]
                ),
                directory / "odometry-000000.parquet",
            )
        return directory

    return create


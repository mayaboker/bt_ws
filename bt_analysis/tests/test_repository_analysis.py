from __future__ import annotations

import json
import math

import pytest

from bt_analysis.analysis import analyze_session, velocity_series
from bt_analysis.errors import (
    NoFinishedSessionError,
    SessionDataError,
    SessionNotFoundError,
)
from bt_analysis.repository import BlackboxRepository


def test_selects_latest_finished_session_and_ignores_invalid_entries(
    tmp_path, make_session
):
    make_session("older", start_utc_ns=100)
    make_session("latest", start_utc_ns=300, status="unclean")
    make_session("active", start_utc_ns=400, status="recording")
    broken = tmp_path / "broken_blackbox"
    broken.mkdir()
    (broken / "metadata.json").write_text("not json")

    repository = BlackboxRepository(tmp_path)

    assert repository.latest().session_id == "latest"
    assert [session.session_id for session in repository.sessions()] == [
        "latest",
        "older",
    ]


def test_empty_repository_has_no_finished_session(tmp_path):
    with pytest.raises(NoFinishedSessionError):
        BlackboxRepository(tmp_path).latest()


def test_rejects_unknown_and_unsafe_session_ids(tmp_path, make_session):
    make_session("known", start_utc_ns=100)
    repository = BlackboxRepository(tmp_path)

    with pytest.raises(SessionNotFoundError):
        repository.get("../known")
    with pytest.raises(SessionNotFoundError):
        repository.get("missing")


def test_analyzes_quality_states_and_flu_velocity(tmp_path, make_session):
    make_session("flight", start_utc_ns=100)
    repository = BlackboxRepository(tmp_path)
    session = repository.latest()

    summary = analyze_session(repository, session)
    series = velocity_series(repository.load_odometry(session))

    assert summary["session"]["duration_s"] == 4.0
    assert summary["quality"] == {
        "frame_count": 200,
        "odometry_count": 3,
        "frame_rate_hz": 50.0,
        "odometry_rate_hz": 0.75,
        "dropped_frames": 1,
        "dropped_odometry": 2,
        "writer_errors": 0,
    }
    assert summary["states"] == [
        {"state": "ARM", "start_s": 0.0, "end_s": 0.5, "duration_s": 0.5},
        {
            "state": "TAKEOFF",
            "start_s": 0.5,
            "end_s": 3.0,
            "duration_s": 2.5,
        },
        {
            "state": "ALT_HOLD",
            "start_s": 3.0,
            "end_s": 4.0,
            "duration_s": 1.0,
        },
    ]
    assert series == {
        "elapsed_s": [0.0, 1.0, 2.0],
        "vx_forward_m_s": [1.0, -1.0, 2.0],
        "vy_left_m_s": [-2.0, -0.0, 4.0],
        "vz_up_m_s": [-3.0, 3.0, -1.0],
    }
    forward = summary["velocity"]["statistics"]["vx_forward_m_s"]
    assert forward["mean_m_s"] == pytest.approx(2 / 3)
    assert forward["rms_m_s"] == pytest.approx(math.sqrt(2))
    assert forward["min"] == {"value_m_s": -1.0, "elapsed_s": 1.0}
    assert forward["max"] == {"value_m_s": 2.0, "elapsed_s": 2.0}


def test_schema_one_session_keeps_summary_without_velocity(tmp_path, make_session):
    make_session("legacy", start_utc_ns=100, with_odometry=False)
    repository = BlackboxRepository(tmp_path)

    summary = analyze_session(repository, repository.latest())

    assert summary["velocity"] == {
        "available": False,
        "frame": "FLU",
        "units": "m/s",
        "statistics": None,
    }


def test_missing_referenced_chunk_is_reported(tmp_path, make_session):
    directory = make_session("flight", start_utc_ns=100)
    (directory / "odometry-000000.parquet").unlink()
    repository = BlackboxRepository(tmp_path)

    with pytest.raises(SessionDataError, match="Missing odometry"):
        repository.load_odometry(repository.latest())


def test_unsafe_chunk_inventory_is_reported(tmp_path, make_session):
    directory = make_session("flight", start_utc_ns=100)
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["chunks"][0]["odometry"] = "../secret.parquet"
    metadata_path.write_text(json.dumps(metadata))
    repository = BlackboxRepository(tmp_path)

    with pytest.raises(SessionDataError, match="Unsafe odometry"):
        repository.load_odometry(repository.latest())


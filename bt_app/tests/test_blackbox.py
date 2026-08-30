from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from bt_msgs import TrackerResultMessage
import pyarrow.parquet as pq

import bt_app.blackbox as blackbox_module
from bt_app.blackbox import BlackboxRecorder, FRAME_SCHEMA, NullBlackboxRecorder
from bt_app.common import InternalJoystick, RobotState
from bt_app.context import Context
from bt_app.services.tracker_result_store import TrackerObservation


@dataclass
class Config:
    name: str = "simulation"


def make_context(*, armed: bool = False) -> Context:
    context = Context()
    context.armed = armed
    context.state = RobotState.ALT_HOLD if armed else RobotState.IDLE
    context.request_rc = InternalJoystick(
        roll=1510,
        pitch=1490,
        throttle=1600,
        arm=2000 if armed else 1000,
        manual=2000,
    )
    context.sent_rc = [1511, 1491, 1601, 1501, 2000, 2000, 1000, 1000]
    context.drone_alt = 9.8
    context.drone_vertical_speed = 0.2
    context.drone_alt_received_at_s = 10.0
    context.drone_roll_deg = 1.0
    context.drone_pitch_deg = -2.0
    context.drone_heading_deg = 45.0
    context.drone_attitude_received_at_s = 10.0
    return context


def make_recorder(path: Path, **kwargs) -> BlackboxRecorder:
    return BlackboxRecorder(
        path,
        vehicle_config=Config(),
        parameters={"HOV_BASELINE": 1660},
        wall_clock_ns=lambda: 1_788_086_400_123_000_000,
        **kwargs,
    )


def session_directory(path: Path) -> Path:
    sessions = list(path.glob("*_blackbox"))
    assert len(sessions) == 1
    return sessions[0]


def test_records_only_armed_interval_as_combined_parquet_frame(tmp_path):
    recorder = make_recorder(tmp_path)
    recorder.start()
    context = make_context()
    recorder.record(context, None, now_s=10.0)
    context.armed = True
    context.state = RobotState.ALT_HOLD
    observation = TrackerObservation(
        TrackerResultMessage(
            tracker_id=1,
            frame_id=7,
            timestamp_ns=123,
            locked=True,
            bbox_x=10,
            bbox_y=20,
            bbox_width=30,
            bbox_height=40,
            score=0.8,
            state=1,
            dx=-3,
            dy=4,
        ),
        received_at_s=9.9,
    )
    recorder.record(context, observation, now_s=10.1)
    recorder.record(context, observation, now_s=10.12)
    context.armed = False
    context.state = RobotState.IDLE
    recorder.record(context, observation, now_s=10.2)
    recorder.stop()

    session = session_directory(tmp_path)
    table = pq.read_table(session / "frames-000000.parquet")
    rows = table.to_pylist()
    assert table.schema == FRAME_SCHEMA
    assert len(rows) == 2
    assert rows[0]["request_ch1"] == 1510
    assert rows[0]["request_ch18"] == 1000
    assert rows[0]["output_ch3"] == 1601
    assert rows[0]["altitude_fresh"] is True
    assert rows[1]["altitude_fresh"] is False
    assert rows[0]["tracker_new_frame"] is True
    assert rows[1]["tracker_new_frame"] is False
    assert rows[0]["tracker_bbox_height"] == 40
    metadata = json.loads((session / "metadata.json").read_text())
    assert metadata["status"] == "complete"
    assert metadata["end_reason"] == "disarmed"
    assert metadata["end_utc_ns"] == 1_788_086_400_123_000_000
    assert metadata["frame_count"] == 2
    assert metadata["parameters"] == {"HOV_BASELINE": 1660}


def test_parameter_snapshot_is_taken_when_flight_arms(tmp_path):
    values = {"HOV_BASELINE": 1600}
    recorder = BlackboxRecorder(
        tmp_path,
        vehicle_config=Config(),
        parameters=lambda: dict(values),
        wall_clock_ns=lambda: 1_788_086_400_123_000_000,
    )
    recorder.start()
    values["HOV_BASELINE"] = 1675
    context = make_context(armed=True)
    recorder.record(context, None, now_s=11.0)
    context.armed = False
    recorder.record(context, None, now_s=11.1)
    recorder.stop()

    metadata = json.loads(
        (session_directory(tmp_path) / "metadata.json").read_text()
    )
    assert metadata["parameters"] == {"HOV_BASELINE": 1675}


def test_rotates_atomic_chunks_and_records_state_transitions(tmp_path):
    recorder = make_recorder(tmp_path, chunk_duration_s=0.05)
    recorder.start()
    context = make_context(armed=True)
    recorder.record(context, None, now_s=20.0)
    context.state = RobotState.TRACK
    recorder.record(context, None, now_s=20.06)
    context.armed = False
    context.state = RobotState.IDLE
    recorder.record(context, None, now_s=20.1)
    recorder.stop()

    session = session_directory(tmp_path)
    assert len(list(session.glob("frames-*.parquet"))) == 2
    assert not list(session.glob("*.tmp"))
    events = []
    for path in sorted(session.glob("events-*.parquet")):
        events.extend(pq.read_table(path).to_pylist())
    assert [event["current_state_name"] for event in events] == [
        "ALT_HOLD",
        "TRACK",
    ]


def test_stop_while_armed_marks_session_unclean(tmp_path):
    recorder = make_recorder(tmp_path)
    recorder.start()
    recorder.record(make_context(armed=True), None, now_s=30.0)
    recorder.stop()

    metadata = json.loads(
        (session_directory(tmp_path) / "metadata.json").read_text()
    )
    assert metadata["status"] == "unclean"
    assert metadata["end_reason"] == "application_stopped"


def test_each_flight_creates_a_separate_session(tmp_path):
    wall_times = iter(
        [
            1_788_086_400_123_000_000,
            1_788_086_401_123_000_000,
            1_788_086_402_123_000_000,
            1_788_086_403_123_000_000,
        ]
    )
    recorder = BlackboxRecorder(
        tmp_path,
        vehicle_config=Config(),
        parameters={},
        wall_clock_ns=lambda: next(wall_times),
    )
    recorder.start()
    context = make_context(armed=True)
    recorder.record(context, None, now_s=1.0)
    context.armed = False
    recorder.record(context, None, now_s=2.0)
    context.armed = True
    recorder.record(context, None, now_s=3.0)
    context.armed = False
    recorder.record(context, None, now_s=4.0)
    recorder.stop()

    sessions = sorted(tmp_path.glob("*_blackbox"))
    assert len(sessions) == 2
    assert all(json.loads((path / "metadata.json").read_text())["status"] == "complete" for path in sessions)


def test_start_recovers_interrupted_session_and_removes_temporary_files(tmp_path):
    session = tmp_path / "20260830T120000.000000Z_deadbeef_blackbox"
    session.mkdir()
    (session / "metadata.json").write_text('{"status": "recording"}')
    (session / "frames-000000.parquet.tmp").write_bytes(b"partial")

    recorder = make_recorder(tmp_path)
    recorder.start()
    recorder.stop()

    metadata = json.loads((session / "metadata.json").read_text())
    assert metadata["status"] == "unclean"
    assert metadata["end_reason"] == "interrupted"
    assert not list(session.glob("*.tmp"))


def test_queue_overflow_drops_frame_without_blocking(tmp_path):
    recorder = make_recorder(tmp_path, queue_size=1)
    recorder._enabled = True
    for _ in range(recorder._frame_capacity):
        recorder._queue.put_nowait({"occupied": True})

    recorder._put_frame({"sample": 1})

    assert recorder.dropped_frames == 1
    assert recorder._queue.qsize() == recorder._frame_capacity


def test_capture_error_is_contained_and_disables_recording(tmp_path, monkeypatch):
    recorder = make_recorder(tmp_path)
    recorder.start()
    monkeypatch.setattr(
        recorder,
        "_make_frame",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad frame")),
    )

    recorder.record(make_context(armed=True), None, now_s=1.0)

    assert recorder.writer_errors == 1
    assert recorder._enabled is False
    recorder.stop()


def test_disk_write_error_marks_unclean_without_escaping(tmp_path, monkeypatch):
    recorder = make_recorder(tmp_path)
    recorder.start()
    monkeypatch.setattr(
        blackbox_module,
        "_write_parquet_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    context = make_context(armed=True)
    recorder.record(context, None, now_s=2.0)
    context.armed = False
    recorder.record(context, None, now_s=2.1)
    recorder.stop()

    metadata = json.loads(
        (session_directory(tmp_path) / "metadata.json").read_text()
    )
    assert metadata["status"] == "unclean"
    assert metadata["end_reason"] == "writer_error"
    assert recorder.writer_errors == 1


def test_null_blackbox_never_creates_output(tmp_path):
    recorder = NullBlackboxRecorder()
    recorder.start()
    recorder.record(make_context(armed=True), None, now_s=1.0)
    recorder.stop()

    assert list(tmp_path.iterdir()) == []

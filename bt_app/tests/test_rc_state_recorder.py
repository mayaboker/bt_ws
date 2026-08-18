import csv
import time

from bt_app.common import RobotState
import pytest

from bt_app.rc_state_recorder import (
    CSV_HEADER,
    NullRcStateRecorder,
    RcStateRecorder,
    RcStateRecorderStartupError,
)


def read_rows(path):
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.reader(file))


def test_recorder_writes_header_and_valid_row(tmp_path):
    path = tmp_path / "logs" / "rc_state.csv"
    recorder = RcStateRecorder(path, flush_interval_s=0.01)

    recorder.start()
    recorder.record(RobotState.ALT_HOLD, [1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800])
    recorder.stop()

    rows = read_rows(path)
    assert rows[0] == list(CSV_HEADER)
    assert rows[1][1:] == [
        "ALT_HOLD",
        "1100",
        "1200",
        "1300",
        "1400",
        "1500",
        "1600",
        "1700",
        "1800",
    ]
    assert rows[1][0].isdigit()


def test_recorder_drops_invalid_channel_count(tmp_path):
    path = tmp_path / "rc_state.csv"
    recorder = RcStateRecorder(path)

    recorder.start()
    recorder.record(RobotState.MANUAL, [1000])
    recorder.stop()

    assert recorder.dropped_samples == 1
    assert read_rows(path) == [list(CSV_HEADER)]


def test_recorder_queue_full_drops_newest_without_blocking(tmp_path):
    path = tmp_path / "rc_state.csv"
    recorder = RcStateRecorder(path, queue_size=1)
    recorder._enabled = True
    recorder._queue.put_nowait((time.monotonic_ns(), "MANUAL", (1000,) * 8))

    recorder.record(RobotState.ALT_HOLD, [1100] * 8)

    assert recorder.dropped_samples == 1
    queued = recorder._queue.get_nowait()
    assert queued[1] == "MANUAL"
    assert queued[2] == (1000,) * 8


def test_recorder_stop_drains_queued_samples(tmp_path):
    path = tmp_path / "rc_state.csv"
    recorder = RcStateRecorder(path, flush_interval_s=100.0)

    recorder.start()
    for index in range(3):
        recorder.record(RobotState.ARM, [1000 + index] * 8)
    recorder.stop()

    rows = read_rows(path)
    assert len(rows) == 4
    assert rows[-1][1:] == [
        "ARM",
        "1002",
        "1002",
        "1002",
        "1002",
        "1002",
        "1002",
        "1002",
        "1002",
    ]


def test_null_recorder_does_not_create_file(tmp_path):
    path = tmp_path / "should_not_exist.csv"
    recorder = NullRcStateRecorder()

    recorder.start()
    recorder.record(RobotState.IDLE, [1000] * 8)
    recorder.stop()

    assert not path.exists()


def test_enabled_recorder_surfaces_file_startup_error(tmp_path):
    recorder = RcStateRecorder(tmp_path)

    with pytest.raises(RcStateRecorderStartupError) as exc_info:
        recorder.start()

    assert exc_info.value.path == tmp_path

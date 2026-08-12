import csv
import time

from bt_app.glide_diagnostic_recorder import (
    CSV_HEADER,
    GlideDiagnosticRecorder,
    GlideDiagnosticSample,
    NullGlideDiagnosticRecorder,
)


def sample(timestamp=123):
    return GlideDiagnosticSample(
        timestamp, "track", 7, True, None, None, 0.1, -0.2,
        2.0, 1.5, -0.4, -0.3, 5.0, 8.0, 1.0, 2.0, 3.0, -2.0, 1485, 1660,
    )


def rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.reader(stream))


def test_recorder_writes_fixed_schema_and_sample(tmp_path):
    path = tmp_path / "logs" / "glide.csv"
    recorder = GlideDiagnosticRecorder(path, flush_interval_s=0.01)
    recorder.start()
    recorder.record(sample())
    recorder.stop()

    data = rows(path)
    assert data[0] == list(CSV_HEADER)
    assert data[1][0:4] == ["123", "track", "7", "True"]
    assert data[1][-1] == "1660"


def test_queue_full_drops_newest_without_blocking(tmp_path):
    recorder = GlideDiagnosticRecorder(tmp_path / "glide.csv", queue_size=1)
    recorder._enabled = True
    recorder._queue.put_nowait(sample(1))
    recorder.record(sample(2))

    assert recorder.dropped_samples == 1
    assert recorder._queue.get_nowait().time_monotonic_ns == 1


def test_stop_drains_queue(tmp_path):
    path = tmp_path / "glide.csv"
    recorder = GlideDiagnosticRecorder(path, flush_interval_s=100.0)
    recorder.start()
    for timestamp in range(3):
        recorder.record(sample(timestamp))
    recorder.stop()
    assert len(rows(path)) == 4


def test_schema_change_preserves_old_log_and_writes_versioned_file(tmp_path):
    path = tmp_path / "glide.csv"
    path.write_text("old,header\n1,2\n", encoding="utf-8")
    recorder = GlideDiagnosticRecorder(path, flush_interval_s=0.01)

    recorder.start()
    recorder.record(sample())
    recorder.stop()

    assert path.read_text(encoding="utf-8") == "old,header\n1,2\n"
    assert rows(tmp_path / "glide.v2.csv")[0] == list(CSV_HEADER)


def test_null_recorder_is_noop():
    recorder = NullGlideDiagnosticRecorder()
    recorder.start()
    recorder.record(sample())
    recorder.stop()

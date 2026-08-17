import subprocess
import sys
from pathlib import Path

import pytest

from bt_gst import app as app_module
from bt_gst.bridge.zmq_models import (
    RedDetectionMessage,
    TrackAdjustmentRequest,
    TrackResizeRequest,
    TrackStartRequest,
    TrackStopRequest,
)
from bt_gst.cli import RunCommand, ShowCommand, VersionCommand, parse_args
from bt_gst.config import (
    AppConfig,
    AppConfigOverrides,
    CameraSourceConfig,
    ConfigError,
    DetectorConfig,
    FileSourceConfig,
    SimulationSourceConfig,
    ZmqConfig,
    load_config_overrides,
    resolve_config,
    validate_config,
)
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.pipeline_runner import DetectionTelemetryState, DetectorLockState
from bt_gst.red_detection import (
    GST_CLOCK_TIME_NONE,
    CursorRoi,
    DetectionCursorState,
    DetectionOverlayState,
    RedDetection,
    read_red_detection,
)


def test_load_and_resolve_file_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "source:\n  type: file\n  path: video.avi\n  rate: 12\n"
        "host: 192.0.2.1\nport: 5600\n",
        encoding="utf-8",
    )

    config = resolve_config(AppConfig(), load_config_overrides(config_path))

    assert config.source == FileSourceConfig(path=Path("video.avi"), rate=12)
    assert config.host == "192.0.2.1"
    assert config.port == 5600


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        (FileSourceConfig(Path("video.avi"), rate=10), "filesrc location=video.avi"),
        (CameraSourceConfig("/dev/video2"), "v4l2src device=/dev/video2"),
        (SimulationSourceConfig("/camera", rate=25), "gzimgsrc topic=/camera"),
    ],
)
def test_build_pipeline_for_supported_sources(source: object, fragment: str) -> None:
    pipeline = build_pipeline_description(AppConfig(source=source, video_local=False))

    assert fragment in pipeline
    assert "rtph264pay" in pipeline
    assert "udpsink" in pipeline


def test_detector_pipeline_contains_plugin_overlay_and_metadata_sink() -> None:
    pipeline = build_pipeline_description(
        AppConfig(
            source=SimulationSourceConfig("/camera"),
            detector=DetectorConfig(enabled=True, overlay_enabled=True),
            video_local=False,
        )
    )

    assert "controlledreddetect" in pipeline
    assert "cairooverlay name=detection_overlay" in pipeline
    assert "appsink name=detection_sink" in pipeline


def test_validate_rejects_zmq_without_detector() -> None:
    with pytest.raises(ConfigError, match="zmq.enabled requires detector.enabled"):
        validate_config(
            AppConfig(
                source=FileSourceConfig(Path("video.avi")),
                zmq=ZmqConfig(enabled=True),
            )
        )


def test_detector_lock_lifecycle() -> None:
    state = DetectorLockState()
    assert state.update(True) == (False, 0, 0)

    state.apply_request(TrackStartRequest(320, 240))
    for expected in range(1, 10):
        assert state.update(True) == (False, expected, 0)
    assert state.update(True) == (True, 10, 0)

    for expected in range(1, 5):
        assert state.update(False) == (True, 0, expected)
    assert state.update(False) == (False, 0, 5)

    state.apply_request(TrackStopRequest())
    assert state.update(True) == (False, 0, 0)


class RecordingPublisher:
    def __init__(self) -> None:
        self.messages: list[RedDetectionMessage] = []

    def publish_red_detection(self, message: RedDetectionMessage) -> None:
        self.messages.append(message)


def test_detection_telemetry_assigns_frame_ids() -> None:
    publisher = RecordingPublisher()
    state = DetectionTelemetryState(publisher)  # type: ignore[arg-type]
    state.lock_state.apply_request(TrackStartRequest(10, 20))

    state.publish(RedDetection(True, 1, 2, 3, 4, 5))
    state.publish(RedDetection(False, 0, 0, 0, 0, 6))

    assert [message.frame_id for message in publisher.messages] == [1, 2]
    assert publisher.messages[0].timestamp_ns == 5
    assert publisher.messages[0].lock_found_frames == 1


def test_cursor_applies_all_control_requests() -> None:
    state = DetectionCursorState(frame_width=100, frame_height=80, initial_size=20)
    state.apply(TrackStartRequest(50, 40))
    assert state.snapshot() == CursorRoi(40, 30, 20, 20)

    state.apply(TrackAdjustmentRequest(10, -5))
    assert state.snapshot() == CursorRoi(50, 25, 20, 20)

    state.apply(TrackResizeRequest(30, 10))
    assert state.snapshot() == CursorRoi(45, 30, 30, 10)

    state.apply(TrackStopRequest())
    assert state.snapshot() is None


def test_overlay_matches_detection_timestamp() -> None:
    state = DetectionOverlayState()
    detection = RedDetection(True, 1, 2, 3, 4, 123)
    state.update(detection)

    assert state.detection_for_timestamp(123) == detection
    assert state.detection_for_timestamp(124) is None


class FakeStructure:
    def __init__(self) -> None:
        self.values = {"found": True, "x": 1, "y": 2, "width": 3, "height": 4}

    def get_value(self, name: str) -> object:
        return self.values[name]


class FakeMeta:
    def get_structure(self) -> FakeStructure:
        return FakeStructure()


class FakeBuffer:
    def __init__(self, pts: int, has_meta: bool = True) -> None:
        self.pts = pts
        self.has_meta = has_meta

    def get_custom_meta(self, _name: str) -> FakeMeta | None:
        return FakeMeta() if self.has_meta else None


def test_read_red_detection_handles_timestamp_and_missing_meta() -> None:
    assert read_red_detection(FakeBuffer(10)) == RedDetection(True, 1, 2, 3, 4, 10)
    assert read_red_detection(FakeBuffer(GST_CLOCK_TIME_NONE)).pts_ns is None
    assert read_red_detection(FakeBuffer(10, has_meta=False)) is None


def test_cli_parses_commands() -> None:
    assert isinstance(parse_args(["version"]), VersionCommand)
    assert isinstance(parse_args(["show", "-c", "config.example.yaml"]), ShowCommand)
    assert isinstance(parse_args(["run", "-c", "config.example.yaml"]), RunCommand)


def test_cli_rejects_source_options_without_source() -> None:
    assert parse_args(["show", "--topic", "/camera"]) != 0


def test_app_show_prints_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    assert app_module.main(["show", "-c", "config.example.yaml"]) == 0
    assert "filesrc location=data/vtest.avi" in capsys.readouterr().out


def test_app_run_dispatches_resolved_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[AppConfig] = []

    def fake_run(config: AppConfig) -> int:
        captured.append(config)
        return 7

    monkeypatch.setattr(app_module, "run_pipeline", fake_run)

    assert app_module.main(["run", "-c", "config.example.yaml"]) == 7
    assert captured[0].source == FileSourceConfig(Path("data/vtest.avi"), rate=10)


def test_console_module_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bt_gst.app", "version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "0.0.1"


def test_resolve_config_accepts_empty_override() -> None:
    config = resolve_config(
        AppConfig(source=FileSourceConfig(Path("video.avi"))),
        AppConfigOverrides(),
    )
    assert config.source == FileSourceConfig(Path("video.avi"))

import subprocess
import sys
from pathlib import Path

import pytest
from bt_msgs import TrackerResultMessage

from bt_gst import app as app_module
from bt_gst.cli import RunCommand, ShowCommand, VersionCommand, parse_args
from bt_gst.config import (
    AppConfig,
    AppConfigOverrides,
    CameraSourceConfig,
    ConfigError,
    DetectorConfig,
    FileSourceConfig,
    SimulationSourceConfig,
    SelectorZmqConfig,
    ZmqConfig,
    load_config_overrides,
    resolve_config,
    validate_config,
)
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.pipeline_runner import (
    _WarningRateLimiter,
    _on_detection_overlay_draw,
    _on_detector_buffer,
)
from bt_gst.red_detection import (
    GST_CLOCK_TIME_NONE,
    DetectionOverlayState,
    DetectionBox,
    RedDetection,
    read_red_detection,
)


@pytest.fixture
def file_config_path(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "source:\n  type: file\n  path: video.avi\n  rate: 10\n",
        encoding="utf-8",
    )
    return config_path


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


def test_detector_pipeline_contains_plugin_and_overlay_without_appsink() -> None:
    pipeline = build_pipeline_description(
        AppConfig(
            source=SimulationSourceConfig("/camera"),
            detector=DetectorConfig(enabled=True, overlay_enabled=True),
            video_local=False,
        )
    )

    assert "controlledreddetect name=red_detector" in pipeline
    assert "cairooverlay name=detection_overlay" in pipeline
    assert "appsink" not in pipeline


def test_detector_accepts_wrapped_red_hue_range() -> None:
    config = validate_config(
        AppConfig(
            source=SimulationSourceConfig("/camera"),
            detector=DetectorConfig(
                enabled=True,
                low_h=170,
                low_s=80,
                low_v=60,
                high_h=10,
                minimum_area=10,
            ),
        )
    )

    pipeline = build_pipeline_description(config)

    assert "low-h=170" in pipeline
    assert "high-h=10" in pipeline
    assert "minimum-area=10" in pipeline


def test_loads_and_resolves_zmq_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "source:\n  type: file\n  path: video.avi\n"
        "detector:\n  enabled: true\n"
        "zmq:\n"
        "  enabled: true\n"
        "  endpoint: tcp://127.0.0.1:6000\n"
        "  bind: false\n"
        "  max_rate_hz: 12\n",
        encoding="utf-8",
    )

    config = resolve_config(AppConfig(), load_config_overrides(config_path))

    assert config.zmq == ZmqConfig(
        enabled=True,
        endpoint="tcp://127.0.0.1:6000",
        bind=False,
        max_rate_hz=12,
    )


def test_loads_selector_zmq_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "source:\n  type: file\n  path: video.avi\n"
        "selector_zmq:\n  endpoint: tcp://127.0.0.1:6001\n"
        "  bind: true\n  command_timeout_s: 0.8\n",
        encoding="utf-8",
    )
    config = resolve_config(AppConfig(), load_config_overrides(config_path))
    assert config.selector_zmq == SelectorZmqConfig(
        enabled=True,
        endpoint="tcp://127.0.0.1:6001",
        bind=True,
        command_timeout_s=0.8,
    )


def test_zmq_requires_enabled_detector() -> None:
    with pytest.raises(ConfigError, match="requires detector.enabled"):
        validate_config(
            AppConfig(
                source=FileSourceConfig(Path("video.avi")),
                zmq=ZmqConfig(enabled=True),
            )
        )


def test_overlay_matches_detection_timestamp() -> None:
    state = DetectionOverlayState()
    detection = RedDetection(True, 1, 2, 3, 4, 123)
    state.update(detection)

    assert state.detection_for_timestamp(123) == detection
    assert state.detection_for_timestamp(124) is None


class RecordingDrawContext:
    def __init__(self) -> None:
        self.rectangle_args: tuple[float, float, float, float] | None = None
        self.stroke_called = False
        self.colors = []
        self.rectangles = []

    def set_source_rgba(self, *rgba: float) -> None:
        self.colors.append(rgba)

    def set_line_width(self, _width: float) -> None:
        return

    def rectangle(self, *args: float) -> None:
        self.rectangle_args = args
        self.rectangles.append(args)

    def stroke(self) -> None:
        self.stroke_called = True


def test_detection_overlay_draws_matching_detection() -> None:
    state = DetectionOverlayState()
    state.update(RedDetection(True, 10, 20, 30, 40, 123))
    context = RecordingDrawContext()

    _on_detection_overlay_draw(None, context, 123, 0, state)

    assert context.rectangle_args == (11.5, 21.5, 27.0, 37.0)
    assert context.stroke_called


def test_detection_overlay_colors_candidates_and_selector():
    state = DetectionOverlayState()
    state.update(
        RedDetection(
            True, 10, 20, 30, 40, 123,
            selector=DetectionBox(5, 6, 80, 80),
            selector_valid=True,
            selector_state=1,
            candidates=(DetectionBox(10, 20, 30, 40), DetectionBox(100, 20, 30, 40)),
        )
    )
    context = RecordingDrawContext()

    _on_detection_overlay_draw(None, context, 123, 0, state)

    assert context.colors == [
        (0.0, 0.0, 1.0, 1.0),
        (0.0, 0.0, 1.0, 1.0),
        (0.0, 1.0, 0.0, 1.0),
        (0.0, 1.0, 0.0, 1.0),
    ]
    assert len(context.rectangles) == 4


def test_detection_overlay_hides_selector_when_target_is_locked():
    state = DetectionOverlayState()
    state.update(
        RedDetection(
            True, 10, 20, 30, 40, 123,
            selector=DetectionBox(5, 6, 80, 80),
            selector_valid=True,
            selector_state=2,
        )
    )
    context = RecordingDrawContext()

    _on_detection_overlay_draw(None, context, 123, 0, state)

    assert context.colors == [(0.0, 1.0, 0.0, 1.0)]
    assert len(context.rectangles) == 1


class FakeStructure:
    def __init__(self, found: bool = True) -> None:
        self.values = {
            "found": found,
            "x": 1 if found else 0,
            "y": 2 if found else 0,
            "width": 3 if found else 0,
            "height": 4 if found else 0,
            "selector-x": 0,
            "selector-y": 0,
            "selector-width": 0,
            "selector-height": 0,
            "selector-valid": False,
            "selector-state": 0,
            "candidate-count": 0,
        }

    def get_value(self, name: str) -> object:
        return self.values[name]


class FakeMeta:
    def __init__(self, found: bool = True) -> None:
        self.found = found

    def get_structure(self) -> FakeStructure:
        return FakeStructure(self.found)


class FakeBuffer:
    def __init__(
        self, pts: int, has_meta: bool = True, found: bool = True
    ) -> None:
        self.pts = pts
        self.has_meta = has_meta
        self.found = found
        self.meta_reads = 0

    def get_custom_meta(self, _name: str) -> FakeMeta | None:
        self.meta_reads += 1
        return FakeMeta(self.found) if self.has_meta else None


def test_read_red_detection_handles_timestamp_and_missing_meta() -> None:
    assert read_red_detection(FakeBuffer(10)) == RedDetection(True, 1, 2, 3, 4, 10)
    assert read_red_detection(FakeBuffer(GST_CLOCK_TIME_NONE)).pts_ns is None
    assert read_red_detection(FakeBuffer(10, has_meta=False)) is None


class FakeProbeInfo:
    def __init__(self, buffer: FakeBuffer) -> None:
        self.buffer = buffer

    def get_buffer(self) -> FakeBuffer:
        return self.buffer


class FakePublisher:
    def __init__(self) -> None:
        self.messages: list[TrackerResultMessage] = []

    def publish(self, message: TrackerResultMessage) -> None:
        self.messages.append(message)


class FakeGst:
    class PadProbeReturn:
        OK = object()


def test_detector_probe_updates_overlay_and_only_notifies_publisher() -> None:
    overlay_state = DetectionOverlayState()
    publisher = FakePublisher()
    buffer = FakeBuffer(123)

    result = _on_detector_buffer(
        None,
        FakeProbeInfo(buffer),
        (
            overlay_state,
            publisher,
            iter(range(1, 100)),
            _WarningRateLimiter(),
            FakeGst,
        ),
    )

    assert overlay_state.detection_for_timestamp(123) == RedDetection(
        True, 1, 2, 3, 4, 123
    )
    assert publisher.messages == [
        TrackerResultMessage(
            frame_id=1,
            timestamp_ns=123,
            locked=True,
            bbox_x=1,
            bbox_y=2,
            bbox_width=3,
            bbox_height=4,
        )
    ]
    assert buffer.meta_reads == 1
    assert result is FakeGst.PadProbeReturn.OK


def test_detector_probe_publishes_sequential_frame_messages() -> None:
    publisher = FakePublisher()
    frame_ids = iter(range(1, 100))

    _on_detector_buffer(
        None,
        FakeProbeInfo(FakeBuffer(100)),
        (None, publisher, frame_ids, _WarningRateLimiter(), FakeGst),
    )
    _on_detector_buffer(
        None,
        FakeProbeInfo(FakeBuffer(GST_CLOCK_TIME_NONE)),
        (None, publisher, frame_ids, _WarningRateLimiter(), FakeGst),
    )

    assert publisher.messages == [
        TrackerResultMessage(
            frame_id=1,
            timestamp_ns=100,
            locked=True,
            bbox_x=1,
            bbox_y=2,
            bbox_width=3,
            bbox_height=4,
        ),
        TrackerResultMessage(
            frame_id=2,
            timestamp_ns=None,
            locked=True,
            bbox_x=1,
            bbox_y=2,
            bbox_width=3,
            bbox_height=4,
        ),
    ]


def test_detector_probe_skips_missing_metadata_and_preserves_frame_gap() -> None:
    publisher = FakePublisher()
    frame_ids = iter(range(1, 100))
    warning_limiter = _WarningRateLimiter()

    _on_detector_buffer(
        None,
        FakeProbeInfo(FakeBuffer(100, has_meta=False)),
        (None, publisher, frame_ids, warning_limiter, FakeGst),
    )
    _on_detector_buffer(
        None,
        FakeProbeInfo(FakeBuffer(200)),
        (None, publisher, frame_ids, warning_limiter, FakeGst),
    )

    assert [message.frame_id for message in publisher.messages] == [2]


def test_detector_probe_publishes_unlocked_zero_box_when_not_found() -> None:
    publisher = FakePublisher()

    _on_detector_buffer(
        None,
        FakeProbeInfo(FakeBuffer(100, found=False)),
        (
            None,
            publisher,
            iter(range(1, 100)),
            _WarningRateLimiter(),
            FakeGst,
        ),
    )

    assert publisher.messages == [
        TrackerResultMessage(frame_id=1, timestamp_ns=100)
    ]


def test_missing_metadata_warning_limiter_allows_one_warning_per_interval() -> None:
    limiter = _WarningRateLimiter(interval_s=5.0)

    assert limiter.ready(now=10.0)
    assert not limiter.ready(now=14.999)
    assert limiter.ready(now=15.0)


def test_cli_parses_commands(file_config_path: Path) -> None:
    assert isinstance(parse_args(["version"]), VersionCommand)
    assert isinstance(parse_args(["show", "-c", str(file_config_path)]), ShowCommand)
    assert isinstance(parse_args(["run", "-c", str(file_config_path)]), RunCommand)


def test_cli_rejects_source_options_without_source() -> None:
    assert parse_args(["show", "--topic", "/camera"]) != 0


def test_app_show_prints_pipeline(
    file_config_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert app_module.main(["show", "-c", str(file_config_path)]) == 0
    assert "filesrc location=video.avi" in capsys.readouterr().out


def test_app_run_dispatches_resolved_config(
    file_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AppConfig] = []

    def fake_run(config: AppConfig) -> int:
        captured.append(config)
        return 7

    monkeypatch.setattr(app_module, "run_pipeline", fake_run)

    assert app_module.main(["run", "-c", str(file_config_path)]) == 7
    assert captured[0].source == FileSourceConfig(Path("video.avi"), rate=10)


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

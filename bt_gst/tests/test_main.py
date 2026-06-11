import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import bt_gst.main as main_module
from bt_gst.cli import DEFAULT_VIDEO, PlayCommand, VersionCommand, parse_args
from bt_gst.main import (
    GST_PLUGIN_PATH,
    PlaybackError,
    TrackerMeta,
    _handle_bus_message,
    build_video_pipeline_description,
    configure_gst_plugin_path,
    main,
    play_video,
    read_tracker_meta,
)
from test_plugin_metadata import load_plugin_module


class NoopPublisher:
    def start(self) -> None:
        return None

    def publish(self, meta: TrackerMeta) -> None:
        return None

    def close(self) -> None:
        return None


def install_fake_gi(
    monkeypatch,
    gst: object | None = None,
    gtk: object | None = None,
) -> None:
    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")

    def require_version(_name: str, _version: str) -> None:
        return None

    gi.require_version = require_version
    repository.Gst = gst or types.SimpleNamespace(
        MessageType=types.SimpleNamespace(ERROR=1, EOS=2),
    )
    repository.GstApp = types.SimpleNamespace()
    repository.Gtk = gtk or types.SimpleNamespace()

    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)


def test_parse_version_command() -> None:
    assert parse_args(["version"]) == VersionCommand()


def test_parse_play_command_defaults_to_data_video() -> None:
    assert parse_args(["play"]) == PlayCommand(video=DEFAULT_VIDEO)


def test_parse_play_command_accepts_video_path() -> None:
    video = Path("data/vtest.avi")

    assert parse_args(["play", str(video)]) == PlayCommand(video=video)


def test_build_video_pipeline_description_uses_explicit_gtksink_pipeline() -> None:
    video = Path("data/video with spaces.avi")

    pipeline = build_video_pipeline_description(video)

    assert "filesrc" in pipeline
    assert "decodebin" in pipeline
    assert "videoconvert" in pipeline
    assert "btpassthrough" in pipeline
    assert "tee name=metadata_tee" in pipeline
    assert "queue" in pipeline
    assert "gtksink name=video_sink" in pipeline
    assert "appsink name=metadata_sink" in pipeline
    assert f'location="{video.resolve()}"' in pipeline


def test_read_tracker_meta_from_plugin_buffer() -> None:
    gi = pytest.importorskip("gi")

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    plugin = load_plugin_module()
    element = plugin.BtPassThrough()
    buffer = Gst.Buffer.new_allocate(None, 4, None)

    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    assert read_tracker_meta(buffer) == TrackerMeta(dx=0, dy=0, score=1.0)


def test_configure_gst_plugin_path_sets_plugin_folder(monkeypatch) -> None:
    monkeypatch.delenv("GST_PLUGIN_PATH", raising=False)

    configure_gst_plugin_path()

    assert os.environ["GST_PLUGIN_PATH"] == str(GST_PLUGIN_PATH)


def test_configure_gst_plugin_path_preserves_existing_entries(monkeypatch) -> None:
    existing_path = os.pathsep.join(["/tmp/gst-a", "/tmp/gst-b"])
    monkeypatch.setenv("GST_PLUGIN_PATH", existing_path)

    configure_gst_plugin_path()

    assert os.environ["GST_PLUGIN_PATH"] == os.pathsep.join(
        [str(GST_PLUGIN_PATH), existing_path]
    )


def test_handle_bus_message_raises_playback_error(monkeypatch) -> None:
    install_fake_gi(monkeypatch)

    class Error:
        message = "decoder failed"

    class Message:
        type = 1

        def parse_error(self) -> tuple[Error, str]:
            return Error(), "debug details"

    with pytest.raises(PlaybackError, match="decoder failed") as exc_info:
        _handle_bus_message(Message())

    assert "debug details" in str(exc_info.value)


def test_main_returns_error_when_playback_fails(monkeypatch, tmp_path, capsys) -> None:
    video = tmp_path / "video.avi"
    video.write_bytes(b"")

    def fail_playback(video_path: Path) -> None:
        raise PlaybackError(f"failed to play {video_path.name}")

    monkeypatch.setattr(main_module, "play_video", fail_playback)

    assert main(["play", str(video)]) == 1

    captured = capsys.readouterr()
    assert "failed to play video.avi" in captured.err


def test_console_parse_error_returns_nonzero() -> None:
    project_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "bt_gst.main", "play", "missing-video.avi"],
        check=False,
        capture_output=True,
        cwd=project_dir,
        text=True,
    )

    assert result.returncode != 0


def test_play_video_cleans_up_pipeline_when_loop_raises(monkeypatch, tmp_path) -> None:
    video = tmp_path / "video.avi"
    video.write_bytes(b"")

    class FakeSink:
        def get_property(self, name: str) -> object:
            assert name == "widget"
            return object()

    class FakeMetadataSink:
        def try_pull_sample(self, timeout: int) -> None:
            return None

    class FakeBus:
        def timed_pop_filtered(self, timeout: int, message_types: int) -> None:
            return None

    class FakePipeline:
        def __init__(self) -> None:
            self.states: list[str] = []

        def get_by_name(self, name: str) -> object | None:
            if name == "video_sink":
                return FakeSink()
            if name == "metadata_sink":
                return FakeMetadataSink()
            return None

        def get_bus(self) -> FakeBus:
            return FakeBus()

        def set_state(self, state: str) -> str:
            self.states.append(state)
            return "SUCCESS"

    class FakeWindow:
        def __init__(self, title: str) -> None:
            self.title = title

        def set_default_size(self, width: int, height: int) -> None:
            return None

        def connect(self, signal: str, callback: object) -> None:
            return None

        def add(self, widget: object) -> None:
            return None

        def show_all(self) -> None:
            return None

    pipeline = FakePipeline()
    gst = types.SimpleNamespace(
        MSECOND=1,
        MessageType=types.SimpleNamespace(ERROR=1, EOS=2),
        State=types.SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
        StateChangeReturn=types.SimpleNamespace(FAILURE="FAILURE"),
        init=lambda args: None,
        parse_launch=lambda description: pipeline,
    )
    gtk = types.SimpleNamespace(
        Window=FakeWindow,
        init=lambda args: None,
        events_pending=lambda: (_ for _ in ()).throw(RuntimeError("loop failed")),
        main_iteration=lambda: None,
    )
    install_fake_gi(monkeypatch, gst=gst, gtk=gtk)
    monkeypatch.setattr(main_module, "TrackerMetaPublisher", NoopPublisher)

    with pytest.raises(RuntimeError, match="loop failed"):
        play_video(video)

    assert pipeline.states == ["PLAYING", "NULL"]


def test_play_video_raises_when_pipeline_fails_to_start(monkeypatch, tmp_path) -> None:
    video = tmp_path / "video.avi"
    video.write_bytes(b"")

    class FakeSink:
        def get_property(self, name: str) -> object:
            assert name == "widget"
            return object()

    class FakeMetadataSink:
        pass

    class FakeBus:
        pass

    class FakePipeline:
        def __init__(self) -> None:
            self.states: list[str] = []

        def get_by_name(self, name: str) -> object | None:
            if name == "video_sink":
                return FakeSink()
            if name == "metadata_sink":
                return FakeMetadataSink()
            return None

        def get_bus(self) -> FakeBus:
            return FakeBus()

        def set_state(self, state: str) -> str:
            self.states.append(state)
            if state == "PLAYING":
                return "FAILURE"
            return "SUCCESS"

    class FakeWindow:
        def __init__(self, title: str) -> None:
            self.title = title

        def set_default_size(self, width: int, height: int) -> None:
            return None

        def connect(self, signal: str, callback: object) -> None:
            return None

        def add(self, widget: object) -> None:
            return None

        def show_all(self) -> None:
            return None

    pipeline = FakePipeline()
    gst = types.SimpleNamespace(
        MessageType=types.SimpleNamespace(ERROR=1, EOS=2),
        State=types.SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
        StateChangeReturn=types.SimpleNamespace(FAILURE="FAILURE"),
        init=lambda args: None,
        parse_launch=lambda description: pipeline,
    )
    gtk = types.SimpleNamespace(
        Window=FakeWindow,
        init=lambda args: None,
    )
    install_fake_gi(monkeypatch, gst=gst, gtk=gtk)
    monkeypatch.setattr(main_module, "TrackerMetaPublisher", NoopPublisher)

    with pytest.raises(PlaybackError, match="failed to start"):
        play_video(video)

    assert pipeline.states == ["PLAYING", "NULL"]


def test_play_video_publishes_tracker_meta_and_closes_publisher(monkeypatch, tmp_path) -> None:
    video = tmp_path / "video.avi"
    video.write_bytes(b"")
    published: list[TrackerMeta] = []
    events: list[str] = []

    class FakePublisher:
        def start(self) -> None:
            events.append("start")

        def publish(self, meta: TrackerMeta) -> None:
            published.append(meta)

        def close(self) -> None:
            events.append("close")

    class FakeSink:
        def get_property(self, name: str) -> object:
            assert name == "widget"
            return object()

    class FakeSample:
        def get_buffer(self) -> object:
            return object()

    class FakeMetadataSink:
        def __init__(self) -> None:
            self._pulled = False

        def try_pull_sample(self, timeout: int) -> FakeSample | None:
            if self._pulled:
                return None
            self._pulled = True
            return FakeSample()

    class FakeMessage:
        type = 2

    class FakeBus:
        def __init__(self) -> None:
            self._calls = 0

        def timed_pop_filtered(self, timeout: int, message_types: int) -> FakeMessage | None:
            self._calls += 1
            if self._calls == 1:
                return None
            return FakeMessage()

    class FakePipeline:
        def __init__(self) -> None:
            self.states: list[str] = []
            self.metadata_sink = FakeMetadataSink()
            self.bus = FakeBus()

        def get_by_name(self, name: str) -> object | None:
            if name == "video_sink":
                return FakeSink()
            if name == "metadata_sink":
                return self.metadata_sink
            return None

        def get_bus(self) -> FakeBus:
            return self.bus

        def set_state(self, state: str) -> str:
            self.states.append(state)
            return "SUCCESS"

    class FakeWindow:
        def __init__(self, title: str) -> None:
            self.title = title

        def set_default_size(self, width: int, height: int) -> None:
            return None

        def connect(self, signal: str, callback: object) -> None:
            return None

        def add(self, widget: object) -> None:
            return None

        def show_all(self) -> None:
            return None

    pipeline = FakePipeline()
    gst = types.SimpleNamespace(
        MSECOND=1,
        MessageType=types.SimpleNamespace(ERROR=1, EOS=2),
        State=types.SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
        StateChangeReturn=types.SimpleNamespace(FAILURE="FAILURE"),
        init=lambda args: None,
        parse_launch=lambda description: pipeline,
    )
    gtk = types.SimpleNamespace(
        Window=FakeWindow,
        init=lambda args: None,
        events_pending=lambda: False,
        main_iteration=lambda: None,
    )
    install_fake_gi(monkeypatch, gst=gst, gtk=gtk)
    monkeypatch.setattr(main_module, "TrackerMetaPublisher", FakePublisher)
    monkeypatch.setattr(
        main_module,
        "read_tracker_meta",
        lambda buffer: TrackerMeta(dx=3, dy=4, score=0.5),
    )

    play_video(video)

    assert events == ["start", "close"]
    assert published == [TrackerMeta(dx=3, dy=4, score=0.5)]
    assert pipeline.states == ["PLAYING", "NULL"]


def test_play_video_maps_publisher_start_failure_to_playback_error(
    monkeypatch,
    tmp_path,
) -> None:
    video = tmp_path / "video.avi"
    video.write_bytes(b"")

    class FailingPublisher(NoopPublisher):
        def start(self) -> None:
            raise main_module.ZmqPublisherError("bind failed")

    class FakeSink:
        def get_property(self, name: str) -> object:
            assert name == "widget"
            return object()

    class FakePipeline:
        def __init__(self) -> None:
            self.states: list[str] = []

        def get_by_name(self, name: str) -> object | None:
            if name == "video_sink":
                return FakeSink()
            if name == "metadata_sink":
                return object()
            return None

        def get_bus(self) -> object:
            return object()

        def set_state(self, state: str) -> str:
            self.states.append(state)
            return "SUCCESS"

    class FakeWindow:
        def __init__(self, title: str) -> None:
            self.title = title

        def set_default_size(self, width: int, height: int) -> None:
            return None

        def connect(self, signal: str, callback: object) -> None:
            return None

        def add(self, widget: object) -> None:
            return None

        def show_all(self) -> None:
            return None

    pipeline = FakePipeline()
    gst = types.SimpleNamespace(
        MessageType=types.SimpleNamespace(ERROR=1, EOS=2),
        State=types.SimpleNamespace(PLAYING="PLAYING", NULL="NULL"),
        StateChangeReturn=types.SimpleNamespace(FAILURE="FAILURE"),
        init=lambda args: None,
        parse_launch=lambda description: pipeline,
    )
    gtk = types.SimpleNamespace(
        Window=FakeWindow,
        init=lambda args: None,
    )
    install_fake_gi(monkeypatch, gst=gst, gtk=gtk)
    monkeypatch.setattr(main_module, "TrackerMetaPublisher", FailingPublisher)

    with pytest.raises(PlaybackError, match="bind failed"):
        play_video(video)

    assert pipeline.states == ["NULL"]


def test_console_version_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bt_gst.main", "version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "0.0.1"


def test_console_help_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "bt_gst.main", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "BT GStreamer command line utilities." in result.stdout

import os
import subprocess
import sys
from pathlib import Path

from bt_gst.cli import DEFAULT_VIDEO, PlayCommand, VersionCommand, parse_args
from bt_gst.main import (
    GST_PLUGIN_PATH,
    TrackerMeta,
    build_tracker_data_message,
    build_tracker_debug_message_from_structure,
    build_user_adjust_roi_request_structure,
    build_user_resize_roi_request_structure,
    build_user_stop_request_structure,
    build_video_pipeline_description,
    build_user_point_request_structure,
    configure_gst_plugin_path,
    dispatch_track_request,
    format_tracker_debug_message,
    format_tracker_debug_structure,
    format_video_click,
    _handle_bus_message,
    read_tracker_meta,
)
from bt_gst.optical_flow_tracker import (
    Roi,
    adjust_roi,
    build_centered_roi,
    resize_roi,
    STATUS_BREAK,
    STATUS_OFF,
    TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT,
    TRACKER_DEBUG_FIELD_FEATURES_JSON,
    TRACKER_DEBUG_FIELD_FRAME_NUMBER,
    TRACKER_DEBUG_FIELD_STATUS,
    TRACKER_DEBUG_MESSAGE_NAME,
    TRACK_REQUEST_FIELD_DELTA_X,
    TRACK_REQUEST_FIELD_DELTA_Y,
    TRACK_REQUEST_FIELD_HEIGHT,
    TRACK_REQUEST_FIELD_SOURCE,
    TRACK_REQUEST_FIELD_TYPE,
    TRACK_REQUEST_FIELD_WIDTH,
    TRACK_REQUEST_FIELD_X,
    TRACK_REQUEST_FIELD_Y,
    TRACK_REQUEST_NAME,
    TRACK_REQUEST_SOURCE_USER,
    TRACK_REQUEST_TYPE_ADJUST_ROI,
    TRACK_REQUEST_TYPE_POINT,
    TRACK_REQUEST_TYPE_RESIZE_ROI,
    TRACK_REQUEST_TYPE_STOP,
    compute_roi_offset,
    compute_tracker_score,
)
from bt_gst.zmq_models import (
    TrackAdjustmentRequest,
    TrackResizeRequest,
    TrackStartRequest,
    TrackStopRequest,
    TrackerDataMessage,
    TrackerDebugMessage,
)
from test_plugin_metadata import load_plugin_module


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
    assert "video/x-raw,format=RGBA" in pipeline
    assert "bt_optical_flow name=tracker" in pipeline
    assert "btpassthrough" not in pipeline
    assert "tee name=metadata_tee" in pipeline
    assert "queue" in pipeline
    assert "gtksink name=video_sink" in pipeline
    assert "appsink name=metadata_sink" in pipeline
    assert f'location="{video.resolve()}"' in pipeline


def test_build_centered_roi() -> None:
    assert build_centered_roi(
        x=50,
        y=40,
        size=80,
        frame_width=200,
        frame_height=100,
    ) == Roi(x=10, y=0, width=80, height=80)


def test_build_centered_roi_clamps_to_frame_edges() -> None:
    assert build_centered_roi(
        x=5,
        y=5,
        size=20,
        frame_width=100,
        frame_height=80,
    ) == Roi(x=0, y=0, width=20, height=20)


def test_resize_roi_grows_around_center() -> None:
    assert resize_roi(
        Roi(x=10, y=10, width=20, height=20),
        width=40,
        height=40,
        frame_width=100,
        frame_height=100,
    ) == Roi(x=0, y=0, width=40, height=40)


def test_resize_roi_shrinks_around_center() -> None:
    assert resize_roi(
        Roi(x=10, y=10, width=20, height=20),
        width=10,
        height=10,
        frame_width=100,
        frame_height=100,
    ) == Roi(x=15, y=15, width=10, height=10)


def test_resize_roi_clamps_to_frame_edges() -> None:
    assert resize_roi(
        Roi(x=80, y=80, width=20, height=20),
        width=40,
        height=40,
        frame_width=100,
        frame_height=100,
    ) == Roi(x=60, y=60, width=40, height=40)


def test_adjust_roi_moves_and_preserves_size() -> None:
    assert adjust_roi(
        Roi(x=10, y=10, width=20, height=30),
        delta_x=5,
        delta_y=-3,
        frame_width=100,
        frame_height=100,
    ) == Roi(x=15, y=7, width=20, height=30)


def test_adjust_roi_clamps_to_frame_edges() -> None:
    assert adjust_roi(
        Roi(x=10, y=10, width=20, height=20),
        delta_x=-50,
        delta_y=90,
        frame_width=100,
        frame_height=100,
    ) == Roi(x=0, y=80, width=20, height=20)


def test_compute_tracker_score_clamps_to_unit_range() -> None:
    assert compute_tracker_score(feature_count=0, max_corners=80) == 0.0
    assert compute_tracker_score(feature_count=20, max_corners=80) == 0.25
    assert compute_tracker_score(feature_count=100, max_corners=80) == 1.0
    assert compute_tracker_score(feature_count=10, max_corners=0) == 0.0


def test_compute_roi_offset_uses_frame_center() -> None:
    assert compute_roi_offset(
        Roi(x=40, y=20, width=20, height=20),
        frame_width=100,
        frame_height=100,
    ) == (0, 20)


def test_build_user_point_request_structure() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    structure = build_user_point_request_structure(Gst, 12, 34)

    assert structure.get_name() == TRACK_REQUEST_NAME
    assert structure.get_value(TRACK_REQUEST_FIELD_SOURCE) == TRACK_REQUEST_SOURCE_USER
    assert structure.get_value(TRACK_REQUEST_FIELD_TYPE) == TRACK_REQUEST_TYPE_POINT
    assert structure.get_value(TRACK_REQUEST_FIELD_X) == 12
    assert structure.get_value(TRACK_REQUEST_FIELD_Y) == 34


def test_build_user_stop_request_structure() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    structure = build_user_stop_request_structure(Gst)

    assert structure.get_name() == TRACK_REQUEST_NAME
    assert structure.get_value(TRACK_REQUEST_FIELD_SOURCE) == TRACK_REQUEST_SOURCE_USER
    assert structure.get_value(TRACK_REQUEST_FIELD_TYPE) == TRACK_REQUEST_TYPE_STOP


def test_build_user_resize_roi_request_structure() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    structure = build_user_resize_roi_request_structure(Gst, 90, 90)

    assert structure.get_name() == TRACK_REQUEST_NAME
    assert structure.get_value(TRACK_REQUEST_FIELD_SOURCE) == TRACK_REQUEST_SOURCE_USER
    assert structure.get_value(TRACK_REQUEST_FIELD_TYPE) == TRACK_REQUEST_TYPE_RESIZE_ROI
    assert structure.get_value(TRACK_REQUEST_FIELD_WIDTH) == 90
    assert structure.get_value(TRACK_REQUEST_FIELD_HEIGHT) == 90


def test_build_user_adjust_roi_request_structure() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    structure = build_user_adjust_roi_request_structure(Gst, -10, 10)

    assert structure.get_name() == TRACK_REQUEST_NAME
    assert structure.get_value(TRACK_REQUEST_FIELD_SOURCE) == TRACK_REQUEST_SOURCE_USER
    assert structure.get_value(TRACK_REQUEST_FIELD_TYPE) == TRACK_REQUEST_TYPE_ADJUST_ROI
    assert structure.get_value(TRACK_REQUEST_FIELD_DELTA_X) == -10
    assert structure.get_value(TRACK_REQUEST_FIELD_DELTA_Y) == 10


def test_read_tracker_meta_from_plugin_buffer() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    plugin = load_plugin_module()
    element = plugin.BtOpticalFlow()
    buffer = Gst.Buffer.new_allocate(None, 4, None)

    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    assert read_tracker_meta(buffer) == TrackerMeta(
        dx=0,
        dy=0,
        score=0.0,
        status=STATUS_BREAK,
    )


def test_read_tracker_meta_from_disabled_plugin_buffer() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    plugin = load_plugin_module()
    element = plugin.BtOpticalFlow()
    element.set_property("enabled", False)
    buffer = Gst.Buffer.new_allocate(None, 4, None)

    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    assert read_tracker_meta(buffer) == TrackerMeta(
        dx=0,
        dy=0,
        score=0.0,
        status=STATUS_OFF,
    )


def test_format_video_click() -> None:
    assert (
        format_video_click(x=10.5, y=20.0, button=1, width=960, height=540)
        == "video-click x=10.5 y=20.0 button=1 width=960 height=540"
    )


def test_build_tracker_data_message_uses_frame_id_and_timestamp() -> None:
    assert build_tracker_data_message(
        TrackerMeta(dx=1, dy=-2, score=0.75, status=1),
        frame_id=42,
        timestamp=123.5,
    ) == TrackerDataMessage(
        frame_id=42,
        timestamp=123.5,
        dx=1,
        dy=-2,
        score=0.75,
        status=1,
    )


def test_build_tracker_debug_message_from_structure() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    structure = Gst.Structure.new_empty(TRACKER_DEBUG_MESSAGE_NAME)
    structure.set_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER, 4)
    structure.set_value(TRACKER_DEBUG_FIELD_STATUS, 1)
    structure.set_value(TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT, 2)
    structure.set_value(TRACKER_DEBUG_FIELD_FEATURES_JSON, '[{"x":1.0,"y":2.0}]')

    assert build_tracker_debug_message_from_structure(structure) == TrackerDebugMessage(
        frame_number=4,
        status=1,
        active_feature_count=2,
        features_json='[{"x":1.0,"y":2.0}]',
    )


def test_dispatch_track_request_calls_existing_sender(monkeypatch) -> None:
    calls = []
    tracker = object()

    monkeypatch.setattr(
        "bt_gst.main.send_user_point_request",
        lambda tracker_arg, x, y: calls.append(("start", tracker_arg, x, y)) or True,
    )
    monkeypatch.setattr(
        "bt_gst.main.send_user_stop_request",
        lambda tracker_arg: calls.append(("stop", tracker_arg)) or True,
    )
    monkeypatch.setattr(
        "bt_gst.main.send_user_resize_roi_request",
        lambda tracker_arg, width, height: calls.append(
            ("resize", tracker_arg, width, height)
        )
        or True,
    )
    monkeypatch.setattr(
        "bt_gst.main.send_user_adjust_roi_request",
        lambda tracker_arg, delta_x, delta_y: calls.append(
            ("adjustment", tracker_arg, delta_x, delta_y)
        )
        or True,
    )

    assert dispatch_track_request(TrackStartRequest(x=1, y=2), tracker)
    assert dispatch_track_request(TrackStopRequest(), tracker)
    assert dispatch_track_request(TrackResizeRequest(width=30, height=40), tracker)
    assert dispatch_track_request(
        TrackAdjustmentRequest(delta_x=-5, delta_y=6),
        tracker,
    )
    assert calls == [
        ("start", tracker, 1, 2),
        ("stop", tracker),
        ("resize", tracker, 30, 40),
        ("adjustment", tracker, -5, 6),
    ]


def test_format_tracker_debug_message() -> None:
    assert (
        format_tracker_debug_message(
            frame_number=3,
            status=1,
            active_feature_count=2,
            features_json='[{"x":1.0,"y":2.0}]',
        )
        == 'bt-tracker-debug frame=3 status=1 active-feature-count=2 features=[{"x":1.0,"y":2.0}]'
    )


def test_format_tracker_debug_structure() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    structure = Gst.Structure.new_empty(TRACKER_DEBUG_MESSAGE_NAME)
    structure.set_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER, 4)
    structure.set_value(TRACKER_DEBUG_FIELD_STATUS, 2)
    structure.set_value(TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT, 0)
    structure.set_value(TRACKER_DEBUG_FIELD_FEATURES_JSON, "[]")

    assert (
        format_tracker_debug_structure(structure)
        == "bt-tracker-debug frame=4 status=2 active-feature-count=0 features=[]"
    )


def test_handle_bus_message_prints_tracker_debug(capsys) -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    structure = Gst.Structure.new_empty(TRACKER_DEBUG_MESSAGE_NAME)
    structure.set_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER, 4)
    structure.set_value(TRACKER_DEBUG_FIELD_STATUS, 2)
    structure.set_value(TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT, 0)
    structure.set_value(TRACKER_DEBUG_FIELD_FEATURES_JSON, "[]")
    message = Gst.Message.new_element(None, structure)

    assert _handle_bus_message(message, object()) is False
    assert (
        capsys.readouterr().out.strip()
        == "bt-tracker-debug frame=4 status=2 active-feature-count=0 features=[]"
    )


def test_handle_bus_message_publishes_tracker_debug(capsys) -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    class Adapter:
        def __init__(self) -> None:
            self.messages = []

        def publish_tracker_debug(self, message: TrackerDebugMessage) -> None:
            self.messages.append(message)

    adapter = Adapter()
    structure = Gst.Structure.new_empty(TRACKER_DEBUG_MESSAGE_NAME)
    structure.set_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER, 5)
    structure.set_value(TRACKER_DEBUG_FIELD_STATUS, 1)
    structure.set_value(TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT, 3)
    structure.set_value(TRACKER_DEBUG_FIELD_FEATURES_JSON, "[]")
    message = Gst.Message.new_element(None, structure)

    assert _handle_bus_message(message, object(), adapter) is False
    assert adapter.messages == [
        TrackerDebugMessage(
            frame_number=5,
            status=1,
            active_feature_count=3,
            features_json="[]",
        )
    ]
    assert (
        capsys.readouterr().out.strip()
        == "bt-tracker-debug frame=5 status=1 active-feature-count=3 features=[]"
    )


def test_handle_bus_message_ignores_unrelated_element_message(capsys) -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    message = Gst.Message.new_element(None, Gst.Structure.new_empty("other-message"))

    assert _handle_bus_message(message, object()) is False
    assert capsys.readouterr().out == ""


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

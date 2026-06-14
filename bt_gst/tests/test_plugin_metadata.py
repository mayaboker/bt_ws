import json
import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest

from bt_gst import optical_flow_tracker


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "plugins" / "python" / "gstbt_optical_flow.py"
)


@lru_cache
def load_plugin_module():
    spec = importlib.util.spec_from_file_location("gstbt_optical_flow", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_track_request_event(gst, request_type: str, **values):
    structure = gst.Structure.new_empty(optical_flow_tracker.TRACK_REQUEST_NAME)
    structure.set_value(
        optical_flow_tracker.TRACK_REQUEST_FIELD_SOURCE,
        optical_flow_tracker.TRACK_REQUEST_SOURCE_USER,
    )
    structure.set_value(optical_flow_tracker.TRACK_REQUEST_FIELD_TYPE, request_type)
    for name, value in values.items():
        structure.set_value(name, value)
    return gst.Event.new_custom(gst.EventType.CUSTOM_DOWNSTREAM, structure)


def make_tracking_frame(width: int = 40, height: int = 40, shift_x: int = 0, shift_y: int = 0):
    np = pytest.importorskip("numpy")
    frame = np.zeros((height, width, 4), dtype=np.uint8)
    frame[..., 3] = 255
    for x, y in ((10, 10), (24, 10), (10, 24), (24, 24), (17, 17)):
        x0 = x + shift_x
        y0 = y + shift_y
        frame[y0 : y0 + 4, x0 : x0 + 4, 0:3] = 255
    return frame


def make_rgba_buffer(gst, frame):
    buffer = gst.Buffer.new_allocate(None, frame.nbytes, None)
    buffer.fill(0, frame.tobytes())
    return buffer


def configure_tracking_properties(element: object) -> None:
    element.set_property(optical_flow_tracker.PROP_REQUEST_SEARCH_SIZE, 30)
    element.set_property(optical_flow_tracker.PROP_MAX_CORNERS, 30)
    element.set_property(optical_flow_tracker.PROP_MIN_FEATURES, 4)
    element.set_property(optical_flow_tracker.PROP_MIN_DISTANCE_PX, 2.0)
    element.set_property(optical_flow_tracker.PROP_BLOCK_SIZE, 3)
    element.set_property(optical_flow_tracker.PROP_LK_WINDOW_SIZE, 15)


def add_element_to_pipeline(gst, element: object):
    pipeline = gst.Pipeline.new(None)
    pipeline.add(element)
    return pipeline


def pop_element_message(gst, pipeline: object):
    return pipeline.get_bus().pop_filtered(gst.MessageType.ELEMENT)


def test_plugin_exports_tracker_meta_definition() -> None:
    module = load_plugin_module()

    assert module.__gstelementfactory__[0] == "bt_optical_flow"
    assert module.META_NAME == optical_flow_tracker.META_NAME
    assert module.G_TYPE_INT == 24
    assert module.G_TYPE_FLOAT == 56
    assert optical_flow_tracker.STATUS_OFF == 0
    assert optical_flow_tracker.STATUS_TRACK == 1
    assert optical_flow_tracker.STATUS_BREAK == 2
    assert optical_flow_tracker.PROP_DEBUG == "debug"
    assert optical_flow_tracker.DEFAULT_DEBUG is False
    assert optical_flow_tracker.TRACKER_DEBUG_MESSAGE_NAME == "bt-tracker-debug"


def test_plugin_exposes_metadata_helpers() -> None:
    module = load_plugin_module()

    assert callable(module.set_meta_int)
    assert callable(module.set_meta_float)


def test_plugin_exposes_default_properties() -> None:
    module = load_plugin_module()
    element = module.BtOpticalFlow()

    assert element.get_property(optical_flow_tracker.PROP_ENABLED) is True
    assert element.get_property(optical_flow_tracker.PROP_DEBUG) is False
    assert (
        element.get_property(optical_flow_tracker.PROP_MAX_CORNERS)
        == optical_flow_tracker.DEFAULT_MAX_CORNERS
    )
    assert (
        element.get_property(optical_flow_tracker.PROP_REQUEST_SEARCH_SIZE)
        == optical_flow_tracker.DEFAULT_REQUEST_SEARCH_SIZE
    )


def test_plugin_point_request_stores_active_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_REQUEST_SEARCH_SIZE, 4)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=8,height=8")
    structure = Gst.Structure.new_empty(optical_flow_tracker.TRACK_REQUEST_NAME)
    structure.set_value(
        optical_flow_tracker.TRACK_REQUEST_FIELD_SOURCE,
        optical_flow_tracker.TRACK_REQUEST_SOURCE_USER,
    )
    structure.set_value(
        optical_flow_tracker.TRACK_REQUEST_FIELD_TYPE,
        optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
    )
    structure.set_value(optical_flow_tracker.TRACK_REQUEST_FIELD_X, 4)
    structure.set_value(optical_flow_tracker.TRACK_REQUEST_FIELD_Y, 4)

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        Gst.Event.new_custom(Gst.EventType.CUSTOM_DOWNSTREAM, structure)
    )
    assert element._active_roi == optical_flow_tracker.Roi(x=2, y=2, width=4, height=4)


def test_plugin_stop_request_clears_active_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element._pending_point = (4, 4)
    element._active_roi = optical_flow_tracker.Roi(x=2, y=2, width=4, height=4)
    element._previous_gray = object()
    element._feature_points = object()
    element._needs_feature_init = True

    assert element.do_sink_event(
        make_track_request_event(Gst, optical_flow_tracker.TRACK_REQUEST_TYPE_STOP)
    )
    assert element._pending_point is None
    assert element._active_roi is None
    assert element._previous_gray is None
    assert element._feature_points is None
    assert element._needs_feature_init is False


def test_plugin_resize_request_updates_active_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=20,height=20")
    element._active_roi = optical_flow_tracker.Roi(x=6, y=6, width=4, height=4)

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_RESIZE_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_WIDTH: 8,
                optical_flow_tracker.TRACK_REQUEST_FIELD_HEIGHT: 8,
            },
        )
    )
    assert element._active_roi == optical_flow_tracker.Roi(x=4, y=4, width=8, height=8)
    assert element._needs_feature_init is True


def test_plugin_resize_request_ignored_without_active_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=20,height=20")

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_RESIZE_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_WIDTH: 8,
                optical_flow_tracker.TRACK_REQUEST_FIELD_HEIGHT: 8,
            },
        )
    )
    assert element._active_roi is None


def test_plugin_adjust_request_updates_active_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=20,height=20")
    element._active_roi = optical_flow_tracker.Roi(x=6, y=6, width=4, height=4)

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_ADJUST_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_X: 3,
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_Y: -2,
            },
        )
    )
    assert element._active_roi == optical_flow_tracker.Roi(x=9, y=4, width=4, height=4)
    assert element._needs_feature_init is True


def test_plugin_adjust_request_ignored_without_active_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=20,height=20")

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_ADJUST_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_X: 3,
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_Y: -2,
            },
        )
    )
    assert element._active_roi is None


def test_plugin_draws_adjusted_roi() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=8,height=8")
    element._active_roi = optical_flow_tracker.Roi(x=1, y=1, width=3, height=3)
    buffer = Gst.Buffer.new_allocate(None, 8 * 8 * 4, None)
    buffer.fill(0, bytes(8 * 8 * 4))

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_ADJUST_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_X: 2,
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_Y: 1,
            },
        )
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    data = buffer.extract_dup(0, 8 * 8 * 4)
    old_top_left_offset = ((1 * 8) + 1) * 4
    new_top_left_offset = ((2 * 8) + 3) * 4
    assert data[old_top_left_offset : old_top_left_offset + 4] == bytes((0, 0, 0, 0))
    assert data[new_top_left_offset : new_top_left_offset + 4] == bytes((255, 0, 0, 255))


def test_plugin_draws_roi_and_keeps_break_status() -> None:
    import gi

    from bt_gst.main import read_tracker_meta

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_REQUEST_SEARCH_SIZE, 4)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=8,height=8")
    structure = Gst.Structure.new_empty(optical_flow_tracker.TRACK_REQUEST_NAME)
    structure.set_value(
        optical_flow_tracker.TRACK_REQUEST_FIELD_SOURCE,
        optical_flow_tracker.TRACK_REQUEST_SOURCE_USER,
    )
    structure.set_value(
        optical_flow_tracker.TRACK_REQUEST_FIELD_TYPE,
        optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
    )
    structure.set_value(optical_flow_tracker.TRACK_REQUEST_FIELD_X, 4)
    structure.set_value(optical_flow_tracker.TRACK_REQUEST_FIELD_Y, 4)
    buffer = Gst.Buffer.new_allocate(None, 8 * 8 * 4, None)
    buffer.fill(0, bytes(8 * 8 * 4))

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        Gst.Event.new_custom(Gst.EventType.CUSTOM_DOWNSTREAM, structure)
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    data = buffer.extract_dup(0, 8 * 8 * 4)
    top_left_offset = ((2 * 8) + 2) * 4
    inside_offset = ((3 * 8) + 3) * 4
    assert data[top_left_offset : top_left_offset + 4] == bytes((255, 0, 0, 255))
    assert data[inside_offset : inside_offset + 4] == bytes((0, 0, 0, 0))
    assert read_tracker_meta(buffer).status == optical_flow_tracker.STATUS_BREAK


def test_plugin_point_request_initializes_features_and_tracks() -> None:
    pytest.importorskip("cv2")
    import gi

    from bt_gst.main import read_tracker_meta

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    configure_tracking_properties(element)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    buffer = make_rgba_buffer(Gst, make_tracking_frame())

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_X: 20,
                optical_flow_tracker.TRACK_REQUEST_FIELD_Y: 20,
            },
        )
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    meta = read_tracker_meta(buffer)
    assert meta is not None
    assert meta.status == optical_flow_tracker.STATUS_TRACK
    assert meta.dx == 0
    assert meta.dy == 0
    assert 0.0 < meta.score <= 1.0
    assert element._feature_points is not None


def test_plugin_too_few_features_emits_break() -> None:
    pytest.importorskip("cv2")
    import gi

    from bt_gst.main import read_tracker_meta

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    configure_tracking_properties(element)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    buffer = Gst.Buffer.new_allocate(None, 40 * 40 * 4, None)
    buffer.fill(0, bytes(40 * 40 * 4))

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_X: 20,
                optical_flow_tracker.TRACK_REQUEST_FIELD_Y: 20,
            },
        )
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    meta = read_tracker_meta(buffer)
    assert meta is not None
    assert meta.status == optical_flow_tracker.STATUS_BREAK
    assert element._feature_points is None


def test_plugin_shifted_frame_moves_roi_and_updates_offset() -> None:
    pytest.importorskip("cv2")
    import gi

    from bt_gst.main import read_tracker_meta

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    configure_tracking_properties(element)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    first = make_rgba_buffer(Gst, make_tracking_frame())
    second = make_rgba_buffer(Gst, make_tracking_frame(shift_x=3, shift_y=2))

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_X: 20,
                optical_flow_tracker.TRACK_REQUEST_FIELD_Y: 20,
            },
        )
    )
    assert element.do_transform_ip(first) == Gst.FlowReturn.OK
    initial_roi = element._active_roi
    assert initial_roi is not None
    assert element.do_transform_ip(second) == Gst.FlowReturn.OK

    meta = read_tracker_meta(second)
    assert meta is not None
    assert meta.status == optical_flow_tracker.STATUS_TRACK
    assert element._active_roi is not None
    assert element._active_roi.x > initial_roi.x
    assert element._active_roi.y > initial_roi.y
    assert meta.dx > 0
    assert meta.dy < 0


def test_plugin_track_features_drops_points_outside_moved_roi(monkeypatch: pytest.MonkeyPatch) -> None:
    np = pytest.importorskip("numpy")

    module = load_plugin_module()

    class FakeCv2:
        TERM_CRITERIA_EPS = 1
        TERM_CRITERIA_COUNT = 2

        def calcOpticalFlowPyrLK(self, *_args, **_kwargs):
            next_points = np.array(
                [
                    [[14.0, 14.0]],
                    [[16.0, 16.0]],
                    [[18.0, 18.0]],
                    [[20.0, 20.0]],
                    [[35.0, 35.0]],
                ],
                dtype=np.float32,
            )
            status = np.ones((5, 1), dtype=np.uint8)
            return next_points, status, None

    monkeypatch.setattr(module, "load_cv_modules", lambda: (FakeCv2(), np))
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_MIN_FEATURES, 4)
    element._frame_width = 40
    element._frame_height = 40
    element._active_roi = optical_flow_tracker.Roi(x=10, y=10, width=10, height=10)
    element._previous_gray = np.zeros((40, 40), dtype=np.uint8)
    element._feature_points = np.array(
        [
            [[12.0, 12.0]],
            [[14.0, 14.0]],
            [[16.0, 16.0]],
            [[18.0, 18.0]],
            [[19.0, 19.0]],
        ],
        dtype=np.float32,
    )

    _dx, _dy, _score, status = element._track_features(np.zeros((40, 40), dtype=np.uint8))

    assert status == optical_flow_tracker.STATUS_TRACK
    assert element._active_roi == optical_flow_tracker.Roi(x=12, y=12, width=10, height=10)
    assert element._feature_points is not None
    assert element._feature_points.shape == (4, 1, 2)
    assert [point[0].tolist() for point in element._feature_points] == [
        [14.0, 14.0],
        [16.0, 16.0],
        [18.0, 18.0],
        [20.0, 20.0],
    ]


def test_plugin_track_features_breaks_when_roi_filter_leaves_too_few_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    np = pytest.importorskip("numpy")

    module = load_plugin_module()

    class FakeCv2:
        TERM_CRITERIA_EPS = 1
        TERM_CRITERIA_COUNT = 2

        def calcOpticalFlowPyrLK(self, *_args, **_kwargs):
            next_points = np.array(
                [
                    [[14.0, 14.0]],
                    [[16.0, 16.0]],
                    [[18.0, 18.0]],
                    [[35.0, 35.0]],
                ],
                dtype=np.float32,
            )
            status = np.ones((4, 1), dtype=np.uint8)
            return next_points, status, None

    monkeypatch.setattr(module, "load_cv_modules", lambda: (FakeCv2(), np))
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_MIN_FEATURES, 4)
    element._frame_width = 40
    element._frame_height = 40
    element._active_roi = optical_flow_tracker.Roi(x=10, y=10, width=10, height=10)
    element._previous_gray = np.zeros((40, 40), dtype=np.uint8)
    element._feature_points = np.array(
        [
            [[12.0, 12.0]],
            [[14.0, 14.0]],
            [[16.0, 16.0]],
            [[19.0, 19.0]],
        ],
        dtype=np.float32,
    )

    _dx, _dy, _score, status = element._track_features(np.zeros((40, 40), dtype=np.uint8))

    assert status == optical_flow_tracker.STATUS_BREAK
    assert element._feature_points is None
    assert element._active_roi == optical_flow_tracker.Roi(x=10, y=10, width=10, height=10)


def test_plugin_debug_false_posts_no_debug_message() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    pipeline = add_element_to_pipeline(Gst, element)
    buffer = Gst.Buffer.new_allocate(None, 4, None)

    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    assert pop_element_message(Gst, pipeline) is None


def test_plugin_debug_true_posts_break_message() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_DEBUG, True)
    pipeline = add_element_to_pipeline(Gst, element)
    buffer = Gst.Buffer.new_allocate(None, 4, None)

    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    message = pop_element_message(Gst, pipeline)
    assert message is not None
    structure = message.get_structure()
    assert structure.get_name() == optical_flow_tracker.TRACKER_DEBUG_MESSAGE_NAME
    assert (
        structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_FRAME_NUMBER)
        == 1
    )
    assert structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_STATUS) == 2
    assert (
        structure.get_value(
            optical_flow_tracker.TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT
        )
        == 0
    )
    assert structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_FEATURES_JSON) == "[]"


def test_plugin_debug_true_posts_off_message_when_disabled() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_DEBUG, True)
    element.set_property(optical_flow_tracker.PROP_ENABLED, False)
    pipeline = add_element_to_pipeline(Gst, element)
    buffer = Gst.Buffer.new_allocate(None, 4, None)

    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    message = pop_element_message(Gst, pipeline)
    assert message is not None
    structure = message.get_structure()
    assert structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_STATUS) == 0
    assert (
        structure.get_value(
            optical_flow_tracker.TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT
        )
        == 0
    )
    assert structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_FEATURES_JSON) == "[]"


def test_plugin_debug_true_posts_track_message_with_features() -> None:
    pytest.importorskip("cv2")
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_DEBUG, True)
    configure_tracking_properties(element)
    pipeline = add_element_to_pipeline(Gst, element)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    buffer = make_rgba_buffer(Gst, make_tracking_frame())

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_X: 20,
                optical_flow_tracker.TRACK_REQUEST_FIELD_Y: 20,
            },
        )
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    message = pop_element_message(Gst, pipeline)
    assert message is not None
    structure = message.get_structure()
    assert structure.get_name() == optical_flow_tracker.TRACKER_DEBUG_MESSAGE_NAME
    assert (
        structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_FRAME_NUMBER)
        == 1
    )
    assert structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_STATUS) == 1
    assert (
        structure.get_value(
            optical_flow_tracker.TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT
        )
        > 0
    )
    features = json.loads(
        structure.get_value(optical_flow_tracker.TRACKER_DEBUG_FIELD_FEATURES_JSON)
    )
    assert features
    assert {"x", "y"} == set(features[0])


def test_plugin_debug_frame_numbers_increase_monotonically() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_DEBUG, True)
    pipeline = add_element_to_pipeline(Gst, element)

    for _ in range(2):
        buffer = Gst.Buffer.new_allocate(None, 4, None)
        assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    first = pop_element_message(Gst, pipeline)
    second = pop_element_message(Gst, pipeline)
    assert first is not None
    assert second is not None
    assert (
        first.get_structure().get_value(
            optical_flow_tracker.TRACKER_DEBUG_FIELD_FRAME_NUMBER
        )
        == 1
    )
    assert (
        second.get_structure().get_value(
            optical_flow_tracker.TRACKER_DEBUG_FIELD_FRAME_NUMBER
        )
        == 2
    )


def test_plugin_debug_draws_green_feature_marks() -> None:
    pytest.importorskip("cv2")
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_DEBUG, True)
    configure_tracking_properties(element)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    buffer = make_rgba_buffer(Gst, make_tracking_frame())

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_X: 20,
                optical_flow_tracker.TRACK_REQUEST_FIELD_Y: 20,
            },
        )
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    assert element._feature_points is not None

    point = element._feature_points[0]
    x = round(float(point[0][0]))
    y = round(float(point[0][1]))
    data = buffer.extract_dup(0, 40 * 40 * 4)
    offset = ((y * 40) + x) * 4
    assert data[offset : offset + 4] == bytes((0, 255, 0, 255))


def test_plugin_debug_draws_yellow_roi_and_green_features() -> None:
    pytest.importorskip("cv2")
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_DEBUG, True)
    configure_tracking_properties(element)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    buffer = make_rgba_buffer(Gst, make_tracking_frame())

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_POINT,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_X: 20,
                optical_flow_tracker.TRACK_REQUEST_FIELD_Y: 20,
            },
        )
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK
    assert element._active_roi is not None
    assert element._feature_points is not None

    data = buffer.extract_dup(0, 40 * 40 * 4)
    roi_offset = ((element._active_roi.y * 40) + element._active_roi.x) * 4
    feature = element._feature_points[0]
    feature_x = round(float(feature[0][0]))
    feature_y = round(float(feature[0][1]))
    feature_offset = ((feature_y * 40) + feature_x) * 4
    assert data[roi_offset : roi_offset + 4] == bytes((255, 255, 0, 255))
    assert data[feature_offset : feature_offset + 4] == bytes((0, 255, 0, 255))


def test_plugin_resize_and_adjust_mark_feature_reacquisition() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=40,height=40")
    element._active_roi = optical_flow_tracker.Roi(x=10, y=10, width=20, height=20)
    element._previous_gray = object()
    element._feature_points = object()
    element._needs_feature_init = False

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_RESIZE_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_WIDTH: 22,
                optical_flow_tracker.TRACK_REQUEST_FIELD_HEIGHT: 22,
            },
        )
    )
    assert element._previous_gray is None
    assert element._feature_points is None
    assert element._needs_feature_init is True

    element._previous_gray = object()
    element._feature_points = object()
    element._needs_feature_init = False
    assert element.do_sink_event(
        make_track_request_event(
            Gst,
            optical_flow_tracker.TRACK_REQUEST_TYPE_ADJUST_ROI,
            **{
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_X: 1,
                optical_flow_tracker.TRACK_REQUEST_FIELD_DELTA_Y: 1,
            },
        )
    )
    assert element._previous_gray is None
    assert element._feature_points is None
    assert element._needs_feature_init is True


def test_disabled_plugin_does_not_draw_roi() -> None:
    import gi

    from bt_gst.main import read_tracker_meta

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element.set_property(optical_flow_tracker.PROP_REQUEST_SEARCH_SIZE, 4)
    element.set_property(optical_flow_tracker.PROP_ENABLED, False)
    element._active_roi = optical_flow_tracker.Roi(x=2, y=2, width=4, height=4)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=8,height=8")
    buffer = Gst.Buffer.new_allocate(None, 8 * 8 * 4, None)
    buffer.fill(0, bytes(8 * 8 * 4))

    assert element.do_set_caps(caps, caps) is True
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    data = buffer.extract_dup(0, 8 * 8 * 4)
    assert data == bytes(8 * 8 * 4)
    assert read_tracker_meta(buffer).status == optical_flow_tracker.STATUS_OFF


def test_plugin_stop_request_prevents_roi_drawing() -> None:
    import gi

    from bt_gst.main import read_tracker_meta

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_plugin_module()
    element = module.BtOpticalFlow()
    element._active_roi = optical_flow_tracker.Roi(x=2, y=2, width=4, height=4)
    caps = Gst.Caps.from_string("video/x-raw,format=RGBA,width=8,height=8")
    buffer = Gst.Buffer.new_allocate(None, 8 * 8 * 4, None)
    buffer.fill(0, bytes(8 * 8 * 4))

    assert element.do_set_caps(caps, caps) is True
    assert element.do_sink_event(
        make_track_request_event(Gst, optical_flow_tracker.TRACK_REQUEST_TYPE_STOP)
    )
    assert element.do_transform_ip(buffer) == Gst.FlowReturn.OK

    data = buffer.extract_dup(0, 8 * 8 * 4)
    assert data == bytes(8 * 8 * 4)
    assert read_tracker_meta(buffer).status == optical_flow_tracker.STATUS_BREAK

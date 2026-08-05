from bt_gst.bridge.zmq_models import (
    TrackAdjustmentRequest,
    TrackResizeRequest,
    TrackStartRequest,
    TrackStopRequest,
)
from bt_gst.red_detection import CursorRoi, TrackerCursorState


def test_cursor_request_lifecycle_and_bounds() -> None:
    state = TrackerCursorState(frame_width=100, frame_height=80)

    state.apply(TrackStartRequest(x=50, y=40))
    assert state.snapshot() == CursorRoi(35, 25, 30, 30)

    state.apply(TrackAdjustmentRequest(delta_x=-100, delta_y=100))
    assert state.snapshot() == CursorRoi(0, 50, 30, 30)

    state.apply(TrackResizeRequest(width=200, height=10))
    assert state.snapshot() == CursorRoi(0, 60, 100, 10)

    state.apply(TrackStopRequest())
    assert state.snapshot() is None


def test_adjustment_and_resize_before_start_are_ignored() -> None:
    state = TrackerCursorState(frame_width=640, frame_height=480)
    state.apply(TrackAdjustmentRequest(delta_x=5, delta_y=3))
    state.apply(TrackResizeRequest(width=50, height=50))
    assert state.snapshot() is None

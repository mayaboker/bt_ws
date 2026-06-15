#region imports
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from loguru import logger

from bt_gst import __version__
from bt_gst.cli import PlayCommand, VersionCommand, parse_args
from bt_gst.optical_flow_tracker import (
    DEFAULT_REQUEST_SEARCH_SIZE,
    DEFAULT_ROI_ADJUST_STEP_PX,
    DEFAULT_ROI_RESIZE_STEP_PX,
    META_NAME,
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
)
from bt_gst.zmq_io import TrackerIoAdapter, ZmqTrackerIoAdapter
from bt_gst.zmq_models import (
    TrackAdjustmentRequest,
    TrackResizeRequest,
    TrackStartRequest,
    TrackStopRequest,
    TrackerDataMessage,
    TrackerDebugMessage,
)
#endregion imports

# region constants
DEFAULT_VIDEO = Path(__file__).resolve().parents[1] / "data" / "vtest.avi"
GST_PLUGIN_PATH = Path(__file__).resolve().parents[1] / "plugins"
TRACKER_META_NAME = META_NAME
SYNTHETIC_VIDEO_WIDTH = 640
SYNTHETIC_VIDEO_HEIGHT = 480
SYNTHETIC_VIDEO_FPS = 20
# endregion constants

@dataclass
class TrackerUiState:
    roi_size: int = DEFAULT_REQUEST_SEARCH_SIZE


@dataclass(frozen=True)
class TrackerMeta:
    dx: int
    dy: int
    score: float
    status: int


@dataclass(frozen=True)
class SyntheticFrameTiming:
    pts: int
    dts: int
    duration: int


class SyntheticVideoSource:
    def __init__(
        self,
        appsrc: object,
        gst: object,
        *,
        width: int = SYNTHETIC_VIDEO_WIDTH,
        height: int = SYNTHETIC_VIDEO_HEIGHT,
        fps: int = SYNTHETIC_VIDEO_FPS,
    ) -> None:
        self._appsrc = appsrc
        self._gst = gst
        self._width = width
        self._height = height
        self._fps = fps
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def frame_interval_seconds(self) -> float:
        return 1.0 / float(self._fps)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="bt-gst-synthetic-video-source",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._appsrc.emit("end-of-stream")

    def _run(self) -> None:
        frame_index = 0
        next_frame_at = time.monotonic()
        while not self._stop_event.is_set():
            frame = generate_synthetic_rgba_frame(
                frame_index,
                width=self._width,
                height=self._height,
            )
            timing = build_synthetic_frame_timing(
                frame_index,
                fps=self._fps,
                gst_second=self._gst.SECOND,
            )
            buffer = self._gst.Buffer.new_allocate(None, len(frame), None)
            buffer.fill(0, frame)
            buffer.pts = timing.pts
            buffer.dts = timing.dts
            buffer.duration = timing.duration
            flow_return = self._appsrc.emit("push-buffer", buffer)
            if flow_return != self._gst.FlowReturn.OK:
                logger.warning("synthetic frame push stopped flow_return={}", flow_return)
                break

            frame_index += 1
            next_frame_at += self.frame_interval_seconds
            sleep_seconds = next_frame_at - time.monotonic()
            if sleep_seconds > 0:
                self._stop_event.wait(sleep_seconds)

# region user event
def on_video_click(
    video_widget: object,
    event: object,
    tracker: object | None = None,
    state: TrackerUiState | None = None,
) -> bool:
    allocation = video_widget.get_allocation()
    logger.info(
        "video click received x={} y={} button={} widget_width={} widget_height={}",
        event.x,
        event.y,
        event.button,
        allocation.width,
        allocation.height,
    )
    print_video_click(event, allocation.width, allocation.height)
    if tracker is not None:
        if state is not None:
            state.roi_size = DEFAULT_REQUEST_SEARCH_SIZE
        send_user_point_request(tracker, int(event.x), int(event.y))
    return False


def on_key_press(
    window: object,
    event: object,
    tracker: object,
    state: TrackerUiState,
) -> bool:
    from gi.repository import Gdk

    key_name = Gdk.keyval_name(event.keyval)
    if key_name == "Escape":
        send_user_stop_request(tracker)
        return False
    if key_name in {"plus", "KP_Add", "equal"}:
        state.roi_size += DEFAULT_ROI_RESIZE_STEP_PX
        send_user_resize_roi_request(tracker, state.roi_size, state.roi_size)
        return False
    if key_name in {"minus", "KP_Subtract"}:
        state.roi_size = max(1, state.roi_size - DEFAULT_ROI_RESIZE_STEP_PX)
        send_user_resize_roi_request(tracker, state.roi_size, state.roi_size)
        return False
    if key_name in {"Left", "KP_Left"}:
        send_user_adjust_roi_request(tracker, -DEFAULT_ROI_ADJUST_STEP_PX, 0)
        return False
    if key_name in {"Right", "KP_Right"}:
        send_user_adjust_roi_request(tracker, DEFAULT_ROI_ADJUST_STEP_PX, 0)
        return False
    if key_name in {"Up", "KP_Up"}:
        send_user_adjust_roi_request(tracker, 0, -DEFAULT_ROI_ADJUST_STEP_PX)
        return False
    if key_name in {"Down", "KP_Down"}:
        send_user_adjust_roi_request(tracker, 0, DEFAULT_ROI_ADJUST_STEP_PX)
        return False
    return False

#endregion user event

def main(argv: Sequence[str] | None = None) -> int:
    command = parse_args(argv)
    if isinstance(command, int):
        return command
    if isinstance(command, VersionCommand):
        print(__version__)
        return 0
    if isinstance(command, PlayCommand):
        play_video(command.video)
        return 0
    raise RuntimeError(f"unsupported command: {command!r}")


def build_synthetic_frame_timing(
    frame_index: int,
    *,
    fps: int = SYNTHETIC_VIDEO_FPS,
    gst_second: int,
) -> SyntheticFrameTiming:
    duration = int(gst_second) // int(fps)
    timestamp = int(frame_index) * duration
    return SyntheticFrameTiming(pts=timestamp, dts=timestamp, duration=duration)


def synthetic_target_position(
    frame_index: int,
    *,
    width: int = SYNTHETIC_VIDEO_WIDTH,
    height: int = SYNTHETIC_VIDEO_HEIGHT,
    target_size: int = 80,
) -> tuple[int, int]:
    max_x = width - target_size - 40
    max_y = height - target_size - 40
    travel_x = max(1, max_x - 40)
    travel_y = max(1, max_y - 40)
    period_x = travel_x * 2
    period_y = travel_y * 2
    phase_x = (frame_index * 2) % period_x
    phase_y = frame_index % period_y
    offset_x = phase_x if phase_x <= travel_x else period_x - phase_x
    offset_y = phase_y if phase_y <= travel_y else period_y - phase_y
    return 40 + offset_x, 40 + offset_y


def generate_synthetic_rgba_frame(
    frame_index: int,
    *,
    width: int = SYNTHETIC_VIDEO_WIDTH,
    height: int = SYNTHETIC_VIDEO_HEIGHT,
) -> bytes:
    import numpy as np

    frame = np.zeros((height, width, 4), dtype=np.uint8)
    frame[..., 0:3] = 18
    frame[..., 3] = 255

    grid_color = np.array([42, 42, 42], dtype=np.uint8)
    frame[::40, :, 0:3] = grid_color
    frame[:, ::40, 0:3] = grid_color

    target_size = 80
    x, y = synthetic_target_position(
        frame_index,
        width=width,
        height=height,
        target_size=target_size,
    )
    x2 = x + target_size
    y2 = y + target_size
    frame[y:y2, x:x2, 0:3] = 60
    frame[y : y + 4, x:x2, 0:3] = 255
    frame[y2 - 4 : y2, x:x2, 0:3] = 255
    frame[y:y2, x : x + 4, 0:3] = 255
    frame[y:y2, x2 - 4 : x2, 0:3] = 255

    feature_offsets = (
        (16, 16),
        (56, 16),
        (16, 56),
        (56, 56),
        (36, 36),
    )
    for dx, dy in feature_offsets:
        fx = x + dx
        fy = y + dy
        frame[fy : fy + 8, fx : fx + 8, 0:3] = (255, 255, 255)

    return frame.tobytes()


def build_video_pipeline_description(video_path: Path) -> str:
    return (
        "appsrc name=video_source is-live=true format=time block=true "
        'do-timestamp=false caps="video/x-raw,format=RGBA,'
        f"width={SYNTHETIC_VIDEO_WIDTH},height={SYNTHETIC_VIDEO_HEIGHT},"
        f'framerate={SYNTHETIC_VIDEO_FPS}/1" ! '
        "bt_optical_flow name=tracker debug=false ! "
        "tee name=metadata_tee "
        "metadata_tee. ! queue ! videoconvert ! gtksink name=video_sink sync=true qos=true "
        "metadata_tee. ! queue leaky=downstream max-size-buffers=1 ! "
        "appsink name=metadata_sink emit-signals=false sync=false max-buffers=1 drop=true"
    )


def configure_gst_plugin_path() -> None:
    plugin_path = str(GST_PLUGIN_PATH)
    existing_path = os.environ.get("GST_PLUGIN_PATH")
    if not existing_path:
        os.environ["GST_PLUGIN_PATH"] = plugin_path
        return

    paths = existing_path.split(os.pathsep)
    if plugin_path not in paths:
        os.environ["GST_PLUGIN_PATH"] = os.pathsep.join([plugin_path, *paths])


def play_video(video_path: Path = DEFAULT_VIDEO) -> None:
    configure_gst_plugin_path()

    try:
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("GstApp", "1.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, Gst, GstApp, Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "GStreamer Python bindings are unavailable. Install PyGObject and "
            "the native GStreamer/Gtk introspection packages."
        ) from exc

    Gst.init(None)
    Gtk.init(None)

    pipeline_description = build_video_pipeline_description(video_path)
    pipeline = Gst.parse_launch(pipeline_description)

    sink = pipeline.get_by_name("video_sink")
    if sink is None:
        raise RuntimeError(
            "GStreamer element 'gtksink' was not found. Install the GTK "
            "GStreamer plugin package, usually gst-plugins-good."
        )

    #region pipe elements
    metadata_sink = pipeline.get_by_name("metadata_sink")
    if metadata_sink is None:
        raise RuntimeError("GStreamer element 'metadata_sink' was not found.")

    video_source = pipeline.get_by_name("video_source")
    if video_source is None:
        raise RuntimeError("GStreamer element 'video_source' was not found.")

    tracker = pipeline.get_by_name("tracker")
    if tracker is None:
        raise RuntimeError("GStreamer element 'tracker' was not found.")
    #endregion pipe elements
    
    running = True
    tracker_state = TrackerUiState()
    tracker_data_frame_id = 0
    io_adapter: TrackerIoAdapter = ZmqTrackerIoAdapter()

    def close_window(window: object) -> None:
        nonlocal running
        running = False

    #region window and event setup
    video_widget = sink.get_property("widget")
    video_widget.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    video_widget.connect("button-press-event", on_video_click, tracker, tracker_state)

    window = Gtk.Window(title=f"bt-gst: {video_path.name}")
    # window.set_default_size(960, 540)
    window.set_default_size(SYNTHETIC_VIDEO_WIDTH, SYNTHETIC_VIDEO_HEIGHT)

    window.connect("destroy", close_window)
    window.connect("key-press-event", on_key_press, tracker, tracker_state)
    window.add(video_widget)
    window.show_all()
    # endregion window and event setup

    bus = pipeline.get_bus()
    synthetic_source = SyntheticVideoSource(video_source, Gst)

    pipeline.set_state(Gst.State.PLAYING)
    synthetic_source.start()
    try:
        # main loop
        while running:
            while Gtk.events_pending():
                Gtk.main_iteration()

            #region poll track request and send to tracker
            track_request = io_adapter.poll_latest_request()
            if track_request is not None:
                dispatch_track_request(track_request, tracker)
            #endregion poll track request and send to tracker

            #region handle bus messages
            message = bus.timed_pop_filtered(
                10_000_000,
                Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.ELEMENT,
            )
            if message is not None and _handle_bus_message(
                message,
                pipeline,
                io_adapter,
            ):
                break
            # endregion handle bus messages

            # region pull metadata sample and publish tracker data
            # try_pull_sample data from the tracker metadata sink, if available, and publish it via the IO adapter
            sample = pull_metadata_sample(metadata_sink, 10 * Gst.MSECOND)
            if sample is None:
                continue

            buffer = sample.get_buffer()
            if buffer is None:
                continue

            tracker_meta = read_tracker_meta(buffer)
            if tracker_meta is None:
                continue

            tracker_data_frame_id += 1
            # publish tracker data via the IO adapter
            io_adapter.publish_tracker_data(
                build_tracker_data_message(
                    tracker_meta,
                    frame_id=tracker_data_frame_id,
                )
            )
            # endregion pull metadata sample and publish tracker data

    finally:
        synthetic_source.stop()
        pipeline.set_state(Gst.State.NULL)
        io_adapter.close()


def format_video_click(
    x: float,
    y: float,
    button: int,
    width: int,
    height: int,
) -> str:
    return f"video-click x={x:.1f} y={y:.1f} button={button} width={width} height={height}"


def print_video_click(event: object, width: int, height: int) -> None:
    print(format_video_click(event.x, event.y, event.button, width, height))

# region user track request
def build_user_point_request_structure(gst: object, x: int, y: int) -> object:
    structure = gst.Structure.new_empty(TRACK_REQUEST_NAME)
    structure.set_value(TRACK_REQUEST_FIELD_SOURCE, TRACK_REQUEST_SOURCE_USER)
    structure.set_value(TRACK_REQUEST_FIELD_TYPE, TRACK_REQUEST_TYPE_POINT)
    structure.set_value(TRACK_REQUEST_FIELD_X, int(x))
    structure.set_value(TRACK_REQUEST_FIELD_Y, int(y))
    return structure


def build_user_stop_request_structure(gst: object) -> object:
    structure = gst.Structure.new_empty(TRACK_REQUEST_NAME)
    structure.set_value(TRACK_REQUEST_FIELD_SOURCE, TRACK_REQUEST_SOURCE_USER)
    structure.set_value(TRACK_REQUEST_FIELD_TYPE, TRACK_REQUEST_TYPE_STOP)
    return structure


def build_user_resize_roi_request_structure(
    gst: object,
    width: int,
    height: int,
) -> object:
    structure = gst.Structure.new_empty(TRACK_REQUEST_NAME)
    structure.set_value(TRACK_REQUEST_FIELD_SOURCE, TRACK_REQUEST_SOURCE_USER)
    structure.set_value(TRACK_REQUEST_FIELD_TYPE, TRACK_REQUEST_TYPE_RESIZE_ROI)
    structure.set_value(TRACK_REQUEST_FIELD_WIDTH, int(width))
    structure.set_value(TRACK_REQUEST_FIELD_HEIGHT, int(height))
    return structure


def build_user_adjust_roi_request_structure(
    gst: object,
    delta_x: int,
    delta_y: int,
) -> object:
    structure = gst.Structure.new_empty(TRACK_REQUEST_NAME)
    structure.set_value(TRACK_REQUEST_FIELD_SOURCE, TRACK_REQUEST_SOURCE_USER)
    structure.set_value(TRACK_REQUEST_FIELD_TYPE, TRACK_REQUEST_TYPE_ADJUST_ROI)
    structure.set_value(TRACK_REQUEST_FIELD_DELTA_X, int(delta_x))
    structure.set_value(TRACK_REQUEST_FIELD_DELTA_Y, int(delta_y))
    return structure
#endregion user track request

# region send tracker event
def send_tracker_event(tracker: object, structure: object) -> bool:
    from gi.repository import Gst

    event = Gst.Event.new_custom(Gst.EventType.CUSTOM_DOWNSTREAM, structure)
    sink_pad = tracker.get_static_pad("sink")
    if sink_pad is None:
        logger.warning("track request dropped reason=no-sink-pad")
        return False
    return bool(sink_pad.send_event(event))


def send_user_point_request(tracker: object, x: int, y: int) -> bool:
    from gi.repository import Gst

    structure = build_user_point_request_structure(Gst, x, y)
    sent = send_tracker_event(tracker, structure)
    logger.info("track request sent x={} y={} sent={}", x, y, sent)
    return sent


def send_user_stop_request(tracker: object) -> bool:
    from gi.repository import Gst

    structure = build_user_stop_request_structure(Gst)
    sent = send_tracker_event(tracker, structure)
    logger.info("track stop request sent={}", sent)
    return sent


def send_user_resize_roi_request(tracker: object, width: int, height: int) -> bool:
    from gi.repository import Gst

    structure = build_user_resize_roi_request_structure(Gst, width, height)
    sent = send_tracker_event(tracker, structure)
    logger.info("track resize request sent width={} height={} sent={}", width, height, sent)
    return sent


def send_user_adjust_roi_request(tracker: object, delta_x: int, delta_y: int) -> bool:
    from gi.repository import Gst

    structure = build_user_adjust_roi_request_structure(Gst, delta_x, delta_y)
    sent = send_tracker_event(tracker, structure)
    logger.info(
        "track adjust request sent delta_x={} delta_y={} sent={}",
        delta_x,
        delta_y,
        sent,
    )
    return sent
#endregion send tracker event

def pull_metadata_sample(metadata_sink: object, timeout: int) -> object | None:
    if hasattr(metadata_sink, "try_pull_sample"):
        return metadata_sink.try_pull_sample(timeout)
    return metadata_sink.emit("try-pull-sample", timeout)


def read_tracker_meta(buffer: object) -> TrackerMeta | None:
    meta = buffer.get_custom_meta(TRACKER_META_NAME)
    if meta is None:
        return None

    structure = meta.get_structure()
    return TrackerMeta(
        dx=structure.get_value("dx"),
        dy=structure.get_value("dy"),
        score=structure.get_value("score"),
        status=structure.get_value("status"),
    )


def print_tracker_meta(meta: TrackerMeta) -> None:
    print(
        f"{TRACKER_META_NAME} dx={meta.dx} dy={meta.dy} "
        f"score={meta.score} status={meta.status}"
    )


def build_tracker_data_message(
    meta: TrackerMeta,
    *,
    frame_id: int,
    timestamp: float | None = None,
) -> TrackerDataMessage:
    return TrackerDataMessage(
        frame_id=frame_id,
        timestamp=time.time() if timestamp is None else timestamp,
        dx=meta.dx,
        dy=meta.dy,
        score=meta.score,
        status=meta.status,
    )


def build_tracker_debug_message_from_structure(structure: object) -> TrackerDebugMessage:
    return TrackerDebugMessage(
        frame_number=structure.get_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER),
        status=structure.get_value(TRACKER_DEBUG_FIELD_STATUS),
        active_feature_count=structure.get_value(
            TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT
        ),
        features_json=structure.get_value(TRACKER_DEBUG_FIELD_FEATURES_JSON),
    )


def dispatch_track_request(request: object, tracker: object) -> bool:
    if isinstance(request, TrackStartRequest):
        return send_user_point_request(tracker, request.x, request.y)
    if isinstance(request, TrackStopRequest):
        return send_user_stop_request(tracker)
    if isinstance(request, TrackResizeRequest):
        return send_user_resize_roi_request(tracker, request.width, request.height)
    if isinstance(request, TrackAdjustmentRequest):
        return send_user_adjust_roi_request(tracker, request.delta_x, request.delta_y)
    logger.warning("ignored unsupported track request request={}", request)
    return False


def format_tracker_debug_message(
    frame_number: int,
    status: int,
    active_feature_count: int,
    features_json: str,
) -> str:
    return (
        f"{TRACKER_DEBUG_MESSAGE_NAME} frame={frame_number} status={status} "
        f"active-feature-count={active_feature_count} features={features_json}"
    )


def format_tracker_debug_structure(structure: object) -> str:
    return format_tracker_debug_message(
        frame_number=structure.get_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER),
        status=structure.get_value(TRACKER_DEBUG_FIELD_STATUS),
        active_feature_count=structure.get_value(
            TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT
        ),
        features_json=structure.get_value(TRACKER_DEBUG_FIELD_FEATURES_JSON),
    )


def _handle_bus_message(
    message: object,
    pipeline: object,
    io_adapter: TrackerIoAdapter | None = None,
) -> bool:
    from gi.repository import Gst

    if message.type == Gst.MessageType.ERROR:
        error, debug = message.parse_error()
        print(f"GStreamer error: {error.message}", file=sys.stderr)
        if debug:
            print(debug, file=sys.stderr)
        pipeline.set_state(Gst.State.NULL)
        return True
    elif message.type == Gst.MessageType.EOS:
        pipeline.set_state(Gst.State.NULL)
        return True
    elif message.type == Gst.MessageType.ELEMENT:
        structure = message.get_structure()
        if structure is not None and structure.get_name() == TRACKER_DEBUG_MESSAGE_NAME:
            print(format_tracker_debug_structure(structure))
            if io_adapter is not None:
                io_adapter.publish_tracker_debug(
                    build_tracker_debug_message_from_structure(structure)
                )
        return False
    return False


if __name__ == "__main__":
    main()

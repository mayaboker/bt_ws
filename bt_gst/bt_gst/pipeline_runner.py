import threading
from dataclasses import dataclass, field

from loguru import logger

from bt_gst.bridge.zmq_io import (
    DetectionIoAdapter,
    NullDetectionIoAdapter,
    ZmqDetectionIoAdapter,
)
from bt_gst.bridge.zmq_models import (
    RedDetectionMessage,
    TrackStartRequest,
    TrackStopRequest,
)
from bt_gst.config import AppConfig
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.red_detection import (
    DetectionCursorState,
    DetectionOverlayState,
    RedDetection,
    read_red_detection,
)

pipeline_runner_logger = logger.bind(component="bt_gst.pipeline_runner")


class PipelineRunError(RuntimeError):
    """Raised when a GStreamer pipeline cannot be run."""


@dataclass
class DetectorLockState:
    acquire_frames: int = 10
    lose_frames: int = 5
    _active: bool = False
    _locked: bool = False
    _found_frames: int = 0
    _missing_frames: int = 0
    _mutex: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def apply_request(self, request: object) -> None:
        with self._mutex:
            if isinstance(request, TrackStartRequest):
                self._active = True
                self._locked = False
                self._found_frames = 0
                self._missing_frames = 0
            elif isinstance(request, TrackStopRequest):
                self._active = False
                self._locked = False
                self._found_frames = 0
                self._missing_frames = 0

    def update(self, found: bool) -> tuple[bool, int, int]:
        with self._mutex:
            if not self._active:
                return False, 0, 0
            if found:
                self._missing_frames = 0
                self._found_frames = min(
                    self.acquire_frames,
                    self._found_frames + 1,
                )
                if self._found_frames >= self.acquire_frames:
                    self._locked = True
            else:
                self._found_frames = 0
                self._missing_frames = min(
                    self.lose_frames,
                    self._missing_frames + 1,
                )
                if self._missing_frames >= self.lose_frames:
                    self._locked = False
            return self._locked, self._found_frames, self._missing_frames


@dataclass
class DetectionTelemetryState:
    publisher: DetectionIoAdapter
    lock_state: DetectorLockState = field(default_factory=DetectorLockState)
    next_frame_id: int = 1
    last_locked: bool = False

    def publish(self, detection: RedDetection) -> None:
        locked, found_frames, missing_frames = self.lock_state.update(detection.found)
        if locked != self.last_locked:
            pipeline_runner_logger.info(
                "red detector lock changed locked={} frame={} found_frames={} "
                "missing_frames={}",
                locked,
                self.next_frame_id,
                found_frames,
                missing_frames,
            )
            self.last_locked = locked
        self.publisher.publish_red_detection(
            RedDetectionMessage(
                frame_id=self.next_frame_id,
                timestamp_ns=detection.pts_ns,
                found=detection.found,
                x=detection.x,
                y=detection.y,
                width=detection.width,
                height=detection.height,
                locked=locked,
                lock_found_frames=found_frames,
                lock_missing_frames=missing_frames,
            )
        )
        self.next_frame_id += 1


def run_pipeline(config: AppConfig) -> int:
    pipeline_description = build_pipeline_description(config)
    pipeline_runner_logger.info(
        "starting GStreamer pipeline pipeline={}", pipeline_description
    )
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise PipelineRunError(
            "GStreamer Python bindings are unavailable. Install PyGObject and "
            "the native GStreamer introspection packages."
        ) from exc

    Gst.init(None)
    try:
        pipeline = Gst.parse_launch(pipeline_description)
    except Exception as exc:
        raise PipelineRunError(f"GStreamer pipeline could not be parsed: {exc}") from exc

    try:
        detection_io = _build_detection_io(config)
    except PipelineRunError:
        pipeline.set_state(Gst.State.NULL)
        raise
    try:
        cursor_state = (
            DetectionCursorState(frame_width=640, frame_height=480)
            if config.zmq.enabled
            else None
        )
        detection_telemetry_state = DetectionTelemetryState(detection_io)
        if config.detector.enabled:
            detection_sink = pipeline.get_by_name("detection_sink")
            if detection_sink is None:
                raise PipelineRunError(
                    "GStreamer element 'detection_sink' was not found"
                )
            detection_sink.connect(
                "new-sample",
                _on_detection_sample,
                (Gst, detection_telemetry_state),
            )

        if config.detector.overlay_enabled:
            detection_overlay = pipeline.get_by_name("detection_overlay")
            if detection_overlay is None:
                raise PipelineRunError(
                    "GStreamer element 'detection_overlay' was not found"
                )
            overlay_sink_pad = detection_overlay.get_static_pad("sink")
            if overlay_sink_pad is None:
                raise PipelineRunError(
                    "GStreamer element 'detection_overlay' has no sink pad"
                )
            overlay_state = DetectionOverlayState()
            overlay_sink_pad.add_probe(
                Gst.PadProbeType.BUFFER,
                _on_detection_overlay_buffer,
                (overlay_state, Gst),
            )
            detection_overlay.connect("draw", _on_detection_overlay_draw, overlay_state)
            if cursor_state is not None:
                detection_overlay.connect("draw", _on_tracker_cursor_draw, cursor_state)

        bus = pipeline.get_bus()
        pipeline.set_state(Gst.State.PLAYING)
        pipeline_runner_logger.debug("GStreamer pipeline entered PLAYING")
        try:
            while True:
                if cursor_state is not None:
                    for request in detection_io.poll_requests():
                        cursor_state.apply(request)
                        detection_telemetry_state.lock_state.apply_request(request)
                message = bus.timed_pop_filtered(
                    50 * getattr(Gst, "MSECOND", 1_000_000),
                    Gst.MessageType.ERROR | Gst.MessageType.EOS,
                )
                if message is None:
                    continue
                if message.type == Gst.MessageType.ERROR:
                    error, debug = message.parse_error()
                    pipeline_runner_logger.error(
                        "GStreamer error error={} debug={}", error, debug
                    )
                    print(f"GStreamer error: {error.message}")
                    if debug:
                        print(debug)
                    return 1
                if message.type == Gst.MessageType.EOS:
                    pipeline_runner_logger.info("GStreamer pipeline reached EOS")
                    return 0
        except KeyboardInterrupt:
            pipeline_runner_logger.info("GStreamer pipeline interrupted")
            return 0
    finally:
        pipeline.set_state(Gst.State.NULL)
        detection_io.close()
        pipeline_runner_logger.debug("GStreamer pipeline entered NULL")


def _build_detection_io(config: AppConfig) -> DetectionIoAdapter:
    if not config.zmq.enabled:
        return NullDetectionIoAdapter()
    try:
        return ZmqDetectionIoAdapter(
            request_endpoint=config.zmq.request_endpoint,
            telemetry_endpoint=config.zmq.telemetry_endpoint,
            bind=config.zmq.bind,
        )
    except Exception as exc:
        raise PipelineRunError(f"ZMQ detector bridge could not start: {exc}") from exc


def _on_detection_sample(
    sink: object,
    callback_data: tuple[object, DetectionTelemetryState],
) -> object:
    gst, telemetry_state = callback_data
    sample = sink.emit("pull-sample")
    if sample is None:
        return gst.FlowReturn.ERROR
    buffer = sample.get_buffer()
    if buffer is None:
        return gst.FlowReturn.OK
    detection = read_red_detection(buffer)
    if detection is None:
        pipeline_runner_logger.warning("red detection buffer has no metadata")
        return gst.FlowReturn.OK

    telemetry_state.publish(detection)
    pipeline_runner_logger.debug(
        "red detection found={} x={} y={} width={} height={} pts_ns={}",
        detection.found,
        detection.x,
        detection.y,
        detection.width,
        detection.height,
        detection.pts_ns,
    )
    return gst.FlowReturn.OK


def _on_detection_overlay_buffer(
    _pad: object,
    info: object,
    callback_data: tuple[DetectionOverlayState, object],
) -> object:
    state, gst = callback_data
    buffer = info.get_buffer()
    state.update(read_red_detection(buffer) if buffer is not None else None)
    return gst.PadProbeReturn.OK


def _on_detection_overlay_draw(
    _overlay: object,
    context: object,
    timestamp: int,
    _duration: int,
    state: DetectionOverlayState,
) -> None:
    detection = state.detection_for_timestamp(timestamp)
    if detection is None or not detection.found:
        return

    line_width = 3.0
    half_line = line_width / 2.0
    context.set_source_rgba(0.0, 1.0, 0.0, 1.0)
    context.set_line_width(line_width)
    context.rectangle(
        detection.x + half_line,
        detection.y + half_line,
        max(0.0, detection.width - line_width),
        max(0.0, detection.height - line_width),
    )
    context.stroke()


def _on_tracker_cursor_draw(
    _overlay: object,
    context: object,
    _timestamp: int,
    _duration: int,
    state: DetectionCursorState,
) -> None:
    roi = state.snapshot()
    if roi is None:
        return
    line_width = 3.0
    half_line = line_width / 2.0
    context.set_source_rgba(0.0, 1.0, 1.0, 1.0)
    context.set_line_width(line_width)
    context.rectangle(
        roi.x + half_line,
        roi.y + half_line,
        max(0.0, roi.width - line_width),
        max(0.0, roi.height - line_width),
    )
    context.stroke()

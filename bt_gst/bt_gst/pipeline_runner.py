from itertools import count
import time

from bt_msgs import TrackerResultMessage
from loguru import logger

from bt_gst.config import AppConfig, TrackerConfig, effective_tracker_config
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.red_detection import (
    DetectionBox,
    DetectionOverlayState,
    read_cpu_nano_detection,
    read_red_detection,
)
from bt_gst.zmq_publisher import ZmqFramePublisher, ZmqPublisherError
from bt_gst.selector_subscriber import SelectorSubscriberError, ZmqSelectorSubscriber

pipeline_runner_logger = logger.bind(component="bt_gst.pipeline_runner")


class PipelineRunError(RuntimeError):
    """Raised when a GStreamer pipeline cannot be run."""


class _WarningRateLimiter:
    def __init__(self, interval_s: float = 5.0) -> None:
        self.interval_s = interval_s
        self._last_warning_at = float("-inf")

    def ready(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        if current - self._last_warning_at < self.interval_s:
            return False
        self._last_warning_at = current
        return True


def run_pipeline(config: AppConfig) -> int:
    pipeline_description = build_pipeline_description(config)
    pipeline_runner_logger.info(
        "starting GStreamer pipeline pipeline={}", pipeline_description
    )
    try:
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("GstVideo", "1.0")
        from gi.repository import Gst, GstVideo
    except (ImportError, ValueError) as exc:
        raise PipelineRunError(
            "GStreamer Python bindings are unavailable. Install PyGObject and "
            "the native GStreamer introspection packages."
        ) from exc

    Gst.init(None)
    try:
        pipeline = Gst.parse_launch(pipeline_description)
    except Exception as exc:
        raise PipelineRunError(
            f"GStreamer pipeline could not be parsed: {exc}"
        ) from exc

    publisher = None
    selector_subscriber = None
    tracker_config = effective_tracker_config(config)
    try:
        if config.zmq.enabled:
            publisher = ZmqFramePublisher(
                config.zmq.endpoint,
                bind=config.zmq.bind,
                max_rate_hz=config.zmq.max_rate_hz,
            )
            try:
                publisher.start()
            except ZmqPublisherError as exc:
                raise PipelineRunError(str(exc)) from exc

        tracker_element = (
            pipeline.get_by_name("tracker_backend") if tracker_config.enabled else None
        )
        if tracker_config.enabled and tracker_element is None:
            raise PipelineRunError("GStreamer element 'tracker_backend' was not found")
        selector_supported = tracker_config.type == "controlled_red" or (
            tracker_config.type == "cpu_nano"
            and tracker_config.cpu_nano.initialization == "selector"
        )
        if (
            tracker_config.enabled
            and selector_supported
            and config.selector_zmq.enabled
        ):
            selector_subscriber = ZmqSelectorSubscriber(
                config.selector_zmq.endpoint,
                bind=config.selector_zmq.bind,
            )
            try:
                selector_subscriber.start()
            except SelectorSubscriberError as exc:
                raise PipelineRunError(str(exc)) from exc

        overlay_state = None
        if tracker_config.overlay_enabled:
            detection_overlay = pipeline.get_by_name("detection_overlay")
            if detection_overlay is None:
                raise PipelineRunError(
                    "GStreamer element 'detection_overlay' was not found"
                )
            overlay_state = DetectionOverlayState()

            detection_overlay.connect("draw", _on_detection_overlay_draw, overlay_state)

        frame_ids = count(1) if publisher is not None else None
        metadata_warning_limiter = _WarningRateLimiter()
        if tracker_config.enabled and (
            overlay_state is not None or publisher is not None
        ):
            detector_src_pad = tracker_element.get_static_pad("src")
            if detector_src_pad is None:
                raise PipelineRunError(
                    "GStreamer element 'red_detector' has no src pad"
                )
            detector_src_pad.add_probe(
                Gst.PadProbeType.BUFFER,
                _on_detector_buffer,
                (
                    overlay_state,
                    publisher,
                    frame_ids,
                    metadata_warning_limiter,
                    Gst,
                    _metadata_reader(tracker_config, GstVideo),
                    lambda: (
                        tracker_config.type == "controlled_red"
                        or bool(tracker_element.get_property("enabled"))
                    ),
                ),
            )

        bus = pipeline.get_bus()
        pipeline.set_state(Gst.State.PLAYING)
        pipeline_runner_logger.debug("GStreamer pipeline entered PLAYING")
        applied_selector = None
        try:
            while True:
                if selector_subscriber is not None and tracker_element is not None:
                    selector = selector_subscriber.latest(
                        max_age_s=config.selector_zmq.command_timeout_s
                    )
                    if selector is not None:
                        selector_key = (
                            selector.center_x,
                            selector.center_y,
                            int(selector.state),
                            selector.roi_width,
                            selector.roi_height,
                        )
                        if selector_key != applied_selector:
                            if _apply_selector_command(
                                tracker_element, selector, tracker_config, overlay_state
                            ):
                                applied_selector = selector_key
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
        if publisher is not None:
            try:
                publisher.stop()
            except ZmqPublisherError as exc:
                pipeline_runner_logger.warning(
                    "ZMQ publisher shutdown failed error={}", exc
                )
        if selector_subscriber is not None:
            try:
                selector_subscriber.stop()
            except SelectorSubscriberError as exc:
                pipeline_runner_logger.warning(
                    "selector subscriber shutdown failed error={}", exc
                )
        pipeline_runner_logger.debug("GStreamer pipeline entered NULL")


def _metadata_reader(tracker: TrackerConfig, gst_video: object):
    if tracker.type == "controlled_red":
        return read_red_detection
    return lambda buffer: read_cpu_nano_detection(
        buffer, gst_video, tracker.cpu_nano.confidence_threshold
    )


def _apply_selector_command(
    tracker_element: object,
    command: object,
    tracker: TrackerConfig,
    overlay_state: DetectionOverlayState | None = None,
) -> bool:
    if tracker.type == "controlled_red":
        tracker_element.set_property("selector-center-x", command.center_x)
        tracker_element.set_property("selector-center-y", command.center_y)
        tracker_element.set_property("selector-state", int(command.state))
        return True
    if int(command.state) == 0:
        tracker_element.set_property("enabled", False)
        if overlay_state is not None:
            overlay_state.update_selector(None)
        return True

    sink_pad = tracker_element.get_static_pad("sink")
    caps = sink_pad.get_current_caps() if sink_pad is not None else None
    if caps is None or caps.get_size() == 0:
        pipeline_runner_logger.debug(
            "delaying CPU NanoTrack selector command until input caps are negotiated"
        )
        return False
    structure = caps.get_structure(0)
    width = int(structure.get_value("width"))
    height = int(structure.get_value("height"))
    command_roi_width = getattr(command, "roi_width", None)
    command_roi_height = getattr(command, "roi_height", None)
    if command_roi_width is None or command_roi_height is None:
        roi_width, roi_height = tracker.cpu_nano.selector_roi_size
        if roi_width > width or roi_height > height:
            raise PipelineRunError(
                "CPU NanoTrack selector ROI is larger than the input frame"
            )
    else:
        roi_width = min(command_roi_width, width)
        roi_height = min(command_roi_height, height)
    x = min(max(round(command.center_x * width - roi_width / 2), 0), width - roi_width)
    y = min(
        max(round(command.center_y * height - roi_height / 2), 0), height - roi_height
    )
    tracker_element.set_property("roi", f"{x},{y},{roi_width},{roi_height}")
    locked = int(command.state) == 2
    tracker_element.set_property("enabled", locked)
    if overlay_state is not None:
        overlay_state.update_selector(
            None if locked else DetectionBox(x, y, roi_width, roi_height)
        )
    return True


def _on_detector_buffer(
    _pad: object,
    info: object,
    callback_data: tuple,
) -> object:
    overlay_state, publisher, frame_ids, warning_limiter, gst, *rest = callback_data
    reader = rest[0] if rest else read_red_detection
    metadata_expected = rest[1] if len(rest) > 1 else lambda: True
    buffer = info.get_buffer()
    detection = reader(buffer) if buffer is not None else None
    if overlay_state is not None:
        overlay_state.update(detection)
    if publisher is not None and frame_ids is not None and buffer is not None:
        frame_id = next(frame_ids)
        if detection is None:
            if not metadata_expected():
                return gst.PadProbeReturn.OK
            if warning_limiter.ready():
                pipeline_runner_logger.warning(
                    "skipped tracker result reason=tracker-metadata-missing"
                )
            return gst.PadProbeReturn.OK
        message_args = {
            "frame_id": frame_id,
            "timestamp_ns": detection.pts_ns,
            "locked": detection.found,
            "score": float(detection.score),
        }
        if detection.found:
            message_args.update(
                bbox_x=detection.x,
                bbox_y=detection.y,
                bbox_width=detection.width,
                bbox_height=detection.height,
            )
        publisher.publish(TrackerResultMessage(**message_args))
    return gst.PadProbeReturn.OK


def _on_detection_overlay_draw(
    _overlay: object,
    context: object,
    timestamp: int,
    _duration: int,
    state: DetectionOverlayState,
) -> None:
    detection = state.detection_for_timestamp(timestamp)

    line_width = 3.0
    context.set_line_width(line_width)
    selector = state.selector()
    if selector is not None:
        _draw_box(context, selector, line_width, (1.0, 1.0, 0.0, 1.0))
    if detection is None:
        return
    for candidate in detection.candidates:
        _draw_box(context, candidate, line_width, (0.0, 0.0, 1.0, 1.0))
    if detection.found:
        _draw_box(context, detection, line_width, (0.0, 1.0, 0.0, 1.0))
    if detection.selector_state == 1:
        color = (
            (0.0, 1.0, 0.0, 1.0) if detection.selector_valid else (1.0, 1.0, 0.0, 1.0)
        )
        _draw_box(context, detection.selector, line_width, color)


def _draw_box(
    context: object, box: object, line_width: float, color: tuple[float, ...]
) -> None:
    half_line = line_width / 2.0
    context.set_source_rgba(*color)
    context.rectangle(
        box.x + half_line,
        box.y + half_line,
        max(0.0, box.width - line_width),
        max(0.0, box.height - line_width),
    )
    context.stroke()

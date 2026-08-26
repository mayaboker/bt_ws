from collections.abc import Iterator
from itertools import count
import time

from bt_msgs import TrackerResultMessage
from loguru import logger

from bt_gst.config import AppConfig
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.red_detection import (
    DetectionOverlayState,
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

    publisher = None
    selector_subscriber = None
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

        red_detector = pipeline.get_by_name("red_detector") if config.detector.enabled else None
        if config.detector.enabled and red_detector is None:
            raise PipelineRunError("GStreamer element 'red_detector' was not found")
        if config.detector.enabled and config.selector_zmq.enabled:
            selector_subscriber = ZmqSelectorSubscriber(
                config.selector_zmq.endpoint,
                bind=config.selector_zmq.bind,
            )
            try:
                selector_subscriber.start()
            except SelectorSubscriberError as exc:
                raise PipelineRunError(str(exc)) from exc

        overlay_state = None
        if config.detector.overlay_enabled:
            detection_overlay = pipeline.get_by_name("detection_overlay")
            if detection_overlay is None:
                raise PipelineRunError(
                    "GStreamer element 'detection_overlay' was not found"
                )
            overlay_state = DetectionOverlayState()

            detection_overlay.connect("draw", _on_detection_overlay_draw, overlay_state)

        frame_ids = count(1) if publisher is not None else None
        metadata_warning_limiter = _WarningRateLimiter()
        if config.detector.enabled and (overlay_state is not None or publisher is not None):
            detector_src_pad = red_detector.get_static_pad("src")
            if detector_src_pad is None:
                raise PipelineRunError("GStreamer element 'red_detector' has no src pad")
            detector_src_pad.add_probe(
                Gst.PadProbeType.BUFFER,
                _on_detector_buffer,
                (
                    overlay_state,
                    publisher,
                    frame_ids,
                    metadata_warning_limiter,
                    Gst,
                ),
            )

        bus = pipeline.get_bus()
        pipeline.set_state(Gst.State.PLAYING)
        pipeline_runner_logger.debug("GStreamer pipeline entered PLAYING")
        applied_selector = None
        try:
            while True:
                if selector_subscriber is not None and red_detector is not None:
                    selector = selector_subscriber.latest(
                        max_age_s=config.selector_zmq.command_timeout_s
                    )
                    if selector is not None:
                        selector_key = (
                            selector.center_x,
                            selector.center_y,
                            int(selector.state),
                        )
                        if selector_key != applied_selector:
                            _apply_selector_command(red_detector, selector)
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
                pipeline_runner_logger.warning("ZMQ publisher shutdown failed error={}", exc)
        if selector_subscriber is not None:
            try:
                selector_subscriber.stop()
            except SelectorSubscriberError as exc:
                pipeline_runner_logger.warning("selector subscriber shutdown failed error={}", exc)
        pipeline_runner_logger.debug("GStreamer pipeline entered NULL")


def _apply_selector_command(red_detector: object, command: object) -> None:
    red_detector.set_property("selector-center-x", command.center_x)
    red_detector.set_property("selector-center-y", command.center_y)
    red_detector.set_property("selector-state", int(command.state))


def _on_detector_buffer(
    _pad: object,
    info: object,
    callback_data: tuple[
        DetectionOverlayState | None,
        ZmqFramePublisher | None,
        Iterator[int] | None,
        _WarningRateLimiter,
        object,
    ],
) -> object:
    overlay_state, publisher, frame_ids, warning_limiter, gst = callback_data
    buffer = info.get_buffer()
    detection = read_red_detection(buffer) if buffer is not None else None
    if overlay_state is not None:
        overlay_state.update(detection)
    if publisher is not None and frame_ids is not None and buffer is not None:
        frame_id = next(frame_ids)
        if detection is None:
            if warning_limiter.ready():
                pipeline_runner_logger.warning(
                    "skipped tracker result reason=red-detection-metadata-missing"
                )
            return gst.PadProbeReturn.OK
        publisher.publish(
            TrackerResultMessage(
                frame_id=frame_id,
                timestamp_ns=detection.pts_ns,
                locked=detection.found,
                bbox_x=detection.x,
                bbox_y=detection.y,
                bbox_width=detection.width,
                bbox_height=detection.height,
            )
        )
    return gst.PadProbeReturn.OK


def _on_detection_overlay_draw(
    _overlay: object,
    context: object,
    timestamp: int,
    _duration: int,
    state: DetectionOverlayState,
) -> None:
    detection = state.detection_for_timestamp(timestamp)
    if detection is None:
        return

    line_width = 3.0
    context.set_line_width(line_width)
    for candidate in detection.candidates:
        _draw_box(context, candidate, line_width, (0.0, 0.0, 1.0, 1.0))
    if detection.found:
        _draw_box(context, detection, line_width, (0.0, 1.0, 0.0, 1.0))
    if detection.selector_state == 1:
        color = (0.0, 1.0, 0.0, 1.0) if detection.selector_valid else (1.0, 1.0, 0.0, 1.0)
        _draw_box(context, detection.selector, line_width, color)


def _draw_box(context: object, box: object, line_width: float, color: tuple[float, ...]) -> None:
    half_line = line_width / 2.0
    context.set_source_rgba(*color)
    context.rectangle(
        box.x + half_line,
        box.y + half_line,
        max(0.0, box.width - line_width),
        max(0.0, box.height - line_width),
    )
    context.stroke()

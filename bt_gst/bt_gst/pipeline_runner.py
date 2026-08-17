from collections.abc import Iterator
from itertools import count

from bt_msgs import TrackerResultMessage
from loguru import logger

from bt_gst.config import AppConfig
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.red_detection import (
    GST_CLOCK_TIME_NONE,
    DetectionOverlayState,
    read_red_detection,
)
from bt_gst.zmq_publisher import ZmqFramePublisher, ZmqPublisherError

pipeline_runner_logger = logger.bind(component="bt_gst.pipeline_runner")


class PipelineRunError(RuntimeError):
    """Raised when a GStreamer pipeline cannot be run."""


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
        if config.detector.enabled and (overlay_state is not None or publisher is not None):
            red_detector = pipeline.get_by_name("red_detector")
            if red_detector is None:
                raise PipelineRunError("GStreamer element 'red_detector' was not found")
            detector_src_pad = red_detector.get_static_pad("src")
            if detector_src_pad is None:
                raise PipelineRunError("GStreamer element 'red_detector' has no src pad")
            detector_src_pad.add_probe(
                Gst.PadProbeType.BUFFER,
                _on_detector_buffer,
                (overlay_state, publisher, frame_ids, Gst),
            )

        bus = pipeline.get_bus()
        pipeline.set_state(Gst.State.PLAYING)
        pipeline_runner_logger.debug("GStreamer pipeline entered PLAYING")
        try:
            while True:
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
        pipeline_runner_logger.debug("GStreamer pipeline entered NULL")


def _on_detector_buffer(
    _pad: object,
    info: object,
    callback_data: tuple[
        DetectionOverlayState | None,
        ZmqFramePublisher | None,
        Iterator[int] | None,
        object,
    ],
) -> object:
    overlay_state, publisher, frame_ids, gst = callback_data
    buffer = info.get_buffer()
    if overlay_state is not None:
        overlay_state.update(read_red_detection(buffer) if buffer is not None else None)
    if publisher is not None and frame_ids is not None and buffer is not None:
        pts = int(buffer.pts)
        publisher.publish(
            TrackerResultMessage(
                frame_id=next(frame_ids),
                timestamp=None if pts == GST_CLOCK_TIME_NONE else pts,
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

from loguru import logger

from bt_gst.config import AppConfig
from bt_gst.pipeline_builder import build_pipeline_description
from bt_gst.red_detection import (
    DetectionOverlayState,
    read_red_detection,
)

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

    try:
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
        pipeline_runner_logger.debug("GStreamer pipeline entered NULL")


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

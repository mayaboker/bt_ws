from loguru import logger

from bt_gst.config import AppConfig
from bt_gst.pipeline_builder import PipelineBuildError, build_pipeline_description

pipeline_runner_logger = logger.bind(component="bt_gst.pipeline_runner")


class PipelineRunError(RuntimeError):
    """Raised when a GStreamer pipeline cannot be run."""


def run_pipeline(config: AppConfig) -> int:
    try:
        pipeline_description = build_pipeline_description(config)
    except PipelineBuildError:
        raise
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

    bus = pipeline.get_bus()
    pipeline.set_state(Gst.State.PLAYING)
    pipeline_runner_logger.debug("GStreamer pipeline entered PLAYING")
    try:
        while True:
            message = bus.timed_pop_filtered(
                Gst.CLOCK_TIME_NONE,
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

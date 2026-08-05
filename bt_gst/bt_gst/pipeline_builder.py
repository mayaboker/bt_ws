import shlex
from pathlib import Path

from loguru import logger

from bt_gst.config import (
    AppConfig,
    CameraSourceConfig,
    ConfigError,
    DetectorConfig,
    FileSourceConfig,
    SimulationSourceConfig,
    SourceConfig,
    validate_config,
)

pipeline_builder_logger = logger.bind(component="bt_gst.pipeline_builder")


class PipelineBuildError(RuntimeError):
    """Raised when a GStreamer pipeline cannot be built."""


def build_pipeline_description(config: AppConfig) -> str:
    config = validate_config(config)
    source = config.source
    pipeline_builder_logger.trace("building pipeline source={!r}", source)
    parts = [
        build_source_pipeline_description(source),
        build_processing_pipeline_description(config.detector),
        "! tee name=video_tee",
        "video_tee. !",
        build_stream_branch_description(config),
    ]
    debug_branch = build_debug_branch_description(config)
    if debug_branch:
        parts.append(debug_branch)
    detection_branch = build_detection_branch_description(config)
    if detection_branch:
        parts.append(detection_branch)
    return " ".join(parts)


def build_source_pipeline_description(source: SourceConfig) -> str:
    if isinstance(source, FileSourceConfig):
        return (
            f"filesrc location={_quote_path(source.path)} ! decodebin ! "
            f"videorate ! video/x-raw,framerate={source.rate}/1"
        )
    if isinstance(source, CameraSourceConfig):
        return f"v4l2src device={shlex.quote(source.device)}"
    if isinstance(source, SimulationSourceConfig):
        return f"gzimgsrc topic={shlex.quote(source.topic)}"
    raise ConfigError("source config is required")


def build_processing_pipeline_description(detector: DetectorConfig) -> str:
    if not detector.enabled:
        return "! videoconvert"
    detector_description = (
        "! videoconvert ! video/x-raw,format=RGB ! controlledreddetect "
        f"detection-enabled=true low-h={detector.low_h} low-s={detector.low_s} "
        f"low-v={detector.low_v} high-h={detector.high_h} "
        f"high-s={detector.high_s} high-v={detector.high_v}"
    )
    if not detector.overlay_enabled:
        return detector_description
    return (
        f"{detector_description} ! videoconvert ! "
        "video/x-raw,format=BGRx ! "
        "cairooverlay name=detection_overlay"
    )


def build_stream_branch_description(config: AppConfig) -> str:
    if config.codec != "h264":
        raise PipelineBuildError(f"unsupported codec: {config.codec}")
    framerate = 30
    raw_caps = "video/x-raw,format=I420,width=640,height=480,framerate=30/1"
    if isinstance(config.source, SimulationSourceConfig):
        framerate = config.source.rate
        raw_caps = (
            f"video/x-raw,format=I420,width=640,height=480,"
            f"framerate={framerate}/1"
        )
    return (
        "queue leaky=downstream max-size-buffers=2 ! "
        "videoconvert ! videoscale ! videorate !"
        f"{raw_caps} ! "
        "x264enc bitrate=1500 tune=zerolatency speed-preset=ultrafast "
        "key-int-max=30 bframes=0 byte-stream=true aud=true "
        "intra-refresh=false sliced-threads=false threads=1 ! "
        "video/x-h264,stream-format=byte-stream,alignment=au,"
        "profile=constrained-baseline ! "
        "h264parse config-interval=1 ! "
        f"rtph264pay pt=96 mtu={config.mtu} config-interval=1 "
        "aggregate-mode=zero-latency ! "
        f"udpsink host={shlex.quote(config.host)} port={config.port} "
        "sync=false async=false"
    )


def build_debug_branch_description(config: AppConfig) -> str:
    if not config.video_local:
        return ""
    return "video_tee. ! queue ! videoconvert ! fpsdisplaysink video-sink=glimagesink sync=true"


def build_detection_branch_description(config: AppConfig) -> str:
    if not config.detector.enabled:
        return ""
    return (
        "video_tee. ! queue leaky=downstream max-size-buffers=1 ! "
        "appsink name=detection_sink emit-signals=true sync=false "
        "max-buffers=1 drop=true"
    )


def _quote_path(path: Path) -> str:
    return shlex.quote(str(path))

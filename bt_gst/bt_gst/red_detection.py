from dataclasses import dataclass, field
from threading import Lock

RED_DETECTION_META_NAME = "GstRedDetectionMeta"
OBJECT_DETECTION_PARAMS_NAME = "bt-object-detection"
GST_CLOCK_TIME_NONE = (1 << 64) - 1


@dataclass(frozen=True)
class DetectionBox:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class RedDetection:
    found: bool
    x: int
    y: int
    width: int
    height: int
    pts_ns: int | None
    selector: DetectionBox = DetectionBox(0, 0, 0, 0)
    selector_valid: bool = False
    selector_state: int = 0
    candidates: tuple[DetectionBox, ...] = ()
    score: float = 0.0
    initialized: bool = False


@dataclass
class DetectionOverlayState:
    _detection: RedDetection | None = None
    _selector: DetectionBox | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def update(self, detection: RedDetection | None) -> None:
        with self._lock:
            self._detection = detection

    def detection_for_timestamp(self, timestamp: int) -> RedDetection | None:
        with self._lock:
            detection = self._detection
        if detection is None:
            return None
        timestamp_ns = None if timestamp == GST_CLOCK_TIME_NONE else timestamp
        if detection.pts_ns != timestamp_ns:
            return None
        return detection

    def update_selector(self, selector: DetectionBox | None) -> None:
        with self._lock:
            self._selector = selector

    def selector(self) -> DetectionBox | None:
        with self._lock:
            return self._selector


def read_red_detection(buffer: object) -> RedDetection | None:
    meta = buffer.get_custom_meta(RED_DETECTION_META_NAME)
    if meta is None:
        return None

    structure = meta.get_structure()
    pts = int(buffer.pts)
    candidate_count = int(structure.get_value("candidate-count"))
    candidates = tuple(
        DetectionBox(
            x=int(structure.get_value(f"candidate-{index}-x")),
            y=int(structure.get_value(f"candidate-{index}-y")),
            width=int(structure.get_value(f"candidate-{index}-width")),
            height=int(structure.get_value(f"candidate-{index}-height")),
        )
        for index in range(candidate_count)
    )
    return RedDetection(
        found=bool(structure.get_value("found")),
        x=int(structure.get_value("x")),
        y=int(structure.get_value("y")),
        width=int(structure.get_value("width")),
        height=int(structure.get_value("height")),
        pts_ns=None if pts == GST_CLOCK_TIME_NONE else pts,
        selector=DetectionBox(
            x=int(structure.get_value("selector-x")),
            y=int(structure.get_value("selector-y")),
            width=int(structure.get_value("selector-width")),
            height=int(structure.get_value("selector-height")),
        ),
        selector_valid=bool(structure.get_value("selector-valid")),
        selector_state=int(structure.get_value("selector-state")),
        candidates=candidates,
    )


def read_cpu_nano_detection(
    buffer: object,
    gst_video: object,
    confidence_threshold: float,
) -> RedDetection | None:
    """Normalize one CPU NanoTrack ROI meta into the common detection model."""

    meta = gst_video.buffer_get_video_region_of_interest_meta_id(buffer, 0)
    if meta is None:
        return None
    # The NanoTrack pipeline adds exactly one result ROI with id 0. The common
    # parameter structure is shared with cpuyolodetect and is authoritative.
    parameters = meta.get_param(OBJECT_DETECTION_PARAMS_NAME)
    if parameters is None:
        return None
    initialized = bool(parameters.get_value("initialized"))
    score = float(parameters.get_value("confidence"))
    locked = not initialized and score >= confidence_threshold
    pts = int(buffer.pts)
    return RedDetection(
        found=locked,
        x=int(meta.x),
        y=int(meta.y),
        width=int(meta.w),
        height=int(meta.h),
        pts_ns=None if pts == GST_CLOCK_TIME_NONE else pts,
        score=score,
        initialized=initialized,
    )

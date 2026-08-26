from dataclasses import dataclass, field
from threading import Lock

RED_DETECTION_META_NAME = "GstRedDetectionMeta"
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


@dataclass
class DetectionOverlayState:
    _detection: RedDetection | None = None
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

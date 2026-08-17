from dataclasses import dataclass, field
from threading import Lock

RED_DETECTION_META_NAME = "GstRedDetectionMeta"
GST_CLOCK_TIME_NONE = (1 << 64) - 1


@dataclass(frozen=True)
class RedDetection:
    found: bool
    x: int
    y: int
    width: int
    height: int
    pts_ns: int | None


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
    return RedDetection(
        found=bool(structure.get_value("found")),
        x=int(structure.get_value("x")),
        y=int(structure.get_value("y")),
        width=int(structure.get_value("width")),
        height=int(structure.get_value("height")),
        pts_ns=None if pts == GST_CLOCK_TIME_NONE else pts,
    )

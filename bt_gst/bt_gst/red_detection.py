from dataclasses import dataclass, field
from threading import Lock

from bt_gst.bridge.zmq_models import (
    MESSAGE_TYPE_FIELD,
    TYPE_TRACK_ADJUSTMENT,
    TYPE_TRACK_RESIZE,
    TYPE_TRACK_START,
    TYPE_TRACK_STOP,
    TrackRequest,
)

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


@dataclass(frozen=True)
class CursorRoi:
    x: int
    y: int
    width: int
    height: int


@dataclass
class DetectionCursorState:
    frame_width: int
    frame_height: int
    initial_size: int = 30
    _roi: CursorRoi | None = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def apply(self, request: TrackRequest) -> None:
        with self._lock:
            request_type = request.get(MESSAGE_TYPE_FIELD)
            if request_type == TYPE_TRACK_START:
                size = min(self.initial_size, self.frame_width, self.frame_height)
                self._roi = self._centered(
                    int(request["x"]),
                    int(request["y"]),
                    size,
                    size,
                )
            elif request_type == TYPE_TRACK_STOP:
                self._roi = None
            elif request_type == TYPE_TRACK_ADJUSTMENT and self._roi is not None:
                self._roi = self._move(
                    self._roi,
                    int(request["delta_x"]),
                    int(request["delta_y"]),
                )
            elif request_type == TYPE_TRACK_RESIZE and self._roi is not None:
                width = max(1, min(int(request["width"]), self.frame_width))
                height = max(1, min(int(request["height"]), self.frame_height))
                center_x = self._roi.x + self._roi.width // 2
                center_y = self._roi.y + self._roi.height // 2
                self._roi = self._centered(center_x, center_y, width, height)

    def snapshot(self) -> CursorRoi | None:
        with self._lock:
            return self._roi

    def _centered(self, center_x: int, center_y: int, width: int, height: int) -> CursorRoi:
        x = max(0, min(center_x - width // 2, self.frame_width - width))
        y = max(0, min(center_y - height // 2, self.frame_height - height))
        return CursorRoi(x=x, y=y, width=width, height=height)

    def _move(self, roi: CursorRoi, delta_x: int, delta_y: int) -> CursorRoi:
        return CursorRoi(
            x=max(0, min(roi.x + delta_x, self.frame_width - roi.width)),
            y=max(0, min(roi.y + delta_y, self.frame_height - roi.height)),
            width=roi.width,
            height=roi.height,
        )


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

from dataclasses import dataclass, field
import math
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


@dataclass(frozen=True)
class YoloDetection:
    box: DetectionBox
    class_id: int
    confidence: float


class YoloSelectionState:
    """Thread-safe selector and detection-association state for CPU YOLO."""

    def __init__(
        self,
        association_iou_threshold: float,
        association_max_distance: float,
    ) -> None:
        self._association_iou_threshold = association_iou_threshold
        self._association_max_distance = association_max_distance
        self._armed = False
        self._selector: DetectionBox | None = None
        self._selected_class_id: int | None = None
        self._previous_box: DetectionBox | None = None
        self._frame_size = (0, 0)
        self._lock = Lock()

    def disable(self) -> None:
        with self._lock:
            self._armed = False
            self._selector = None
            self._selected_class_id = None
            self._previous_box = None

    def arm(self, selector: DetectionBox, frame_width: int, frame_height: int) -> None:
        with self._lock:
            self._armed = True
            self._selector = selector
            self._selected_class_id = None
            self._previous_box = None
            self._frame_size = (frame_width, frame_height)

    def select(
        self,
        detections: tuple[YoloDetection, ...],
        pts_ns: int | None,
    ) -> RedDetection | None:
        with self._lock:
            if not self._armed:
                return None
            candidate_boxes = tuple(detection.box for detection in detections)
            selected = self._initial_detection(detections)
            if self._selected_class_id is not None and self._previous_box is not None:
                selected = self._associated_detection(detections)
            if selected is None:
                return RedDetection(
                    False, 0, 0, 0, 0, pts_ns, candidates=candidate_boxes
                )
            self._selected_class_id = selected.class_id
            self._previous_box = selected.box
            return RedDetection(
                True,
                selected.box.x,
                selected.box.y,
                selected.box.width,
                selected.box.height,
                pts_ns,
                candidates=tuple(box for box in candidate_boxes if box != selected.box),
                score=selected.confidence,
            )

    def _initial_detection(
        self, detections: tuple[YoloDetection, ...]
    ) -> YoloDetection | None:
        if self._selector is None:
            return None
        matches = [
            detection
            for detection in detections
            if _boxes_intersect(self._selector, detection.box)
        ]
        if not matches:
            return None
        selector_center = _box_center(self._selector)
        return min(
            matches,
            key=lambda detection: (
                _squared_distance(selector_center, _box_center(detection.box)),
                -detection.confidence,
            ),
        )

    def _associated_detection(
        self, detections: tuple[YoloDetection, ...]
    ) -> YoloDetection | None:
        matches = [
            detection
            for detection in detections
            if detection.class_id == self._selected_class_id
        ]
        if not matches or self._previous_box is None:
            return None
        by_iou = max(
            matches, key=lambda detection: _box_iou(self._previous_box, detection.box)
        )
        if _box_iou(self._previous_box, by_iou.box) >= self._association_iou_threshold:
            return by_iou
        nearest = min(
            matches,
            key=lambda detection: _squared_distance(
                _box_center(self._previous_box), _box_center(detection.box)
            ),
        )
        frame_width, frame_height = self._frame_size
        maximum = self._association_max_distance * math.hypot(frame_width, frame_height)
        distance = math.sqrt(
            _squared_distance(_box_center(self._previous_box), _box_center(nearest.box))
        )
        return nearest if distance <= maximum else None


def _box_center(box: DetectionBox) -> tuple[float, float]:
    return box.x + box.width / 2.0, box.y + box.height / 2.0


def _squared_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return (first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2


def _boxes_intersect(first: DetectionBox, second: DetectionBox) -> bool:
    return (
        first.x < second.x + second.width
        and second.x < first.x + first.width
        and first.y < second.y + second.height
        and second.y < first.y + first.height
    )


def _box_iou(first: DetectionBox, second: DetectionBox) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union else 0.0


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


def read_cpu_yolo_detection(
    buffer: object,
    gst_video: object,
    max_detections: int,
    selection: YoloSelectionState,
) -> RedDetection | None:
    """Read all sequential YOLO ROI results and select one tracked target."""

    detections: list[YoloDetection] = []
    for result_id in range(max_detections):
        meta = gst_video.buffer_get_video_region_of_interest_meta_id(buffer, result_id)
        if meta is None:
            break
        parameters = meta.get_param(OBJECT_DETECTION_PARAMS_NAME)
        if parameters is None:
            continue
        detections.append(
            YoloDetection(
                DetectionBox(int(meta.x), int(meta.y), int(meta.w), int(meta.h)),
                int(parameters.get_value("class-id")),
                float(parameters.get_value("confidence")),
            )
        )
    pts = int(buffer.pts)
    return selection.select(
        tuple(detections), None if pts == GST_CLOCK_TIME_NONE else pts
    )

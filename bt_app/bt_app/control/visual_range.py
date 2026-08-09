"""Pinhole-camera range estimation for a known planar visual target."""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass

from bt_app.comm.gst_bridge import VisualDetectionMessage


MAX_DEPTH_DISAGREEMENT = 0.25
MEDIAN_WINDOW_SIZE = 5


@dataclass(frozen=True)
class CameraIntrinsics:
    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    image_width_px: int
    image_height_px: int


@dataclass(frozen=True)
class TargetRangeEstimate:
    frame_id: int | None
    raw_depth_m: float | None
    distance_m: float | None
    valid: bool
    reason: str | None = None


class VisualRangeEstimator:
    def __init__(
        self,
        intrinsics: CameraIntrinsics,
        *,
        target_width_m: float,
        target_height_m: float,
    ) -> None:
        self.intrinsics = intrinsics
        self.target_width_m = float(target_width_m)
        self.target_height_m = float(target_height_m)
        self._depths: deque[float] = deque(maxlen=MEDIAN_WINDOW_SIZE)
        self._last_frame_id: int | None = None
        self._estimate = TargetRangeEstimate(None, None, None, False, "no detection")

    @property
    def estimate(self) -> TargetRangeEstimate:
        return self._estimate

    def reset(self, reason: str = "no detection") -> TargetRangeEstimate:
        self._depths.clear()
        self._last_frame_id = None
        self._estimate = TargetRangeEstimate(None, None, None, False, reason)
        return self._estimate

    def update(self, detection: VisualDetectionMessage) -> TargetRangeEstimate:
        if detection.frame_id == self._last_frame_id:
            return self._estimate
        self._last_frame_id = detection.frame_id
        reason = self._invalid_reason(detection)
        if reason is not None:
            return self._invalidate(reason, detection.frame_id)
        height_depth = self.intrinsics.fy_px * self.target_height_m / detection.height
        width_depth = self.intrinsics.fx_px * self.target_width_m / detection.width
        disagreement = abs(height_depth - width_depth) / max(height_depth, width_depth)
        if not all(
            math.isfinite(value) and value > 0
            for value in (
                height_depth,
                width_depth,
            )
        ):
            return self._invalidate("non-finite depth", detection.frame_id)
        if disagreement > MAX_DEPTH_DISAGREEMENT:
            return self._invalidate(
                "width/height depth disagreement", detection.frame_id
            )

        self._depths.append(height_depth)
        filtered = float(statistics.median(self._depths))
        self._estimate = TargetRangeEstimate(
            detection.frame_id,
            height_depth,
            filtered,
            True,
        )
        return self._estimate

    def _invalidate(self, reason: str, frame_id: int) -> TargetRangeEstimate:
        self._depths.clear()
        self._estimate = TargetRangeEstimate(frame_id, None, None, False, reason)
        return self._estimate

    def _invalid_reason(self, detection: VisualDetectionMessage) -> str | None:
        if not detection.found:
            return "target not found"
        # if not detection.locked:
        #     return "target not locked"
        if detection.width <= 0 or detection.height <= 0:
            return "non-positive bounding box"
        if (
            detection.x <= 0
            or detection.y <= 0
            or detection.x + detection.width >= self.intrinsics.image_width_px
            or detection.y + detection.height >= self.intrinsics.image_height_px
        ):
            return "bounding box clipped by image edge"
        return None

"""Pinhole-camera distance estimation for a target of known size."""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass

from bt_msgs import TrackerResultMessage


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    image_width_px: int
    image_height_px: int


@dataclass(frozen=True, slots=True)
class DistanceEstimate:
    depth_m: float
    slant_range_m: float
    horizontal_offset_m: float
    vertical_offset_m: float


class PinholeDistanceEstimator:
    """Estimate filtered target depth and camera-relative offsets."""

    def __init__(
        self,
        intrinsics: CameraIntrinsics,
        *,
        target_width_m: float,
        target_height_m: float,
        median_window_size: int = 5,
        max_depth_disagreement: float = 0.25,
    ) -> None:
        self.intrinsics = intrinsics
        self.target_width_m = float(target_width_m)
        self.target_height_m = float(target_height_m)
        self.max_depth_disagreement = float(max_depth_disagreement)
        self._validate_config(median_window_size)
        self._depths: deque[float] = deque(maxlen=median_window_size)

    def reset(self) -> None:
        self._depths.clear()

    def estimate(self, message: TrackerResultMessage) -> DistanceEstimate:
        reason = self.invalid_reason(message)
        if reason is not None:
            self.reset()
            raise ValueError(reason)

        width_depth = (
            self.intrinsics.fx_px * self.target_width_m / message.bbox_width
        )
        height_depth = (
            self.intrinsics.fy_px * self.target_height_m / message.bbox_height
        )
        values = (width_depth, height_depth)
        if not all(math.isfinite(value) and value > 0 for value in values):
            self.reset()
            raise ValueError("non-finite depth")
        disagreement = abs(width_depth - height_depth) / max(values)
        if disagreement > self.max_depth_disagreement:
            self.reset()
            raise ValueError("width/height depth disagreement")

        self._depths.append((width_depth + height_depth) / 2.0)
        depth = float(statistics.median(self._depths))
        center_x = message.bbox_x + message.bbox_width / 2.0
        center_y = message.bbox_y + message.bbox_height / 2.0
        horizontal_offset = (
            (center_x - self.intrinsics.cx_px) * depth / self.intrinsics.fx_px
        )
        vertical_offset = (
            (self.intrinsics.cy_px - center_y) * depth / self.intrinsics.fy_px
        )

        return DistanceEstimate(
            depth_m=depth,
            slant_range_m=math.sqrt(
                depth * depth
                + horizontal_offset * horizontal_offset
                + vertical_offset * vertical_offset
            ),
            horizontal_offset_m=horizontal_offset,
            vertical_offset_m=vertical_offset,
        )

    def invalid_reason(self, message: TrackerResultMessage) -> str | None:
        if not message.locked:
            return "tracker unlocked"
        if message.bbox_width <= 0 or message.bbox_height <= 0:
            return "non-positive bounding box"
        if (
            message.bbox_x <= 0
            or message.bbox_y <= 0
            or message.bbox_x + message.bbox_width >= self.intrinsics.image_width_px
            or message.bbox_y + message.bbox_height >= self.intrinsics.image_height_px
        ):
            return "bounding box clipped by image edge"
        return None

    def _validate_config(self, median_window_size: int) -> None:
        camera_values = (
            self.intrinsics.fx_px,
            self.intrinsics.fy_px,
            self.intrinsics.cx_px,
            self.intrinsics.cy_px,
        )
        if not all(math.isfinite(value) for value in camera_values):
            raise ValueError("camera intrinsics must be finite")
        if self.intrinsics.fx_px <= 0 or self.intrinsics.fy_px <= 0:
            raise ValueError("camera focal lengths must be positive")
        if self.intrinsics.image_width_px <= 0 or self.intrinsics.image_height_px <= 0:
            raise ValueError("camera image dimensions must be positive")
        if not 0 <= self.intrinsics.cx_px < self.intrinsics.image_width_px:
            raise ValueError("camera cx must be inside the image")
        if not 0 <= self.intrinsics.cy_px < self.intrinsics.image_height_px:
            raise ValueError("camera cy must be inside the image")
        if not all(
            math.isfinite(value) and value > 0
            for value in (self.target_width_m, self.target_height_m)
        ):
            raise ValueError("target dimensions must be finite and positive")
        if median_window_size <= 0:
            raise ValueError("median window size must be positive")
        if not 0 <= self.max_depth_disagreement <= 1:
            raise ValueError("depth disagreement must be between zero and one")

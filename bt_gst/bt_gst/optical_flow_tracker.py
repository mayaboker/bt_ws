"""Shared optical-flow tracker interface constants and helpers."""
from typing import Final

from dataclasses import dataclass

META_NAME = "bt-tracker-meta"
META_FIELD_DX = "dx"
META_FIELD_DY = "dy"
META_FIELD_SCORE = "score"
META_FIELD_STATUS = "status"

PROP_ENABLED = "enabled"
PROP_DEBUG = "debug"
PROP_MAX_CORNERS = "max-corners"
PROP_QUALITY_LEVEL = "quality-level"
PROP_MIN_DISTANCE_PX = "min-distance-px"
PROP_MIN_FEATURES = "min-features"
PROP_BLOCK_SIZE = "block-size"
PROP_LK_WINDOW_SIZE = "lk-window-size"
PROP_LK_MAX_LEVEL = "lk-max-level"
PROP_LK_CRITERIA_COUNT = "lk-criteria-count"
PROP_LK_CRITERIA_EPS = "lk-criteria-eps"
PROP_REQUEST_SEARCH_SIZE = "request-search-size"
PROP_ROI_ADJUST_STEP_PX = "roi-adjust-step-px"
PROP_ROI_RESIZE_STEP_PX = "roi-resize-step-px"
PROP_ACCEPT_UPSTREAM_REQUEST = "accept-upstream-request"
PROP_ACCEPT_USER_REQUEST = "accept-user-request"

DEFAULT_ENABLED = True
DEFAULT_DEBUG = False

DEFAULT_MAX_CORNERS = 80
DEFAULT_QUALITY_LEVEL = 0.01
DEFAULT_MIN_DISTANCE_PX = 10.0
DEFAULT_MIN_FEATURES = 2
DEFAULT_BLOCK_SIZE = 7

DEFAULT_LK_WINDOW_SIZE = 21
DEFAULT_LK_MAX_LEVEL = 3
DEFAULT_LK_CRITERIA_COUNT = 30
DEFAULT_LK_CRITERIA_EPS = 0.01

### ROI Size for point tracking requests (pixels)###
DEFAULT_REQUEST_SEARCH_SIZE: Final[int] = 30


DEFAULT_ROI_ADJUST_STEP_PX = 10
DEFAULT_ROI_RESIZE_STEP_PX = 10
DEFAULT_ACCEPT_UPSTREAM_REQUEST = True
DEFAULT_ACCEPT_USER_REQUEST = True

STATUS_OFF = 0
STATUS_TRACK = 1
STATUS_BREAK = 2

TRACK_REQUEST_NAME = "bt-track-request"
TRACK_REQUEST_FIELD_REQUEST_ID = "request-id"
TRACK_REQUEST_FIELD_SOURCE = "source"
TRACK_REQUEST_FIELD_TYPE = "type"
TRACK_REQUEST_FIELD_X = "x"
TRACK_REQUEST_FIELD_Y = "y"
TRACK_REQUEST_FIELD_WIDTH = "width"
TRACK_REQUEST_FIELD_HEIGHT = "height"
TRACK_REQUEST_FIELD_DELTA_X = "delta-x"
TRACK_REQUEST_FIELD_DELTA_Y = "delta-y"
TRACK_REQUEST_TYPE_POINT = "point"
TRACK_REQUEST_TYPE_ROI = "roi"
TRACK_REQUEST_TYPE_STOP = "stop"
TRACK_REQUEST_TYPE_RESIZE_ROI = "resize-roi"
TRACK_REQUEST_TYPE_ADJUST_ROI = "adjust-roi"
TRACK_REQUEST_SOURCE_USER = "user"
TRACK_REQUEST_SOURCE_UPSTREAM_PLUGIN = "upstream-plugin"

TRACKER_DEBUG_MESSAGE_NAME = "bt-tracker-debug"
TRACKER_DEBUG_FIELD_FRAME_NUMBER = "frame-number"
TRACKER_DEBUG_FIELD_STATUS = "status"
TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT = "active-feature-count"
TRACKER_DEBUG_FIELD_FEATURES_JSON = "features-json"


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    width: int
    height: int


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def clamp_roi(roi: Roi, frame_width: int, frame_height: int) -> Roi:
    width = clamp(roi.width, 1, frame_width)
    height = clamp(roi.height, 1, frame_height)
    x = clamp(roi.x, 0, frame_width - width)
    y = clamp(roi.y, 0, frame_height - height)
    return Roi(x=x, y=y, width=width, height=height)


def build_centered_roi(
    x: int,
    y: int,
    size: int,
    frame_width: int,
    frame_height: int,
) -> Roi:
    half_size = max(1, size) // 2
    return clamp_roi(
        Roi(
            x=x - half_size,
            y=y - half_size,
            width=max(1, size),
            height=max(1, size),
        ),
        frame_width=frame_width,
        frame_height=frame_height,
    )


def resize_roi(
    roi: Roi,
    width: int,
    height: int,
    frame_width: int,
    frame_height: int,
) -> Roi:
    center_x = roi.x + roi.width // 2
    center_y = roi.y + roi.height // 2
    return clamp_roi(
        Roi(
            x=center_x - max(1, width) // 2,
            y=center_y - max(1, height) // 2,
            width=max(1, width),
            height=max(1, height),
        ),
        frame_width=frame_width,
        frame_height=frame_height,
    )


def adjust_roi(
    roi: Roi,
    delta_x: int,
    delta_y: int,
    frame_width: int,
    frame_height: int,
) -> Roi:
    """
    Adjust the ROI position by the specified deltas, keeping it within frame bounds.
    """
    return clamp_roi(
        Roi(
            x=roi.x + delta_x,
            y=roi.y + delta_y,
            width=roi.width,
            height=roi.height,
        ),
        frame_width=frame_width,
        frame_height=frame_height,
    )


def compute_tracker_score(feature_count: int, max_corners: int) -> float:
    if max_corners <= 0 or feature_count <= 0:
        return 0.0
    return max(0.0, min(float(feature_count) / float(max_corners), 1.0))


def compute_roi_offset(roi: Roi, frame_width: int, frame_height: int) -> tuple[int, int]:
    center_x = roi.x + (roi.width / 2.0)
    center_y = roi.y + (roi.height / 2.0)
    dx = round(center_x - (frame_width / 2.0))
    dy = round((frame_height / 2.0) - center_y)
    return dx, dy

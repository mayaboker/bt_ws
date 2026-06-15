import ctypes
import ctypes.util
import json
import logging
import sys
from pathlib import Path

import gi

try:
    from loguru import logger
except ModuleNotFoundError:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(message)s",
        level=logging.INFO,
    )

    class LoggerAdapter:
        def __init__(self) -> None:
            self._logger = logging.getLogger(__name__)

        def info(self, message: str, *args: object) -> None:
            self._logger.info(message.format(*args))

        def debug(self, message: str, *args: object) -> None:
            self._logger.debug(message.format(*args))

        def warning(self, message: str, *args: object) -> None:
            self._logger.warning(message.format(*args))

    logger = LoggerAdapter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bt_gst.optical_flow_tracker import (  # noqa: E402
    DEFAULT_ACCEPT_UPSTREAM_REQUEST,
    DEFAULT_ACCEPT_USER_REQUEST,
    DEFAULT_BLOCK_SIZE,
    DEFAULT_DEBUG,
    DEFAULT_ENABLED,
    DEFAULT_LK_CRITERIA_COUNT,
    DEFAULT_LK_CRITERIA_EPS,
    DEFAULT_LK_MAX_LEVEL,
    DEFAULT_LK_WINDOW_SIZE,
    DEFAULT_MAX_CORNERS,
    DEFAULT_MIN_DISTANCE_PX,
    DEFAULT_MIN_FEATURES,
    DEFAULT_QUALITY_LEVEL,
    DEFAULT_REQUEST_SEARCH_SIZE,
    DEFAULT_ROI_ADJUST_STEP_PX,
    DEFAULT_ROI_RESIZE_STEP_PX,
    META_FIELD_DX,
    META_FIELD_DY,
    META_FIELD_SCORE,
    META_FIELD_STATUS,
    META_NAME,
    PROP_ACCEPT_UPSTREAM_REQUEST,
    PROP_ACCEPT_USER_REQUEST,
    PROP_BLOCK_SIZE,
    PROP_DEBUG,
    PROP_ENABLED,
    PROP_LK_CRITERIA_COUNT,
    PROP_LK_CRITERIA_EPS,
    PROP_LK_MAX_LEVEL,
    PROP_LK_WINDOW_SIZE,
    PROP_MAX_CORNERS,
    PROP_MIN_DISTANCE_PX,
    PROP_MIN_FEATURES,
    PROP_QUALITY_LEVEL,
    PROP_REQUEST_SEARCH_SIZE,
    PROP_ROI_ADJUST_STEP_PX,
    PROP_ROI_RESIZE_STEP_PX,
    STATUS_BREAK,
    STATUS_OFF,
    STATUS_TRACK,
    TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT,
    TRACKER_DEBUG_FIELD_FEATURES_JSON,
    TRACKER_DEBUG_FIELD_FRAME_NUMBER,
    TRACKER_DEBUG_FIELD_STATUS,
    TRACKER_DEBUG_MESSAGE_NAME,
    TRACK_REQUEST_FIELD_DELTA_X,
    TRACK_REQUEST_FIELD_DELTA_Y,
    TRACK_REQUEST_FIELD_HEIGHT,
    TRACK_REQUEST_FIELD_SOURCE,
    TRACK_REQUEST_FIELD_TYPE,
    TRACK_REQUEST_FIELD_WIDTH,
    TRACK_REQUEST_FIELD_X,
    TRACK_REQUEST_FIELD_Y,
    TRACK_REQUEST_NAME,
    TRACK_REQUEST_SOURCE_USER,
    TRACK_REQUEST_TYPE_ADJUST_ROI,
    TRACK_REQUEST_TYPE_POINT,
    TRACK_REQUEST_TYPE_RESIZE_ROI,
    TRACK_REQUEST_TYPE_STOP,
    Roi,
    adjust_roi,
    build_centered_roi,
    compute_roi_offset,
    compute_tracker_score,
    resize_roi,
)

gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")
from gi.repository import GObject, Gst, GstBase  # noqa: E402

Gst.init(None)

# region metadata ctypes interop
G_TYPE_INT = 24
G_TYPE_FLOAT = 56


class GValue(ctypes.Structure):
    _fields_ = (
        ("g_type", ctypes.c_size_t),
        ("data", ctypes.c_uint64 * 2),
    )


_gst = ctypes.CDLL(ctypes.util.find_library("gstreamer-1.0"))
_gobject = ctypes.CDLL(ctypes.util.find_library("gobject-2.0"))

_gst.gst_custom_meta_get_structure.argtypes = [ctypes.c_void_p]
_gst.gst_custom_meta_get_structure.restype = ctypes.c_void_p
_gst.gst_structure_set_value.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
]
_gst.gst_structure_set_value.restype = None

_gobject.g_value_init.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
_gobject.g_value_init.restype = ctypes.c_void_p
_gobject.g_value_set_int.argtypes = [ctypes.c_void_p, ctypes.c_int]
_gobject.g_value_set_int.restype = None
_gobject.g_value_set_float.argtypes = [ctypes.c_void_p, ctypes.c_float]
_gobject.g_value_set_float.restype = None
_gobject.g_value_unset.argtypes = [ctypes.c_void_p]
_gobject.g_value_unset.restype = None

if Gst.Meta.get_info(META_NAME) is None:
    Gst.Meta.register_custom_simple(META_NAME)

_CV_MODULES: tuple[object, object] | None = None
_CV_IMPORT_ATTEMPTED = False


def load_cv_modules() -> tuple[object, object] | None:
    global _CV_IMPORT_ATTEMPTED, _CV_MODULES
    if _CV_IMPORT_ATTEMPTED:
        return _CV_MODULES

    _CV_IMPORT_ATTEMPTED = True
    try:
        import cv2
        import numpy
    except ModuleNotFoundError as exc:
        logger.warning("OpenCV tracking unavailable reason={}", exc)
        _CV_MODULES = None
        return None

    _CV_MODULES = (cv2, numpy)
    return _CV_MODULES


def set_meta_int(custom_meta: object, name: str, value: int) -> None:
    structure = _gst.gst_custom_meta_get_structure(hash(custom_meta))
    gvalue = GValue()

    _gobject.g_value_init(ctypes.byref(gvalue), G_TYPE_INT)
    _gobject.g_value_set_int(ctypes.byref(gvalue), value)
    _gst.gst_structure_set_value(
        structure,
        name.encode("utf-8"),
        ctypes.byref(gvalue),
    )
    _gobject.g_value_unset(ctypes.byref(gvalue))


def set_meta_float(custom_meta: object, name: str, value: float) -> None:
    structure = _gst.gst_custom_meta_get_structure(hash(custom_meta))
    gvalue = GValue()

    _gobject.g_value_init(ctypes.byref(gvalue), G_TYPE_FLOAT)
    _gobject.g_value_set_float(ctypes.byref(gvalue), value)
    _gst.gst_structure_set_value(
        structure,
        name.encode("utf-8"),
        ctypes.byref(gvalue),
    )
    _gobject.g_value_unset(ctypes.byref(gvalue))
# endregion metadata ctypes interop

PROPERTY_DEFAULTS = {
    PROP_ENABLED: DEFAULT_ENABLED,
    PROP_DEBUG: DEFAULT_DEBUG,
    PROP_MAX_CORNERS: DEFAULT_MAX_CORNERS,
    PROP_QUALITY_LEVEL: DEFAULT_QUALITY_LEVEL,
    PROP_MIN_DISTANCE_PX: DEFAULT_MIN_DISTANCE_PX,
    PROP_MIN_FEATURES: DEFAULT_MIN_FEATURES,
    PROP_BLOCK_SIZE: DEFAULT_BLOCK_SIZE,
    PROP_LK_WINDOW_SIZE: DEFAULT_LK_WINDOW_SIZE,
    PROP_LK_MAX_LEVEL: DEFAULT_LK_MAX_LEVEL,
    PROP_LK_CRITERIA_COUNT: DEFAULT_LK_CRITERIA_COUNT,
    PROP_LK_CRITERIA_EPS: DEFAULT_LK_CRITERIA_EPS,
    PROP_REQUEST_SEARCH_SIZE: DEFAULT_REQUEST_SEARCH_SIZE,
    PROP_ROI_ADJUST_STEP_PX: DEFAULT_ROI_ADJUST_STEP_PX,
    PROP_ROI_RESIZE_STEP_PX: DEFAULT_ROI_RESIZE_STEP_PX,
    PROP_ACCEPT_UPSTREAM_REQUEST: DEFAULT_ACCEPT_UPSTREAM_REQUEST,
    PROP_ACCEPT_USER_REQUEST: DEFAULT_ACCEPT_USER_REQUEST,
}


class BtOpticalFlow(GstBase.BaseTransform):
    __gstmetadata__ = (
        "BT Optical Flow Tracker",
        "Filter/Video",
        "Tracks video motion with optical flow and emits tracker metadata",
        "bt_ws",
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            "src",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string("video/x-raw,format=RGBA"),
        ),
        Gst.PadTemplate.new(
            "sink",
            Gst.PadDirection.SINK,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string("video/x-raw,format=RGBA"),
        ),
    )

    #region properties
    __gproperties__ = {
        PROP_ENABLED: (
            bool,
            "Enabled",
            "Enable or disable optical-flow tracking",
            DEFAULT_ENABLED,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_DEBUG: (
            bool,
            "Debug",
            "Enable per-frame tracker debug bus messages",
            DEFAULT_DEBUG,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_MAX_CORNERS: (
            int,
            "Max corners",
            "Maximum features to detect and track",
            1,
            10000,
            DEFAULT_MAX_CORNERS,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_QUALITY_LEVEL: (
            float,
            "Quality level",
            "Minimum accepted feature quality",
            0.0,
            1.0,
            DEFAULT_QUALITY_LEVEL,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_MIN_DISTANCE_PX: (
            float,
            "Minimum distance",
            "Minimum distance between detected features",
            0.0,
            10000.0,
            DEFAULT_MIN_DISTANCE_PX,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_MIN_FEATURES: (
            int,
            "Minimum features",
            "Minimum valid tracked features before tracker is considered lost",
            0,
            10000,
            DEFAULT_MIN_FEATURES,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_BLOCK_SIZE: (
            int,
            "Block size",
            "Neighborhood size used by feature detection",
            1,
            1000,
            DEFAULT_BLOCK_SIZE,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_LK_WINDOW_SIZE: (
            int,
            "LK window size",
            "Optical-flow search window size",
            1,
            1000,
            DEFAULT_LK_WINDOW_SIZE,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_LK_MAX_LEVEL: (
            int,
            "LK max level",
            "Maximum pyramid level for LK optical flow",
            0,
            100,
            DEFAULT_LK_MAX_LEVEL,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_LK_CRITERIA_COUNT: (
            int,
            "LK criteria count",
            "Maximum LK solver iterations",
            1,
            10000,
            DEFAULT_LK_CRITERIA_COUNT,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_LK_CRITERIA_EPS: (
            float,
            "LK criteria epsilon",
            "LK solver convergence epsilon",
            0.0,
            1.0,
            DEFAULT_LK_CRITERIA_EPS,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_REQUEST_SEARCH_SIZE: (
            int,
            "Request search size",
            "Square search size around a point request",
            1,
            10000,
            DEFAULT_REQUEST_SEARCH_SIZE,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_ROI_ADJUST_STEP_PX: (
            int,
            "ROI adjust step",
            "Default relative pixel step for user ROI adjustment controls",
            1,
            10000,
            DEFAULT_ROI_ADJUST_STEP_PX,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_ROI_RESIZE_STEP_PX: (
            int,
            "ROI resize step",
            "Default pixel step for user ROI resize controls",
            1,
            10000,
            DEFAULT_ROI_RESIZE_STEP_PX,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_ACCEPT_UPSTREAM_REQUEST: (
            bool,
            "Accept upstream request",
            "Allow upstream plugin request metadata",
            DEFAULT_ACCEPT_UPSTREAM_REQUEST,
            GObject.ParamFlags.READWRITE,
        ),
        PROP_ACCEPT_USER_REQUEST: (
            bool,
            "Accept user request",
            "Allow user click/event requests",
            DEFAULT_ACCEPT_USER_REQUEST,
            GObject.ParamFlags.READWRITE,
        ),
    }
    #endregion properties

    def __init__(self) -> None:
        super().__init__()
        self._property_values = dict(PROPERTY_DEFAULTS)
        self._frame_width = 0
        self._frame_height = 0
        self._pending_point: tuple[int, int] | None = None
        self._active_roi: Roi | None = None
        self._previous_gray: object | None = None
        self._feature_points: object | None = None
        self._needs_feature_init = False
        self._frame_number = 0

    # region do methods
    # region do get/set property
    def do_get_property(self, prop: object) -> object:
        if prop.name in self._property_values:
            return self._property_values[prop.name]
        raise AttributeError(f"unknown property {prop.name}")

    def do_set_property(self, prop: object, value: object) -> None:
        if prop.name not in self._property_values:
            raise AttributeError(f"unknown property {prop.name}")
        self._property_values[prop.name] = value
    # endregion do get/set property
    
    def do_set_caps(self, incaps: Gst.Caps, outcaps: Gst.Caps) -> bool:
        structure = incaps.get_structure(0)
        self._frame_width = structure.get_value("width") or 0
        self._frame_height = structure.get_value("height") or 0
        return True

    def do_sink_event(self, event: Gst.Event) -> bool:
        if event.type == Gst.EventType.CUSTOM_DOWNSTREAM:
            structure = event.get_structure()
            if structure is not None and structure.get_name() == TRACK_REQUEST_NAME:
                return self._handle_track_request(structure)
        return GstBase.BaseTransform.do_sink_event(self, event)

    def do_transform_ip(self, buffer: Gst.Buffer) -> Gst.FlowReturn:
        meta = buffer.add_custom_meta(META_NAME)
        if meta is None:
            return Gst.FlowReturn.ERROR

        self._frame_number += 1
        dx = 0
        dy = 0
        score = 0.0
        status = STATUS_BREAK if self._property_values[PROP_ENABLED] else STATUS_OFF

        if self._property_values[PROP_ENABLED]:
            self._activate_pending_roi()
            dx, dy, score, status = self._process_tracking(buffer)
            self._draw_active_roi(buffer, status)

        set_meta_int(meta, META_FIELD_DX, dx)
        set_meta_int(meta, META_FIELD_DY, dy)
        set_meta_float(meta, META_FIELD_SCORE, score)
        set_meta_int(meta, META_FIELD_STATUS, status)
        self._post_debug_message(status)

        return Gst.FlowReturn.OK
    #endregion do methods

    def _handle_track_request(self, structure: Gst.Structure) -> bool:
        if not self._property_values[PROP_ACCEPT_USER_REQUEST]:
            return True
        if structure.get_value(TRACK_REQUEST_FIELD_SOURCE) != TRACK_REQUEST_SOURCE_USER:
            return True

        request_type = structure.get_value(TRACK_REQUEST_FIELD_TYPE)
        if request_type == TRACK_REQUEST_TYPE_STOP:
            self._reset_tracking(clear_roi=True)
            logger.info("track stop request received")
            return True
        if request_type == TRACK_REQUEST_TYPE_RESIZE_ROI:
            self._resize_active_roi(structure)
            return True
        if request_type == TRACK_REQUEST_TYPE_ADJUST_ROI:
            self._adjust_active_roi(structure)
            return True
        if request_type != TRACK_REQUEST_TYPE_POINT:
            return True

        x = structure.get_value(TRACK_REQUEST_FIELD_X)
        y = structure.get_value(TRACK_REQUEST_FIELD_Y)
        if x is None or y is None:
            return True

        self._pending_point = (int(x), int(y))
        logger.info("track request received on frame ID: {}", self._frame_number)
        self._activate_pending_roi()
        return True

    # region ROI manipulation
    def _resize_active_roi(self, structure: Gst.Structure) -> None:
        if self._active_roi is None or self._frame_width <= 0 or self._frame_height <= 0:
            logger.info("track resize request ignored reason=no-active-roi")
            return

        width = structure.get_value(TRACK_REQUEST_FIELD_WIDTH)
        height = structure.get_value(TRACK_REQUEST_FIELD_HEIGHT)
        if width is None or height is None:
            logger.info("track resize request ignored reason=missing-size")
            return

        self._active_roi = resize_roi(
            self._active_roi,
            width=int(width),
            height=int(height),
            frame_width=self._frame_width,
            frame_height=self._frame_height,
        )
        self._mark_reacquire_needed()
        logger.info(
            "track resize request received width={} height={} roi_x={} roi_y={} "
            "roi_width={} roi_height={}",
            int(width),
            int(height),
            self._active_roi.x,
            self._active_roi.y,
            self._active_roi.width,
            self._active_roi.height,
        )

    def _adjust_active_roi(self, structure: Gst.Structure) -> None:
        if self._active_roi is None or self._frame_width <= 0 or self._frame_height <= 0:
            logger.info("track adjust request ignored reason=no-active-roi")
            return

        delta_x = structure.get_value(TRACK_REQUEST_FIELD_DELTA_X)
        delta_y = structure.get_value(TRACK_REQUEST_FIELD_DELTA_Y)
        if delta_x is None or delta_y is None:
            logger.info("track adjust request ignored reason=missing-delta")
            return

        self._active_roi = adjust_roi(
            self._active_roi,
            delta_x=int(delta_x),
            delta_y=int(delta_y),
            frame_width=self._frame_width,
            frame_height=self._frame_height,
        )
        self._mark_reacquire_needed()
        logger.info(
            "track adjust request received delta_x={} delta_y={} roi_x={} roi_y={} "
            "roi_width={} roi_height={}",
            int(delta_x),
            int(delta_y),
            self._active_roi.x,
            self._active_roi.y,
            self._active_roi.width,
            self._active_roi.height,
        )

    # endregion ROI manipulation
    
    def _activate_pending_roi(self) -> None:
        """
        
        """
        if self._pending_point is None or self._frame_width <= 0 or self._frame_height <= 0:
            # logger.debug(
            #     "activate pending roi skipped pending_point={} frame_width={} frame_height={}",
            #     self._pending_point,
            #     self._frame_width,
            #     self._frame_height,
            # )
            return

        x, y = self._pending_point
        self._active_roi = build_centered_roi(
            x=x,
            y=y,
            size=int(self._property_values[PROP_REQUEST_SEARCH_SIZE]),
            frame_width=self._frame_width,
            frame_height=self._frame_height,
        )
        logger.info(
            "activate pending roi frame ID={}", self._frame_number
        )
        self._pending_point = None
        self._mark_reacquire_needed()

    def _process_tracking(self, buffer: Gst.Buffer) -> tuple[int, int, float, int]:
        """
        Returns (dx, dy, score, status)

        """
        if self._active_roi is None:
            return 0, 0, 0.0, STATUS_BREAK

        gray = self._buffer_to_gray(buffer)
        if gray is None:
            return 0, 0, 0.0, STATUS_BREAK

        # first frame on first request (resize or adjust) or new pending point
        if (
            self._needs_feature_init
            or self._feature_points is None
            or self._previous_gray is None
        ):
            # get good features to track within the active ROI and initialize tracking state
            return self._initialize_features(gray)

        return self._track_features(gray)

    def _buffer_to_gray(self, buffer: Gst.Buffer) -> object | None:
        modules = load_cv_modules()
        if modules is None:
            return None

        cv2, np = modules
        if self._frame_width <= 0 or self._frame_height <= 0:
            return None

        expected_size = self._frame_width * self._frame_height * 4
        if buffer.get_size() < expected_size:
            return None

        rgba = np.frombuffer(
            buffer.extract_dup(0, expected_size),
            dtype=np.uint8,
        ).reshape((self._frame_height, self._frame_width, 4))
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY)

    def _initialize_features(self, gray: object) -> tuple[int, int, float, int]:
        modules = load_cv_modules()
        if modules is None or self._active_roi is None:
            return 0, 0, 0.0, STATUS_BREAK

        cv2, np = modules
        roi = self._active_roi
        crop = gray[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
        features = cv2.goodFeaturesToTrack(
            crop,
            maxCorners=int(self._property_values[PROP_MAX_CORNERS]),
            qualityLevel=float(self._property_values[PROP_QUALITY_LEVEL]),
            minDistance=float(self._property_values[PROP_MIN_DISTANCE_PX]),
            blockSize=int(self._property_values[PROP_BLOCK_SIZE]),
        )

        self._previous_gray = gray
        self._needs_feature_init = False
        min_features = int(self._property_values[PROP_MIN_FEATURES])
        if features is None or len(features) < min_features:
            self._reset_tracking(clear_roi=True, previous_gray=gray)
            logger.info(
                "feature init failed feature_count={} min_features={}",
                0 if features is None else len(features),
                min_features,
            )
            return 0, 0, 0.0, STATUS_BREAK

        features = features.astype(np.float32)
        features[:, 0, 0] += float(roi.x)
        features[:, 0, 1] += float(roi.y)
        self._feature_points = features
        dx, dy = compute_roi_offset(roi, self._frame_width, self._frame_height)
        score = compute_tracker_score(
            len(features),
            int(self._property_values[PROP_MAX_CORNERS]),
        )
        return dx, dy, score, STATUS_TRACK

    #lucas-kanade optical flow tracking
    def _track_features(self, gray: object) -> tuple[int, int, float, int]:
        modules = load_cv_modules()
        if (
            modules is None
            or self._previous_gray is None
            or self._feature_points is None
            or self._active_roi is None
        ):
            return 0, 0, 0.0, STATUS_BREAK

        cv2, np = modules
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            int(self._property_values[PROP_LK_CRITERIA_COUNT]),
            float(self._property_values[PROP_LK_CRITERIA_EPS]),
        )
        next_points, point_status, _error = cv2.calcOpticalFlowPyrLK(
            self._previous_gray,
            gray,
            self._feature_points,
            None,
            winSize=(
                int(self._property_values[PROP_LK_WINDOW_SIZE]),
                int(self._property_values[PROP_LK_WINDOW_SIZE]),
            ),
            maxLevel=int(self._property_values[PROP_LK_MAX_LEVEL]),
            criteria=criteria,
        )

        if next_points is None or point_status is None:
            self._reset_tracking(clear_roi=True, previous_gray=gray)
            return 0, 0, 0.0, STATUS_BREAK

        good_mask = point_status.reshape(-1) == 1
        good_new = next_points[good_mask]
        good_old = self._feature_points[good_mask]
        # break tracking if too few good points
        min_features = int(self._property_values[PROP_MIN_FEATURES])
        if len(good_new) < min_features:
            self._reset_tracking(clear_roi=True, previous_gray=gray)
            return 0, 0, 0.0, STATUS_BREAK

        # Use the per-axis median displacement as a robust estimate of dominant ROI motion.
        # Compared with the mean, the median is less affected by bad LK tracks and
        # independently moving points; see robust statistics / median absolute deviation.
        # LK points are shaped (N, 1, 2); flatten to (N, 2) so median runs per axis.
        original_roi = self._active_roi
        median_motion = np.median((good_new - good_old).reshape(-1, 2), axis=0)
        move_x = round(float(median_motion[0]))
        move_y = round(float(median_motion[1]))
        # set the ROI to new position
        moved_roi = adjust_roi(
            original_roi,
            delta_x=move_x,
            delta_y=move_y,
            frame_width=self._frame_width,
            frame_height=self._frame_height,
        )

        # region filter out points that moved out of the ROI
        good_new_points = good_new.reshape(-1, 2)
        in_roi_mask = (
            (good_new_points[:, 0] >= moved_roi.x)
            & (good_new_points[:, 0] < moved_roi.x + moved_roi.width)
            & (good_new_points[:, 1] >= moved_roi.y)
            & (good_new_points[:, 1] < moved_roi.y + moved_roi.height)
        )
        good_new = good_new[in_roi_mask]
        good_old = good_old[in_roi_mask]
        if len(good_new) < min_features:
            self._reset_tracking(clear_roi=True, previous_gray=gray)
            return 0, 0, 0.0, STATUS_BREAK

        # calc median again
        median_motion = np.median((good_new - good_old).reshape(-1, 2), axis=0)
        move_x = round(float(median_motion[0]))
        move_y = round(float(median_motion[1]))

        self._active_roi = adjust_roi(
            original_roi,
            delta_x=move_x,
            delta_y=move_y,
            frame_width=self._frame_width,
            frame_height=self._frame_height,
        )
        # endregion filter out points that moved out of the ROI

        self._feature_points = good_new.reshape(-1, 1, 2).astype(np.float32)
        self._previous_gray = gray
        # dx,dy from frame center, delta between current ROI center and frame center
        dx, dy = compute_roi_offset(
            self._active_roi,
            self._frame_width,
            self._frame_height,
        )
        score = compute_tracker_score(
            len(good_new),
            int(self._property_values[PROP_MAX_CORNERS]),
        )
        return dx, dy, score, STATUS_TRACK

    def _reset_tracking(
        self,
        *,
        clear_roi: bool,
        previous_gray: object | None = None,
    ) -> None:
        self._pending_point = None
        if clear_roi:
            self._active_roi = None
        self._previous_gray = previous_gray
        self._feature_points = None
        self._needs_feature_init = False

    def _mark_reacquire_needed(self) -> None:
        self._previous_gray = None
        self._feature_points = None
        self._needs_feature_init = True

    #region debug  messages
    def _post_debug_message(self, status: int) -> None:
        if not self._property_values[PROP_DEBUG]:
            return

        structure = build_tracker_debug_structure(
            Gst,
            frame_number=self._frame_number,
            status=status,
            feature_points=self._feature_points if status == STATUS_TRACK else None,
        )
        self.post_message(Gst.Message.new_element(self, structure))
    #endregion debug  messages

    def _draw_active_roi(self, buffer: Gst.Buffer, status: int) -> None:
        if self._active_roi is None or self._frame_width <= 0 or self._frame_height <= 0:
            return

        expected_size = self._frame_width * self._frame_height * 4
        if buffer.get_size() < expected_size:
            return

        roi_color = ROI_DEBUG_COLOR if self._property_values[PROP_DEBUG] else ROI_COLOR
        data = bytearray(buffer.extract_dup(0, expected_size))
        draw_rgba_roi(
            data,
            self._frame_width,
            self._frame_height,
            self._active_roi,
            roi_color,
        )
        if self._property_values[PROP_DEBUG] and status == STATUS_TRACK:
            draw_debug_features(data, self._frame_width, self._frame_height, self._feature_points)
        buffer.fill(0, bytes(data))

# region debug message construction
def build_tracker_debug_structure(
    gst: object,
    *,
    frame_number: int,
    status: int,
    feature_points: object | None,
) -> object:
    features_json = serialize_debug_features(feature_points) if status == STATUS_TRACK else "[]"
    structure = gst.Structure.new_empty(TRACKER_DEBUG_MESSAGE_NAME)
    structure.set_value(TRACKER_DEBUG_FIELD_FRAME_NUMBER, int(frame_number))
    structure.set_value(TRACKER_DEBUG_FIELD_STATUS, int(status))
    structure.set_value(
        TRACKER_DEBUG_FIELD_ACTIVE_FEATURE_COUNT,
        len(json.loads(features_json)),
    )
    structure.set_value(TRACKER_DEBUG_FIELD_FEATURES_JSON, features_json)
    return structure


def serialize_debug_features(feature_points: object | None) -> str:
    if feature_points is None:
        return "[]"
    features = [
        {"x": float(point[0][0]), "y": float(point[0][1])}
        for point in feature_points
    ]
    return json.dumps(features, separators=(",", ":"))
#endregion debug message construction

# region debug drawing
RGBAColor = tuple[int, int, int, int]
ROI_COLOR: RGBAColor = (255, 0, 0, 255)
ROI_DEBUG_COLOR: RGBAColor = (255, 255, 0, 255)
FEATURE_DEBUG_COLOR: RGBAColor = (0, 255, 0, 255)


def draw_rgba_roi(
    data: bytearray,
    frame_width: int,
    frame_height: int,
    roi: Roi,
    color: RGBAColor = ROI_COLOR,
) -> None:
    x0 = roi.x
    y0 = roi.y
    x1 = min(frame_width - 1, roi.x + roi.width - 1)
    y1 = min(frame_height - 1, roi.y + roi.height - 1)

    # Draw a thicker border by drawing multiple offset outlines.
    border_thickness = 2  # increase for a bolder border
    for i in range(border_thickness):
        xi0 = max(0, x0 - i)
        yi0 = max(0, y0 - i)
        xi1 = min(frame_width - 1, x1 + i)
        yi1 = min(frame_height - 1, y1 + i)

        for x in range(xi0, xi1 + 1):
            set_rgba_pixel(data, frame_width, x, yi0, color)
            set_rgba_pixel(data, frame_width, x, yi1, color)

        for y in range(yi0, yi1 + 1):
            set_rgba_pixel(data, frame_width, xi0, y, color)
            set_rgba_pixel(data, frame_width, xi1, y, color)


def draw_debug_features(
    data: bytearray,
    frame_width: int,
    frame_height: int,
    feature_points: object | None,
) -> None:
    if feature_points is None:
        return

    # Use a filled square around each feature for a bolder marker.
    radius = 1  # increase to 2 for a 5x5 marker
    for point in feature_points:
        x = round(float(point[0][0]))
        y = round(float(point[0][1]))
        for dy in range(-radius, radius + 1):
            py = y + dy
            if py < 0 or py >= frame_height:
                continue
            for dx in range(-radius, radius + 1):
                px = x + dx
                if 0 <= px < frame_width:
                    set_rgba_pixel(data, frame_width, px, py, FEATURE_DEBUG_COLOR)


def set_rgba_pixel(
    data: bytearray,
    frame_width: int,
    x: int,
    y: int,
    color: RGBAColor,
) -> None:
    offset = ((y * frame_width) + x) * 4
    data[offset : offset + 4] = bytes(color)

#endregion debug drawing

GObject.type_register(BtOpticalFlow)
__gstelementfactory__ = ("bt_optical_flow", Gst.Rank.NONE, BtOpticalFlow)

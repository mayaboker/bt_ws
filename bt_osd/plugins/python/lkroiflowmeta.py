#!/usr/bin/env python3

import json

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")

from gi.repository import Gst, GObject, GstBase
import cv2
import numpy as np

Gst.init(None)


class LkRoiFlowMeta(GstBase.BaseTransform):
    __gstmetadata__ = (
        "LK ROI Optical Flow Metadata",
        "Filter/Effect/Video",
        "Lucas-Kanade optical flow with JSON metadata source pad",
        "Amir",
    )

    __gsttemplates__ = (
    Gst.PadTemplate.new(
        "sink",
        Gst.PadDirection.SINK,
        Gst.PadPresence.ALWAYS,
        Gst.Caps.from_string("video/x-raw,format=BGR"),
    ),
    Gst.PadTemplate.new(
        "src",
        Gst.PadDirection.SRC,
        Gst.PadPresence.ALWAYS,
        Gst.Caps.from_string("video/x-raw,format=BGR"),
    ),
    Gst.PadTemplate.new(
        "meta",
        Gst.PadDirection.SRC,
        Gst.PadPresence.SOMETIMES,
        Gst.Caps.from_string("application/x-lkroiflow-roi,format=json"),
    ),
    )

    __gproperties__ = {
        "x1": (int, "ROI x1", "Left ROI coordinate", 0, 10000, 100, GObject.ParamFlags.READWRITE),
        "y1": (int, "ROI y1", "Top ROI coordinate", 0, 10000, 100, GObject.ParamFlags.READWRITE),
        "x2": (int, "ROI x2", "Right ROI coordinate", 0, 10000, 300, GObject.ParamFlags.READWRITE),
        "y2": (int, "ROI y2", "Bottom ROI coordinate", 0, 10000, 300, GObject.ParamFlags.READWRITE),
        "max-points": (int, "Max points", "Maximum feature points", 1, 1000, 100, GObject.ParamFlags.READWRITE),
    }

    def __init__(self):
        super().__init__()

        self.x1 = 100
        self.y1 = 100
        self.x2 = 300
        self.y2 = 300
        self.max_points = 100

        self.width = None
        self.height = None

        self.prev_gray_roi = None
        self.prev_points = None
        self.roi_offset = None
        self.prev_roi = None
        self._meta_started = False

        meta_template = self.get_pad_template("meta")
        self.meta_srcpad = Gst.Pad.new_from_template(meta_template, "meta")
        self.meta_srcpad.set_active(True)
        self.add_pad(self.meta_srcpad)

    def do_get_property(self, prop):
        return getattr(self, prop.name.replace("-", "_"))

    def do_set_property(self, prop, value):
        setattr(self, prop.name.replace("-", "_"), value)
        self._reset_tracking()

    def do_set_caps(self, incaps, outcaps):
        s = incaps.get_structure(0)
        self.width = s.get_value("width")
        self.height = s.get_value("height")
        self._reset_tracking()
        return True

    def _reset_tracking(self):
        self.prev_gray_roi = None
        self.prev_points = None
        self.roi_offset = None
        self.prev_roi = None

    def _valid_roi(self):
        x1 = max(0, min(self.x1, self.width - 1))
        y1 = max(0, min(self.y1, self.height - 1))
        x2 = max(0, min(self.x2, self.width))
        y2 = max(0, min(self.y2, self.height))

        if x2 <= x1 or y2 <= y1:
            return None

        return x1, y1, x2, y2

    def _detect_points(self, gray_roi):
        points = cv2.goodFeaturesToTrack(
            gray_roi,
            maxCorners=self.max_points,
            qualityLevel=0.01,
            minDistance=7,
            blockSize=7,
        )
        return points

    def do_transform_ip(self, buf: Gst.Buffer):
        ok, map_info = buf.map(Gst.MapFlags.READ | Gst.MapFlags.WRITE)
        if not ok:
            return Gst.FlowReturn.ERROR

        try:
            frame = np.ndarray(
                shape=(self.height, self.width, 3),
                dtype=np.uint8,
                buffer=map_info.data,
            )

            roi = self._valid_roi()
            if roi is None:
                return Gst.FlowReturn.OK

            x1, y1, x2, y2 = roi

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray_roi = gray[y1:y2, x1:x2]
            track_x1, track_y1 = x1, y1

            if (
                self.prev_gray_roi is None
                or self.prev_points is None
                or self.prev_roi != roi
                or self.prev_gray_roi.shape != gray_roi.shape
                or len(self.prev_points) == 0
            ):
                self._start_tracking(gray_roi, roi)

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
                return Gst.FlowReturn.OK

            next_points, status, _err = cv2.calcOpticalFlowPyrLK(
                self.prev_gray_roi,
                gray_roi,
                self.prev_points,
                None,
                winSize=(21, 21),
                maxLevel=3,
                criteria=(
                    cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                    30,
                    0.01,
                ),
            )

            if next_points is None or status is None:
                self._start_tracking(gray_roi, roi)
                return Gst.FlowReturn.OK

            good_old = self.prev_points[status.flatten() == 1]
            good_new = next_points[status.flatten() == 1]

            if len(good_new) < 5:
                self._start_tracking(gray_roi, roi)
                return Gst.FlowReturn.OK

            motion = good_new - good_old
            dx = float(np.median(motion[:, 0, 0]))
            dy = float(np.median(motion[:, 0, 1]))

            self.x1 += int(round(dx))
            self.x2 += int(round(dx))
            self.y1 += int(round(dy))
            self.y2 += int(round(dy))

            roi = self._valid_roi()
            if roi:
                x1, y1, x2, y2 = roi
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                self._push_roi_metadata(buf, roi, dx, dy, len(good_new))

                for p in good_new:
                    px = int(p[0][0] + track_x1)
                    py = int(p[0][1] + track_y1)
                    cv2.circle(frame, (px, py), 2, (0, 0, 255), -1)

                next_gray_roi = gray[y1:y2, x1:x2]
                self._start_tracking(next_gray_roi, roi)
            else:
                self._reset_tracking()

        finally:
            buf.unmap(map_info)

        return Gst.FlowReturn.OK

    def _start_tracking(self, gray_roi, roi):
        self.prev_gray_roi = gray_roi.copy()
        self.prev_points = self._detect_points(gray_roi)
        self.roi_offset = (roi[0], roi[1])
        self.prev_roi = roi

    def _push_roi_metadata(self, buf, roi, dx, dy, point_count):
        if not self.meta_srcpad.is_linked():
            return

        self._ensure_meta_stream()
        x1, y1, x2, y2 = roi
        metadata = {
            "x1": int(x1),
            "y1": int(y1),
            "x2": int(x2),
            "y2": int(y2),
            "dx": float(dx),
            "dy": float(dy),
            "points": int(point_count),
            "pts": int(buf.pts),
        }
        payload = (json.dumps(metadata, separators=(",", ":")) + "\n").encode("utf-8")
        meta_buf = Gst.Buffer.new_allocate(None, len(payload), None)
        meta_buf.fill(0, payload)
        meta_buf.pts = buf.pts
        meta_buf.dts = buf.dts
        meta_buf.duration = buf.duration
        self.meta_srcpad.push(meta_buf)

    def _ensure_meta_stream(self):
        if self._meta_started:
            return

        self.meta_srcpad.push_event(Gst.Event.new_stream_start("lkroiflow-meta"))
        self.meta_srcpad.push_event(
            Gst.Event.new_caps(Gst.Caps.from_string("application/x-lkroiflow-roi,format=json"))
        )
        segment = Gst.Segment()
        segment.init(Gst.Format.TIME)
        self.meta_srcpad.push_event(Gst.Event.new_segment(segment))
        self._meta_started = True


GObject.type_register(LkRoiFlowMeta)
__gstelementfactory__ = ("lkroiflowmeta", Gst.Rank.NONE, LkRoiFlowMeta)

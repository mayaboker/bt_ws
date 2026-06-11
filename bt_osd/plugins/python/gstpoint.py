#!/usr/bin/env python3

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")

from gi.repository import Gst, GstBase, GObject

Gst.init(None)


class GstPointOverlay(GstBase.BaseTransform):
    __gstmetadata__ = (
        "PointOverlay",
        "Transform",
        "Draw point on frame",
        "ChatGPT",
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            "sink",
            Gst.PadDirection.SINK,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string(
                "video/x-raw,format=BGR"
            ),
        ),
        Gst.PadTemplate.new(
            "src",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string(
                "video/x-raw,format=BGR"
            ),
        ),
    )

    __gproperties__ = {
        "x": (
            GObject.TYPE_FLOAT,
            "X",
            "Normalized X position of the point (0.0 - 1.0)",
            0.0,
            1.0,
            0.5,
            GObject.ParamFlags.READWRITE,
        ),
        "y": (
            GObject.TYPE_FLOAT,
            "Y",
            "Normalized Y position of the point (0.0 - 1.0)",
            0.0,
            1.0,
            0.5,
            GObject.ParamFlags.READWRITE,
        ),
    }

    def __init__(self):
        super().__init__()
        self._x = 0.5
        self._y = 0.5

    def do_get_property(self, prop):
        if prop.name == "x":
            return float(self._x)
        if prop.name == "y":
            return float(self._y)
        raise AttributeError("Unknown property: %s" % prop.name)

    def do_set_property(self, prop, value):
        if prop.name == "x":
            self._x = float(value)
            return
        if prop.name == "y":
            self._y = float(value)
            return
        raise AttributeError("Unknown property: %s" % prop.name)

    def do_transform_ip(self, buf: Gst.Buffer):
        """
        In-place transform function that draws a point on the video frame.
        modify the same buffer memory that is passed in, rather than creating a new buffer for output.
        """

        # GStreamer buffers are not directly accessible. We need to map them to get a pointer to the memory.
        success, map_info = buf.map(Gst.MapFlags.READ | Gst.MapFlags.WRITE)
        if not success:
            return Gst.FlowReturn.ERROR

        try:
            # Caps describe the frame format.
            caps = self.sinkpad.get_current_caps()
            structure = caps.get_structure(0)

            width = structure.get_value("width")
            height = structure.get_value("height")

            # create NumPy view
            frame = np.ndarray(
                (height, width, 3),
                dtype=np.uint8,
                buffer=map_info.data,
            )

            # compute point using normalized x/y properties (0.0..1.0)
            cx = int(self._x * (width - 1))
            cy = int(self._y * (height - 1))

            cv2.circle(
                frame,
                (cx, cy),
                10,
                (0, 0, 255),
                -1,
            )

        finally:
            #  Release buffer access.
            buf.unmap(map_info)

        return Gst.FlowReturn.OK


GObject.type_register(GstPointOverlay)

__gstelementfactory__ = (
    "pointoverlay",
    Gst.Rank.NONE,
    GstPointOverlay,
)
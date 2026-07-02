from collections import deque
from threading import Condition

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")

from gi.repository import GObject, Gst, GstBase

Gst.init(None)

DEFAULT_FPS = 30
CAPS_TEMPLATE = Gst.Caps.from_string(
    "video/x-raw,format=(string){ RGB, BGR, RGBA, BGRA, GRAY8 }"
)

PIXEL_FORMATS = {
    1: ("GRAY8", 1),  # L_INT8
    3: ("RGB", 3),  # RGB_INT8
    4: ("RGBA", 4),  # RGBA_INT8
    5: ("BGRA", 4),  # BGRA_INT8
    8: ("BGR", 3),  # BGR_INT8
}


class GazeboImageSrc(GstBase.BaseSrc):

    __gstmetadata__ = (
        "GazeboImageSrc",
        "Source/Video",
        "Reads camera images from a Gazebo Transport topic",
        "Amir",
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            "src",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            CAPS_TEMPLATE,
        ),
    )

    topic = GObject.Property(type=str, default="/camera")
    fps = GObject.Property(type=int, default=DEFAULT_FPS, minimum=1, maximum=240)
    debug = GObject.Property(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self._condition = Condition()
        self._frames = deque(maxlen=2)
        self._frame_number = 0
        self._node = None
        self._Image = None
        self._running = False
        self._received_frames = 0
        self._pushed_frames = 0
        self.set_format(Gst.Format.TIME)
        self.set_live(True)
        self.set_do_timestamp(True)

    def do_start(self):
        try:
            from gz.msgs10.image_pb2 import Image
            from gz.transport13 import Node
        except ImportError as exc:
            print(f"gzimagesrc: failed to import Gazebo Python modules: {exc}", flush=True)
            return False

        self._Image = Image
        self._node = Node()
        self._frame_number = 0
        self._received_frames = 0
        self._pushed_frames = 0
        self._running = True

        ok = self._node.subscribe(self._Image, self.topic, self.on_image)
        if not ok:
            print(f"gzimagesrc: failed to subscribe to {self.topic}", flush=True)
            self._running = False
            return False

        print(f"gzimagesrc: listening to {self.topic}", flush=True)
        return True

    def do_stop(self):
        with self._condition:
            self._running = False
            self._frames.clear()
            self._condition.notify_all()

        self._node = None
        self._Image = None
        return True

    def do_is_seekable(self):
        return False

    def on_image(self, msg):
        width = msg.width
        height = msg.height
        pixel_format = msg.pixel_format_type
        format_info = PIXEL_FORMATS.get(pixel_format)

        if format_info is None:
            print(
                "gzimagesrc: dropping frame with unsupported pixel format "
                f"{pixel_format}",
                flush=True,
            )
            return

        gst_format, bytes_per_pixel = format_info
        row_size = width * bytes_per_pixel
        step = msg.step or row_size
        data = bytes(msg.data)
        expected_size = step * height
        self._received_frames += 1

        if self.debug and self._received_frames == 1:
            print(
                "gzimagesrc: first frame "
                f"{width}x{height}, pixel_format={pixel_format}, "
                f"gst_format={gst_format}, step={step}, size={len(data)}",
                flush=True,
            )

        if step < row_size or len(data) < expected_size:
            print(
                "gzimagesrc: dropping frame with unsupported size "
                f"{len(data)}; expected at least {expected_size} "
                f"({width}x{height}, step={step})",
                flush=True,
            )
            return

        if step != row_size:
            data = b"".join(
                data[row_start : row_start + row_size]
                for row_start in range(0, expected_size, step)
            )

        with self._condition:
            self._frames.clear()
            self._frames.append((width, height, gst_format, data))
            self._condition.notify()

    def do_create(self, offset, size, buf):
        with self._condition:
            while self._running and not self._frames:
                self._condition.wait()

            if not self._running:
                return Gst.FlowReturn.FLUSHING, None

            width, height, gst_format, data = self._frames.popleft()

        caps = Gst.Caps.from_string(
            "video/x-raw,"
            f"format={gst_format},width={width},height={height},framerate={self.fps}/1"
        )
        self.set_caps(caps)

        buffer = Gst.Buffer.new_allocate(None, len(data), None)
        buffer.fill(0, data)
        buffer.duration = Gst.SECOND // self.fps
        buffer.offset = self._frame_number

        self._pushed_frames += 1
        if self.debug and self._pushed_frames == 1:
            print(
                "gzimagesrc: pushed first buffer "
                f"{width}x{height}, format={gst_format}, size={len(data)}",
                flush=True,
            )

        self._frame_number += 1

        return Gst.FlowReturn.OK, buffer


GObject.type_register(GazeboImageSrc)

__gstelementfactory__ = (
    "gzimagesrc",
    Gst.Rank.NONE,
    GazeboImageSrc,
)
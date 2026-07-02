import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
from gi.repository import Gst, GstBase, GObject

# 1. Define Plugin Metadata
Gst.init(None)

class PyCustomSrc(GstBase.BaseSrc):
    __gstmetadata__ = (
        'Custom Python Source Element',
        'Source/Video',
        'Generates custom data streams',
        'Your Name <you@example.com>'
    )

    # 2. Define Capabilities (Src Pad Template)
    __gsttemplates__ = Gst.PadTemplate.new(
        "src",
        Gst.PadDirection.SRC,
        Gst.PadPresence.ALWAYS,
        Gst.Caps.from_string("video/x-raw, format=RGBA, width=640, height=480, framerate=30/1")
    )

    def __init__(self):
        super(PyCustomSrc, self).__init__()
        # Configure plugin behavior (e.g., live source vs file source)
        self.set_live(True)
        self.set_format(Gst.Format.TIME)

    # 3. Core Generation Logic (Mandatory override)
    def do_create(self, offset, size):
        # Calculate buffer allocation size based on fixed video format
        # 640 * 480 * 4 bytes (RGBA) = 1,228,800 bytes
        buffer_size = 1228800 
        
        # Generate raw byte data (Example: Blue screen)
        # Sequence of [R, G, B, A] -> [0x00, 0x00, 0xFF, 0xFF]
        raw_bytes = bytes([0, 0, 255, 255] * (640 * 480))
        
        # Allocate new GStreamer buffer
        buf = Gst.Buffer.new_allocate(None, buffer_size, None)
        buf.fill(0, raw_bytes)
        
        # Handle buffer timestamps for media streaming clock sync
        duration = Gst.util_uint64_scale_int(1, Gst.SECOND, 30) # 30 fps duration
        buf.duration = duration
        
        return Gst.FlowReturn.OK, buf

# 4. Bind the class to GObject Type System
GObject.type_register(PyCustomSrc)
# Register the element to the GStreamer registry library
__gstelementfactory__ = ("customsrc", Gst.Rank.NONE, PyCustomSrc)
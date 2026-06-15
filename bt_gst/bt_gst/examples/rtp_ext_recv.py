#!/usr/bin/env python3

import gi
import struct

gi.require_version("Gst", "1.0")
gi.require_version("GstRtp", "1.0")

from gi.repository import Gst, GstRtp, GLib

Gst.init(None)

EXT_ID = 1


def bytes_from_gi_result(result):
    """
    PyGObject return shape for get_extension_onebyte_header() can vary.
    This helper tries to extract bytes defensively.
    """
    if result is None:
        return None

    if isinstance(result, tuple):
        success = result[0]
        if not success:
            return None

        for item in result[1:]:
            if isinstance(item, (bytes, bytearray, memoryview)):
                return bytes(item)

        return None

    if isinstance(result, (bytes, bytearray, memoryview)):
        return bytes(result)

    return None


def ntp64_to_float_seconds(data):
    """
    NTP 64-bit timestamp:
      high 32 bits = seconds
      low 32 bits  = fractional seconds
    """
    if data is None or len(data) < 8:
        return None

    seconds, fraction = struct.unpack(">II", data[:8])
    return seconds + fraction / float(1 << 32)


def rtp_probe(pad, info, user_data):
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    ok, rtp = GstRtp.RTPBuffer.map(buffer, Gst.MapFlags.READ)
    if not ok:
        return Gst.PadProbeReturn.OK

    seq = rtp.get_seq()
    ts = rtp.get_timestamp()
    marker = rtp.get_marker()
    has_ext = rtp.get_extension()

    ntp64_data = None
    ntp64_seconds = None

    if has_ext:
        # appbits=0 for the common one-byte RTP header extension case.
        result = rtp.get_extension_onebyte_header(EXT_ID, 0)
        ntp64_data = bytes_from_gi_result(result)
        ntp64_seconds = ntp64_to_float_seconds(ntp64_data)

    if ntp64_seconds is not None:
        print(
            f"recv RTP: seq={seq}, ts={ts}, marker={marker}, "
            f"ntp64={ntp64_seconds:.6f}"
        )
    else:
        print(
            f"recv RTP: seq={seq}, ts={ts}, marker={marker}, "
            f"has_ext={has_ext}, no ntp64"
        )

    rtp.unmap()
    return Gst.PadProbeReturn.OK


pipeline = Gst.parse_launch(
    'udpsrc port=5000 '
    'caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! '
    "rtpjitterbuffer latency=100 ! "
    "identity name=rtp_tap ! "
    "rtph264depay ! "
    "h264parse ! "
    "avdec_h264 ! "
    "videoconvert ! "
    "autovideosink sync=true"
)

tap = pipeline.get_by_name("rtp_tap")
pad = tap.get_static_pad("sink")
pad.add_probe(Gst.PadProbeType.BUFFER, rtp_probe, None)

loop = GLib.MainLoop()
bus = pipeline.get_bus()
bus.add_signal_watch()


def on_message(bus, message, loop):
    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print("ERROR:", err)
        print("DEBUG:", debug)
        loop.quit()
    elif message.type == Gst.MessageType.EOS:
        loop.quit()


bus.connect("message", on_message, loop)

pipeline.set_state(Gst.State.PLAYING)

try:
    loop.run()
except KeyboardInterrupt:
    pass
finally:
    pipeline.set_state(Gst.State.NULL)
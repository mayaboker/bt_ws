#!/usr/bin/env python3

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtp", "1.0")

from gi.repository import Gst, GstRtp, GLib

Gst.init(None)

EXT_ID = 1
NTP64_URI = "urn:ietf:params:rtp-hdrext:ntp-64"


def add_ntp64_extension(payloader):
    ext = GstRtp.RTPHeaderExtension.create_from_uri(NTP64_URI)

    if ext is None:
        raise RuntimeError(
            "Could not create rtphdrextntp64. "
            "Check that GStreamer good plugins / rtpmanager are installed."
        )

    ext.set_id(EXT_ID)

    # Optional. By default, rtphdrextntp64 is added only to the first packet
    # with a given RTP timestamp. This makes it appear on every RTP packet.
    if ext.find_property("every-packet") is not None:
        ext.set_property("every-packet", True)

    payloader.emit("add-extension", ext)

    print(f"Added RTP header extension id={EXT_ID}, uri={NTP64_URI}")


def rtp_debug_probe(pad, info, user_data):
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

    print(f"send RTP: seq={seq}, ts={ts}, marker={marker}, has_ext={has_ext}")

    rtp.unmap()
    return Gst.PadProbeReturn.OK


pipeline = Gst.parse_launch(
    "videotestsrc is-live=true pattern=ball ! "
    "video/x-raw,width=640,height=480,framerate=1/1 ! "
    "x264enc tune=zerolatency speed-preset=ultrafast key-int-max=30 ! "
    "rtph264pay name=pay pt=96 config-interval=1 ! "
    "identity name=rtp_tap ! "
    "udpsink host=127.0.0.1 port=5000 sync=false async=false"
)

payloader = pipeline.get_by_name("pay")
add_ntp64_extension(payloader)

tap = pipeline.get_by_name("rtp_tap")
tap_pad = tap.get_static_pad("sink")
tap_pad.add_probe(Gst.PadProbeType.BUFFER, rtp_debug_probe, None)

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
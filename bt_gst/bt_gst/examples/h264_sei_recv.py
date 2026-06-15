#!/usr/bin/env python3

import json

import gi

gi.require_version("Gst", "1.0")

from gi.repository import GLib, Gst

from h264_sei import extract_user_data_unregistered

Gst.init(None)


def buffer_to_bytes(buffer):
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        return None

    try:
        return bytes(map_info.data)
    finally:
        buffer.unmap(map_info)


def sei_probe(pad, info, user_data):
    buffer = info.get_buffer()
    if buffer is None:
        return Gst.PadProbeReturn.OK

    access_unit = buffer_to_bytes(buffer)
    if access_unit is None:
        return Gst.PadProbeReturn.OK

    payloads = extract_user_data_unregistered(access_unit)
    if not payloads:
        print(f"recv H264: pts={buffer.pts}, no bt sei")
        return Gst.PadProbeReturn.OK

    for payload in payloads:
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = payload.hex()

        print(f"recv H264 SEI: pts={buffer.pts}, payload={decoded}")

    return Gst.PadProbeReturn.OK


pipeline = Gst.parse_launch(
    'udpsrc port=5000 '
    'caps="application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000" ! '
    "rtpjitterbuffer latency=100 ! "
    "rtph264depay ! "
    "h264parse config-interval=-1 ! "
    "video/x-h264,stream-format=byte-stream,alignment=au ! "
    "identity name=sei_tap ! "
    "avdec_h264 ! "
    "videoconvert ! "
    "autovideosink sync=true"
)

tap = pipeline.get_by_name("sei_tap")
pad = tap.get_static_pad("sink")
pad.add_probe(Gst.PadProbeType.BUFFER, sei_probe, None)

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

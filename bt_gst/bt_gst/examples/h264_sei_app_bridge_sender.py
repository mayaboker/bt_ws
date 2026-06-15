#!/usr/bin/env python3

import json
import time

import gi

gi.require_version("Gst", "1.0")

from gi.repository import GLib, Gst

from h264_sei import insert_sei_before_first_vcl

Gst.init(None)


def buffer_to_bytes(buffer):
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        return None

    try:
        return bytes(map_info.data)
    finally:
        buffer.unmap(map_info)


def clone_timing_and_flags(source, target):
    target.pts = source.pts
    target.dts = source.dts
    target.duration = source.duration
    target.offset = source.offset
    target.offset_end = source.offset_end
    target.set_flags(source.get_flags())


def build_sei_payload(buffer):
    return json.dumps(
        {
            "unix_time": time.time(),
            "pts": int(buffer.pts),
            "message": "bt-gst h264 sei",
        },
        separators=(",", ":"),
    ).encode("utf-8")


def on_encoded_sample(appsink, appsrc):
    sample = appsink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.EOS

    buffer = sample.get_buffer()
    if buffer is None:
        return Gst.FlowReturn.OK

    access_unit = buffer_to_bytes(buffer)
    if access_unit is None:
        return Gst.FlowReturn.OK

    payload = build_sei_payload(buffer)
    output_data = insert_sei_before_first_vcl(access_unit, payload)
    output_buffer = Gst.Buffer.new_wrapped(output_data)
    clone_timing_and_flags(buffer, output_buffer)

    print(f"send H264 SEI app-bridge: pts={buffer.pts}, bytes={len(payload)}")
    return appsrc.emit("push-buffer", output_buffer)


source_pipeline = Gst.parse_launch(
    "videotestsrc is-live=true pattern=ball ! "
    "video/x-raw,width=640,height=480,framerate=1/1 ! "
    "x264enc tune=zerolatency speed-preset=ultrafast key-int-max=30 "
    "byte-stream=true aud=true ! "
    "h264parse config-interval=-1 ! "
    "video/x-h264,stream-format=byte-stream,alignment=au ! "
    "appsink name=encoded_sink emit-signals=true sync=false max-buffers=1 drop=true"
)

rtp_pipeline = Gst.parse_launch(
    "appsrc name=encoded_src is-live=true format=time do-timestamp=false "
    'caps="video/x-h264,stream-format=byte-stream,alignment=au" ! '
    "rtph264pay pt=96 config-interval=1 ! "
    "udpsink host=127.0.0.1 port=5000 sync=false async=false"
)

appsink = source_pipeline.get_by_name("encoded_sink")
appsrc = rtp_pipeline.get_by_name("encoded_src")
appsink.connect("new-sample", on_encoded_sample, appsrc)

loop = GLib.MainLoop()


def on_message(bus, message, loop):
    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print("ERROR:", err)
        print("DEBUG:", debug)
        loop.quit()
    elif message.type == Gst.MessageType.EOS:
        loop.quit()


for pipeline in (source_pipeline, rtp_pipeline):
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_message, loop)

rtp_pipeline.set_state(Gst.State.PLAYING)
source_pipeline.set_state(Gst.State.PLAYING)

try:
    loop.run()
except KeyboardInterrupt:
    pass
finally:
    source_pipeline.set_state(Gst.State.NULL)
    rtp_pipeline.set_state(Gst.State.NULL)

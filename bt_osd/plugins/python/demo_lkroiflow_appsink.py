#!/usr/bin/env python3

import json
import os
import signal
import sys

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

Gst.init(None)

sys.path.insert(0, os.path.dirname(__file__))
import lkroiflowmeta  # noqa: F401 - registers the `lkroiflowmeta` element


PIPELINE = """
videotestsrc is-live=true pattern=ball !
video/x-raw,width=640,height=480,framerate=30/1 !
videoconvert ! video/x-raw,format=BGR !
lkroiflowmeta name=flow x1=150 y1=120 x2=350 y2=300 max-points=80
flow. ! queue ! videoconvert ! autovideosink
flow.meta ! queue ! appsink name=metadata emit-signals=true sync=false drop=true max-buffers=1
"""


def main():
    pipeline = Gst.parse_launch(" ".join(PIPELINE.split()))
    metadata_sink = pipeline.get_by_name("metadata")
    if metadata_sink is None:
        print("metadata appsink not found", file=sys.stderr)
        return 1

    metadata_sink.connect("new-sample", on_metadata_sample)

    bus = pipeline.get_bus()
    bus.add_signal_watch()

    loop = GLib.MainLoop()

    def on_message(_bus, message):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            print(f"error: {error}; debug={debug}", file=sys.stderr)
            loop.quit()
        elif message.type == Gst.MessageType.EOS:
            loop.quit()

    bus.connect("message", on_message)

    def handle_sigint(_signum, _frame):
        loop.quit()

    signal.signal(signal.SIGINT, handle_sigint)

    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        bus.remove_signal_watch()

    return 0


def on_metadata_sample(appsink):
    sample = appsink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.OK

    buffer = sample.get_buffer()
    ok, map_info = buffer.map(Gst.MapFlags.READ)
    if not ok:
        return Gst.FlowReturn.ERROR

    try:
        metadata = json.loads(bytes(map_info.data).decode("utf-8"))
        print(
            "roi "
            f"x1={metadata['x1']} "
            f"y1={metadata['y1']} "
            f"x2={metadata['x2']} "
            f"y2={metadata['y2']} "
            f"dx={metadata['dx']:.2f} "
            f"dy={metadata['dy']:.2f} "
            f"points={metadata['points']} "
            f"pts={metadata['pts']}",
            flush=True,
        )
    finally:
        buffer.unmap(map_info)

    return Gst.FlowReturn.OK


if __name__ == "__main__":
    raise SystemExit(main())

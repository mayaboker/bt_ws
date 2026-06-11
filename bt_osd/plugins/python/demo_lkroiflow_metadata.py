#!/usr/bin/env python3
# export GST_PLUGIN_PATH=$PWD/plugins:$GST_PLUGIN_PATH
import os
import signal
import sys

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

Gst.init(None)

sys.path.insert(0, os.path.dirname(__file__))
import lkroiflow  # noqa: F401 - registers the `lkroiflow` element


PIPELINE = """
videotestsrc is-live=true pattern=ball !
video/x-raw,width=640,height=480,framerate=30/1 !
videoconvert ! video/x-raw,format=BGR !
lkroiflow x1=150 y1=120 x2=350 y2=300 max-points=80 !
videoconvert ! autovideosink
"""


def main():
    pipeline = Gst.parse_launch(" ".join(PIPELINE.split()))
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    loop = GLib.MainLoop()

    def on_message(_bus, message):
        if message.type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if structure and structure.get_name() == "lkroiflow-roi":
                pts = structure.get_value("pts")
                if hasattr(pts, "unpack"):
                    pts = pts.unpack()
                print(
                    "roi "
                    f"x1={structure.get_value('x1')} "
                    f"y1={structure.get_value('y1')} "
                    f"x2={structure.get_value('x2')} "
                    f"y2={structure.get_value('y2')} "
                    f"dx={structure.get_value('dx'):.2f} "
                    f"dy={structure.get_value('dy'):.2f} "
                    f"points={structure.get_value('points')} "
                    f"pts={pts}",
                    flush=True,
                )
        elif message.type == Gst.MessageType.ERROR:
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


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

import sys
import os
import signal

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GObject, GLib

Gst.init(None)

# Ensure plugin module directory is on sys.path so importing registers the element
sys.path.insert(0, os.path.dirname(__file__))
import gstpoint  # registers `pointoverlay`


def main():
    pipeline = Gst.parse_launch(
        "videotestsrc ! video/x-raw,format=BGR,width=640,height=480 ! pointoverlay name=po ! videoconvert ! autovideosink"
    )

    po = pipeline.get_by_name("po")
    if po is None:
        print("pointoverlay element not found; ensure gstpoint.py is importable")
        return 1

    Gst.Element.set_state(pipeline, Gst.State.PLAYING)

    loop = GLib.MainLoop()

    # animate x from 0.0 to 1.0, step every second
    x = 0.0
    dx = 0.1

    def update():
        nonlocal x
        po.set_property("x", float(x))
        # keep y fixed at middle for demo
        po.set_property("y", 0.5)
        x += dx
        if x > 1.0:
            x = 0.0
        return True

    GLib.timeout_add_seconds(1, update)

    def handle_sigint(signum, frame):
        loop.quit()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        loop.run()
    finally:
        Gst.Element.set_state(pipeline, Gst.State.NULL)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")

from gi.repository import GLib, Gst


def configure_plugin_path() -> None:
    plugin_path = str(Path(__file__).resolve().parents[2] / "plugins")
    existing_path = os.environ.get("GST_PLUGIN_PATH")
    if not existing_path:
        os.environ["GST_PLUGIN_PATH"] = plugin_path
        return

    paths = existing_path.split(os.pathsep)
    if plugin_path not in paths:
        os.environ["GST_PLUGIN_PATH"] = os.pathsep.join([plugin_path, *paths])


def register_h264_sei_element() -> None:
    plugin_path = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "python"
        / "gstbt_h264_sei.py"
    )
    spec = importlib.util.spec_from_file_location("gstbt_h264_sei", plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {plugin_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


configure_plugin_path()
Gst.init(None)
register_h264_sei_element()

pipeline = Gst.parse_launch(
    "videotestsrc is-live=true pattern=ball ! "
    "video/x-raw,width=640,height=480,framerate=1/1 ! "
    "x264enc tune=zerolatency speed-preset=ultrafast key-int-max=30 "
    "byte-stream=true aud=true ! "
    "h264parse config-interval=-1 ! "
    "video/x-h264,stream-format=byte-stream,alignment=au ! "
    "bt_h264_sei ! "
    "rtph264pay pt=96 config-interval=1 ! "
    "udpsink host=127.0.0.1 port=5000 sync=false async=false"
)

loop = GLib.MainLoop()


def on_message(bus, message, loop):
    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print("ERROR:", err)
        print("DEBUG:", debug)
        loop.quit()
    elif message.type == Gst.MessageType.EOS:
        loop.quit()


bus = pipeline.get_bus()
bus.add_signal_watch()
bus.connect("message", on_message, loop)

pipeline.set_state(Gst.State.PLAYING)

try:
    loop.run()
except KeyboardInterrupt:
    pass
finally:
    pipeline.set_state(Gst.State.NULL)

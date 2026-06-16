#!/usr/bin/env python3

import argparse
import signal
import sys
from typing import Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gst, GLib


Gst.init(None)


def make_element(factory: str, name: str) -> Gst.Element:
    elem = Gst.ElementFactory.make(factory, name)
    if elem is None:
        raise RuntimeError(
            f"Could not create element '{factory}'. "
            f"Check: gst-inspect-1.0 {factory}"
        )
    return elem


def link_or_raise(src: Gst.Element, dst: Gst.Element) -> None:
    if not src.link(dst):
        raise RuntimeError(f"Could not link {src.get_name()} -> {dst.get_name()}")


class TsVideoKlvReceiver:
    def __init__(self, port: int, show_video: bool = True) -> None:
        self.port = port
        self.show_video = show_video
        self.loop: Optional[GLib.MainLoop] = None
        self.klv_count = 0
        self.video_linked = False
        self.metadata_linked = False

        self.pipeline = Gst.Pipeline.new("ts-video-klv-receiver")

        # Source + demux
        self.udpsrc = make_element("udpsrc", "udpsrc")
        self.demux = make_element("tsdemux", "demux")

        self.udpsrc.set_property("port", port)
        self.udpsrc.set_property(
            "caps",
            Gst.Caps.from_string("video/mpegts, systemstream=true, packetsize=188"),
        )
        self.demux.set_property("latency", 0)

        self.pipeline.add(self.udpsrc)
        self.pipeline.add(self.demux)
        link_or_raise(self.udpsrc, self.demux)

        self.demux.connect("pad-added", self.on_demux_pad_added)

        # Video branch:
        # demux dynamic pad -> queue -> h264parse -> avdec_h264 -> videoconvert -> sink
        self.video_queue = make_element("queue", "video_queue")
        self.h264parse = make_element("h264parse", "h264parse")
        self.decoder = make_element("avdec_h264", "decoder")
        self.videoconvert = make_element("videoconvert", "videoconvert")
        self.video_sink = make_element(
            "autovideosink" if show_video else "fakesink",
            "video_sink",
        )

        self.video_queue.set_property("leaky", 2)  # downstream
        self.video_queue.set_property("max-size-buffers", 3)
        self.video_queue.set_property("max-size-time", 0)
        self.video_queue.set_property("max-size-bytes", 0)

        self.decoder.set_property("max-threads", 1)
        self.video_sink.set_property("sync", False)

        for elem in [
            self.video_queue,
            self.h264parse,
            self.decoder,
            self.videoconvert,
            self.video_sink,
        ]:
            self.pipeline.add(elem)

        link_or_raise(self.video_queue, self.h264parse)
        link_or_raise(self.h264parse, self.decoder)
        link_or_raise(self.decoder, self.videoconvert)
        link_or_raise(self.videoconvert, self.video_sink)

        # Metadata/KLV branch:
        # demux dynamic non-video pad -> queue -> appsink
        self.meta_queue = make_element("queue", "meta_queue")
        self.meta_sink = make_element("appsink", "meta_sink")

        self.meta_queue.set_property("leaky", 2)  # downstream
        self.meta_queue.set_property("max-size-buffers", 100)
        self.meta_queue.set_property("max-size-time", 0)
        self.meta_queue.set_property("max-size-bytes", 0)

        self.meta_sink.set_property("emit-signals", True)
        self.meta_sink.set_property("sync", False)
        self.meta_sink.set_property("drop", True)
        self.meta_sink.set_property("max-buffers", 100)
        self.meta_sink.connect("new-sample", self.on_metadata_sample)

        self.pipeline.add(self.meta_queue)
        self.pipeline.add(self.meta_sink)
        link_or_raise(self.meta_queue, self.meta_sink)

        # Bus
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

    def on_demux_pad_added(self, demux: Gst.Element, pad: Gst.Pad) -> None:
        caps = pad.get_current_caps()
        if caps is None:
            caps = pad.query_caps(None)

        caps_str = caps.to_string()
        pad_name = pad.get_name()

        print(f"[INFO] demux pad-added: name={pad_name}, caps={caps_str}")

        if caps_str.startswith("video/x-h264"):
            if self.video_linked:
                print("[INFO] Video already linked; ignoring extra video pad")
                return

            sink_pad = self.video_queue.get_static_pad("sink")
            result = pad.link(sink_pad)
            print(f"[INFO] video link result: {result.value_nick}")

            if result == Gst.PadLinkReturn.OK:
                self.video_linked = True
            return

        # Your working gst-launch uses an unrestricted second branch:
        # demux. ! queue ! identity ! fakesink
        #
        # So here we treat the first non-video pad as metadata/KLV.
        if not self.metadata_linked:
            sink_pad = self.meta_queue.get_static_pad("sink")
            result = pad.link(sink_pad)
            print(f"[INFO] metadata/KLV link result: {result.value_nick}")

            if result == Gst.PadLinkReturn.OK:
                self.metadata_linked = True
            return

        print(f"[INFO] Extra non-video pad ignored: name={pad_name}, caps={caps_str}")

    def on_metadata_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.ERROR

        buf = sample.get_buffer()
        if buf is None:
            return Gst.FlowReturn.ERROR

        ok, map_info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR

        try:
            data = bytes(map_info.data)
        finally:
            buf.unmap(map_info)

        self.klv_count += 1

        pts_ms = None
        if buf.pts != Gst.CLOCK_TIME_NONE:
            pts_ms = buf.pts / Gst.MSECOND

        duration_ms = None
        if buf.duration != Gst.CLOCK_TIME_NONE:
            duration_ms = buf.duration / Gst.MSECOND

        print(
            f"KLV #{self.klv_count}: "
            f"size={len(data)} bytes, "
            f"pts_ms={pts_ms}, "
            f"duration_ms={duration_ms}, "
            f"hex={data.hex(' ')}",
            flush=True,
        )

        return Gst.FlowReturn.OK

    def on_bus_message(self, bus: Gst.Bus, message: Gst.Message) -> None:
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"[ERROR] {err}", file=sys.stderr)
            if debug:
                print(f"[DEBUG] {debug}", file=sys.stderr)
            self.stop()

        elif msg_type == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            print(f"[WARNING] {err}", file=sys.stderr)
            if debug:
                print(f"[DEBUG] {debug}", file=sys.stderr)

        elif msg_type == Gst.MessageType.EOS:
            print("[INFO] EOS")
            self.stop()

    def run(self) -> None:
        self.loop = GLib.MainLoop()

        print(f"[INFO] Listening on UDP port {self.port}")

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        print(f"[INFO] set_state PLAYING: {ret.value_nick}")

        def handle_signal(sig, frame):
            print("\n[INFO] stopping...")
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)

    def stop(self) -> None:
        self.pipeline.set_state(Gst.State.NULL)
        if self.loop and self.loop.is_running():
            self.loop.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()

    receiver = TsVideoKlvReceiver(
        port=args.port,
        show_video=not args.no_video,
    )
    receiver.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""Receive H.264 video plus private JSON metadata from MPEG-TS over UDP."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from typing import Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gst


Gst.init(None)


def get_element_or_raise(pipeline: Gst.Element, name: str) -> Gst.Element:
    elem = pipeline.get_by_name(name)
    if elem is None:
        raise RuntimeError(f"Could not find element named {name!r}")
    return elem


class TsVideoJsonReceiver:
    def __init__(self, port: int, show_video: bool = True) -> None:
        self.port = port
        self.show_video = show_video
        self.loop: Optional[GLib.MainLoop] = None
        self.json_count = 0
        self.video_linked = False
        self.metadata_linked = False
        self.latest_video_pts_ms: float | None = None

        video_sink = "autovideosink" if show_video else "fakesink"
        pipeline_desc = f"""
    udpsrc name=udpsrc port={port}
        caps="video/mpegts,systemstream=true,packetsize=188"
        ! tsdemux name=demux latency=0

    queue name=video_queue leaky=downstream max-size-buffers=3 max-size-time=0 max-size-bytes=0
        ! h264parse name=h264parse
        ! avdec_h264 name=decoder max-threads=1
        ! videoconvert name=videoconvert
        ! textoverlay name=receiver_overlay
                       text="RX JSON waiting"
                       valignment=bottom
                       halignment=right
                       font-desc="Sans, 20"
                       shaded-background=true
        ! {video_sink} name=video_sink sync=false

    queue name=meta_queue leaky=downstream max-size-buffers=100 max-size-time=0 max-size-bytes=0
        ! appsink name=meta_sink emit-signals=true sync=false drop=true max-buffers=100
"""

        self.pipeline = Gst.parse_launch(pipeline_desc)

        self.demux = get_element_or_raise(self.pipeline, "demux")
        self.video_queue = get_element_or_raise(self.pipeline, "video_queue")
        self.videoconvert = get_element_or_raise(self.pipeline, "videoconvert")
        self.receiver_overlay = get_element_or_raise(self.pipeline, "receiver_overlay")
        self.meta_queue = get_element_or_raise(self.pipeline, "meta_queue")
        self.meta_sink = get_element_or_raise(self.pipeline, "meta_sink")

        self.demux.connect("pad-added", self.on_demux_pad_added)
        self.meta_sink.connect("new-sample", self.on_metadata_sample)

        video_probe_pad = self.videoconvert.get_static_pad("src")
        if video_probe_pad is None:
            raise RuntimeError("Could not get videoconvert src pad")
        video_probe_pad.add_probe(Gst.PadProbeType.BUFFER, self.on_video_buffer)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

    def on_video_buffer(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        buf = info.get_buffer()
        if buf is not None and buf.pts != Gst.CLOCK_TIME_NONE:
            self.latest_video_pts_ms = buf.pts / Gst.MSECOND
        return Gst.PadProbeReturn.OK

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

        if not self.metadata_linked:
            sink_pad = self.meta_queue.get_static_pad("sink")
            result = pad.link(sink_pad)
            print(f"[INFO] metadata/JSON link result: {result.value_nick}")

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

        self.json_count += 1

        pts_ms = None
        if buf.pts != Gst.CLOCK_TIME_NONE:
            pts_ms = buf.pts / Gst.MSECOND

        duration_ms = None
        if buf.duration != Gst.CLOCK_TIME_NONE:
            duration_ms = buf.duration / Gst.MSECOND

        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(
                f"JSON #{self.json_count}: "
                f"invalid payload size={len(data)} bytes, "
                f"pts_ms={pts_ms}, "
                f"duration_ms={duration_ms}, "
                f"error={exc}, "
                f"hex={data.hex(' ')}",
                flush=True,
            )
            return Gst.FlowReturn.OK

        counter = payload.get("counter")
        created_unix_ns = payload.get("created_unix_ns")
        sender_pts_ms = payload.get("sender_pts_ms")

        receiver_time_ns = time.time_ns()
        wall_latency_ms = None
        if isinstance(created_unix_ns, int):
            wall_latency_ms = (receiver_time_ns - created_unix_ns) / 1_000_000.0

        metadata_pts_delta_ms = None
        if pts_ms is not None and isinstance(sender_pts_ms, (int, float)):
            metadata_pts_delta_ms = pts_ms - float(sender_pts_ms)

        video_meta_delta_ms = None
        if self.latest_video_pts_ms is not None and pts_ms is not None:
            video_meta_delta_ms = self.latest_video_pts_ms - pts_ms

        overlay_lines = [f"RX JSON #{counter}"]
        if wall_latency_ms is not None:
            overlay_lines.append(f"wall {wall_latency_ms:.2f} ms")
        if video_meta_delta_ms is not None:
            overlay_lines.append(f"video-meta {video_meta_delta_ms:.2f} ms")
        self.receiver_overlay.set_property("text", "\n".join(overlay_lines))

        print(
            f"JSON #{self.json_count}: "
            f"counter={counter}, "
            f"size={len(data)} bytes, "
            f"metadata_pts_ms={pts_ms}, "
            f"sender_pts_ms={sender_pts_ms}, "
            f"wall_latency_ms={wall_latency_ms}, "
            f"latest_video_pts_ms={self.latest_video_pts_ms}, "
            f"video_meta_delta_ms={video_meta_delta_ms}, "
            f"metadata_pts_delta_ms={metadata_pts_delta_ms}, "
            f"duration_ms={duration_ms}, "
            f"payload={payload}",
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

    receiver = TsVideoJsonReceiver(
        port=args.port,
        show_video=not args.no_video,
    )
    receiver.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

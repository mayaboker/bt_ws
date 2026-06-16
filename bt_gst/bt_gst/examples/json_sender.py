#!/usr/bin/env python3
"""Send H.264 video plus private JSON metadata in MPEG-TS over UDP.

The metadata branch uses `meta/x-klv` caps because `mpegtsmux` supports that
stream type. The payload bytes are UTF-8 JSON for this private sender/receiver
pair, not standards-compliant KLV.
"""

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


def make_json_payload(counter: int, pts_ms: float) -> bytes:
    payload = {
        "counter": counter,
        "unix_time": time.time(),
        "pts_ms": pts_ms,
        "message": "hello from json metadata stream",
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class H264JsonUdpSender:
    def __init__(
        self,
        host: str,
        port: int,
        width: int,
        height: int,
        fps: int,
        bitrate_kbps: int,
        json_rate_hz: int,
    ) -> None:
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.json_rate_hz = json_rate_hz

        self.counter = 0
        self.loop: Optional[GLib.MainLoop] = None

        pipeline_desc = f"""
    mpegtsmux name=mux alignment=7
        ! queue
        ! udpsink host={host} port={port} sync=false async=false

    videotestsrc is-live=true pattern=ball
        ! video/x-raw,width={width},height={height},framerate={fps}/1
        ! videoconvert
        ! x264enc tune=zerolatency
                  speed-preset=ultrafast
                  bitrate={bitrate_kbps}
                  key-int-max={fps}
                  bframes=0
                  byte-stream=true
        ! h264parse config-interval=1
        ! queue max-size-buffers=0 max-size-time=0 max-size-bytes=0
        ! mux.

    appsrc name=jsonsrc
           is-live=true
           format=time
           do-timestamp=false
           block=false
           caps=meta/x-klv,parsed=true
        ! queue leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0
        ! mux.
"""

        self.pipeline = Gst.parse_launch(pipeline_desc)

        self.jsonsrc = self.pipeline.get_by_name("jsonsrc")
        if self.jsonsrc is None:
            raise RuntimeError("Could not find appsrc named jsonsrc")

        self.jsonsrc.set_property("is-live", True)
        self.jsonsrc.set_property("format", Gst.Format.TIME)
        self.jsonsrc.set_property("do-timestamp", False)
        self.jsonsrc.set_property("block", False)
        self.jsonsrc.set_property("max-bytes", 4096)
        self.jsonsrc.set_property(
            "caps",
            Gst.Caps.from_string("meta/x-klv,parsed=true"),
        )

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

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

        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old, new, _pending = message.parse_state_changed()
                print(f"[INFO] Pipeline state: {old.value_nick} -> {new.value_nick}")

    def start_json_timer(self) -> bool:
        interval_ms = max(1, int(1000 / self.json_rate_hz))

        print(f"[INFO] Starting JSON timer: {self.json_rate_hz} Hz, interval={interval_ms} ms")
        GLib.timeout_add(interval_ms, self.push_json)
        return False

    def push_json(self) -> bool:
        clock = self.pipeline.get_clock()
        if clock is None:
            return True

        base_time = self.pipeline.get_base_time()
        now = clock.get_time()
        running_time = now - base_time
        pts_ms = running_time / Gst.MSECOND

        payload = make_json_payload(self.counter, pts_ms)

        buf = Gst.Buffer.new_allocate(None, len(payload), None)
        buf.fill(0, payload)

        duration = Gst.SECOND // self.json_rate_hz
        buf.pts = running_time
        buf.dts = running_time
        buf.duration = duration

        ret = self.jsonsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            print(f"[WARNING] push-buffer returned {ret}", file=sys.stderr)

        if self.counter % self.json_rate_hz == 0:
            print(
                f"[INFO] pushed JSON #{self.counter}, "
                f"pts_ms={pts_ms:.2f}, "
                f"size={len(payload)} bytes"
            )

        self.counter += 1
        return True

    def run(self) -> None:
        self.loop = GLib.MainLoop()

        print(
            f"[INFO] Sending H.264 + JSON metadata in MPEG-TS to udp://{self.host}:{self.port}"
        )
        print(
            f"[INFO] Video={self.width}x{self.height}@{self.fps}, "
            f"bitrate={self.bitrate_kbps} kbps, JSON={self.json_rate_hz} Hz"
        )

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        print(f"[INFO] set_state PLAYING returned: {ret.value_nick}")

        GLib.timeout_add(100, self.start_json_timer)

        def handle_signal(sig, frame):
            print("\n[INFO] Stopping sender...")
            self.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)

    def stop(self) -> None:
        try:
            self.jsonsrc.emit("end-of-stream")
        except Exception:
            pass

        self.pipeline.set_state(Gst.State.NULL)

        if self.loop and self.loop.is_running():
            self.loop.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--bitrate-kbps", type=int, default=2500)
    parser.add_argument("--json-rate-hz", type=int, default=30)

    args = parser.parse_args()

    sender = H264JsonUdpSender(
        host=args.host,
        port=args.port,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bitrate_kbps=args.bitrate_kbps,
        json_rate_hz=args.json_rate_hz,
    )

    sender.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import cv2
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import GLib, Gst


Gst.init(None)


def make_json_payload(counter: int, created_unix_ns: int, sender_pts_ms: float) -> bytes:
    payload = {
        "counter": counter,
        "created_unix_ns": created_unix_ns,
        "sender_pts_ms": sender_pts_ms,
        "message": "hello from json metadata stream",
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def make_counter_frame(counter: int, pts_ms: float, width: int, height: int) -> bytes:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (24, 24, 24)

    grid_color = (55, 55, 55)
    for x in range(0, width, 80):
        cv2.line(frame, (x, 0), (x, height), grid_color, 1)
    for y in range(0, height, 80):
        cv2.line(frame, (0, y), (width, y), grid_color, 1)

    marker_size = max(40, min(width, height) // 10)
    usable_width = max(1, width - marker_size - 40)
    x = 20 + ((counter * 13) % usable_width)
    y = height // 2 - marker_size // 2
    cv2.rectangle(frame, (x, y), (x + marker_size, y + marker_size), (0, 180, 255), -1)
    cv2.rectangle(frame, (x, y), (x + marker_size, y + marker_size), (255, 255, 255), 3)

    cv2.putText(
        frame,
        f"TX JSON #{counter}",
        (40, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.0,
        (255, 255, 255),
        4,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"PTS {pts_ms:.2f} ms",
        (40, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (80, 220, 255),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"frame {counter}",
        (40, height - 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (180, 255, 120),
        3,
        cv2.LINE_AA,
    )
    return frame.tobytes()


class H264JsonUdpSender:
    def __init__(
        self,
        host: str,
        port: int,
        width: int,
        height: int,
        fps: int,
        bitrate_kbps: int,
    ) -> None:
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps

        self.counter = 0
        self.loop: Optional[GLib.MainLoop] = None

        pipeline_desc = f"""
    mpegtsmux name=mux alignment=7
        ! queue
        ! udpsink host={host} port={port} sync=false async=false

    appsrc name=videosrc
           is-live=true
           format=time
           do-timestamp=false
           block=false
           caps=video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1
        ! queue leaky=downstream max-size-buffers=3 max-size-time=0 max-size-bytes=0
        ! tee name=video_tee

    video_tee.
        ! queue leaky=downstream max-size-buffers=3 max-size-time=0 max-size-bytes=0
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

    video_tee.
        ! queue leaky=downstream max-size-buffers=3 max-size-time=0 max-size-bytes=0
        ! videoconvert
        ! autovideosink sync=false

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

        self.videosrc = self.pipeline.get_by_name("videosrc")
        if self.videosrc is None:
            raise RuntimeError("Could not find appsrc named videosrc")

        self.jsonsrc = self.pipeline.get_by_name("jsonsrc")
        if self.jsonsrc is None:
            raise RuntimeError("Could not find appsrc named jsonsrc")

        self.videosrc.set_property("is-live", True)
        self.videosrc.set_property("format", Gst.Format.TIME)
        self.videosrc.set_property("do-timestamp", False)
        self.videosrc.set_property("block", False)
        self.videosrc.set_property("max-bytes", width * height * 3 * 3)
        self.videosrc.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1"
            ),
        )

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

    def start_frame_timer(self) -> bool:
        interval_ms = max(1, int(1000 / self.fps))
        print(f"[INFO] Starting frame generator: {self.fps} FPS, interval={interval_ms} ms")
        GLib.timeout_add(interval_ms, self.push_frame_and_json)
        return False

    def push_frame_and_json(self) -> bool:
        frame_duration = Gst.SECOND // self.fps
        frame_pts = self.counter * frame_duration
        pts_ms = frame_pts / Gst.MSECOND

        frame = make_counter_frame(
            self.counter,
            pts_ms,
            width=self.width,
            height=self.height,
        )
        video_buf = Gst.Buffer.new_allocate(None, len(frame), None)
        video_buf.fill(0, frame)
        video_buf.pts = frame_pts
        video_buf.dts = frame_pts
        video_buf.duration = frame_duration

        video_ret = self.videosrc.emit("push-buffer", video_buf)
        if video_ret != Gst.FlowReturn.OK:
            print(f"[WARNING] video push-buffer returned {video_ret}", file=sys.stderr)
            return False

        created_unix_ns = time.time_ns()
        payload = make_json_payload(self.counter, created_unix_ns, pts_ms)

        json_buf = Gst.Buffer.new_allocate(None, len(payload), None)
        json_buf.fill(0, payload)
        json_buf.pts = frame_pts
        json_buf.dts = frame_pts
        json_buf.duration = frame_duration

        json_ret = self.jsonsrc.emit("push-buffer", json_buf)
        if json_ret != Gst.FlowReturn.OK:
            print(f"[WARNING] JSON push-buffer returned {json_ret}", file=sys.stderr)
            return False

        if self.counter % max(1, self.fps) == 0:
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
            f"bitrate={self.bitrate_kbps} kbps, JSON=per video frame"
        )

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        print(f"[INFO] set_state PLAYING returned: {ret.value_nick}")

        GLib.timeout_add(100, self.start_frame_timer)

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
            self.videosrc.emit("end-of-stream")
        except Exception:
            pass
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

    args = parser.parse_args()

    sender = H264JsonUdpSender(
        host=args.host,
        port=args.port,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bitrate_kbps=args.bitrate_kbps,
    )

    sender.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

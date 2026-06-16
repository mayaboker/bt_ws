#!/usr/bin/env python3

"""

gst-launch-1.0 -v \
  udpsrc port=5000 caps="video/mpegts, systemstream=true, packetsize=188" ! \
  tsdemux latency=0 name=demux \
  demux. ! queue ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false \
  demux. ! queue ! "meta/x-klv" ! identity silent=false dump=true ! fakesink sync=false

  
  gst-launch-1.0 -v \
  udpsrc port=5000 caps="video/mpegts, systemstream=true, packetsize=188" ! \
  tsdemux latency=0 name=demux \
  demux. ! queue ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false \
  demux. ! queue ! "meta/x-klv" ! identity silent=false dump=true ! fakesink sync=false

  gst-launch-1.0 -v \
  udpsrc port=5000 caps="video/mpegts, systemstream=true, packetsize=188" ! \
  tsdemux latency=0 name=demux \
  demux. ! queue ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false \
  demux. ! queue ! identity silent=false dump=true ! fakesink sync=false

gst-launch-1.0 -v \
  udpsrc port=5000 caps="video/mpegts, systemstream=true, packetsize=188" ! \
  tsdemux latency=0 name=demux \
  demux. ! queue ! h264parse ! avdec_h264 ! videoconvert ! autovideosink sync=false \
  demux. ! queue ! "meta/x-klv" ! filesink location=received.klv
"""
#!/usr/bin/env python3

import argparse
import signal
import struct
import sys
from typing import Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib


Gst.init(None)


def make_dummy_klv(counter: int) -> bytes:
    """
    Dummy KLV-like packet for testing transport.

    This is NOT full MISB ST 0601.
    It is only for proving:
      Python -> appsrc -> meta/x-klv -> mpegtsmux -> UDP
    """

    # 16-byte KLV Universal Key-like prefix.
    key = bytes.fromhex("060E2B34020B01010E01030101000000")

    # Example value: counter + dummy timestamp.
    value = struct.pack(">QQ", counter, counter * 33333333)

    # BER short-form length because value length is less than 128.
    length = bytes([len(value)])

    return key + length + value


class H264KlvUdpSender:
    def __init__(
        self,
        host: str,
        port: int,
        width: int,
        height: int,
        fps: int,
        bitrate_kbps: int,
        klv_rate_hz: int,
    ) -> None:
        self.host = host
        self.port = port
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate_kbps = bitrate_kbps
        self.klv_rate_hz = klv_rate_hz

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

    appsrc name=klvsrc
           is-live=true
           format=time
           do-timestamp=true
           block=false
           caps=meta/x-klv,parsed=true
        ! queue leaky=downstream max-size-buffers=2 max-size-time=0 max-size-bytes=0
        ! mux.
"""

        self.pipeline = Gst.parse_launch(pipeline_desc)

        self.klvsrc = self.pipeline.get_by_name("klvsrc")
        if self.klvsrc is None:
            raise RuntimeError("Could not find appsrc named klvsrc")

        self.klvsrc.set_property("is-live", True)
        self.klvsrc.set_property("format", Gst.Format.TIME)
        self.klvsrc.set_property("do-timestamp", False)
        self.klvsrc.set_property("block", False)
        self.klvsrc.set_property("max-bytes", 4096)
        self.klvsrc.set_property(
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
                old, new, pending = message.parse_state_changed()
                print(f"[INFO] Pipeline state: {old.value_nick} -> {new.value_nick}")

    def start_klv_timer(self) -> bool:
        interval_ms = max(1, int(1000 / self.klv_rate_hz))

        print(f"[INFO] Starting KLV timer: {self.klv_rate_hz} Hz, interval={interval_ms} ms")

        GLib.timeout_add(interval_ms, self.push_klv)

        # Return False so this setup timer runs only once.
        return False

    def push_klv(self) -> bool:
        """
        Push one KLV packet.

        Important:
        - Uses pipeline running-time as PTS.
        - This avoids muxer stalls caused by bad timestamp domains.
        """

        klv = make_dummy_klv(self.counter)

        buf = Gst.Buffer.new_allocate(None, len(klv), None)
        buf.fill(0, klv)

        duration = Gst.SECOND // self.klv_rate_hz

        clock = self.pipeline.get_clock()
        if clock is None:
            return True

        base_time = self.pipeline.get_base_time()
        now = clock.get_time()
        running_time = now - base_time

        buf.pts = running_time
        buf.dts = running_time
        buf.duration = duration

        ret = self.klvsrc.emit("push-buffer", buf)

        if ret != Gst.FlowReturn.OK:
            print(f"[WARNING] push-buffer returned {ret}", file=sys.stderr)

        if self.counter % self.klv_rate_hz == 0:
            print(
                f"[INFO] pushed KLV #{self.counter}, "
                f"pts_ms={running_time / Gst.MSECOND:.2f}, "
                f"size={len(klv)} bytes"
            )

        self.counter += 1
        return True

    def run(self) -> None:
        self.loop = GLib.MainLoop()

        print(
            f"[INFO] Sending H.264 + KLV in MPEG-TS to udp://{self.host}:{self.port}"
        )
        print(
            f"[INFO] Video={self.width}x{self.height}@{self.fps}, "
            f"bitrate={self.bitrate_kbps} kbps, KLV={self.klv_rate_hz} Hz"
        )

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        print(f"[INFO] set_state PLAYING returned: {ret.value_nick}")

        # Start KLV after pipeline has clock/base-time.
        GLib.timeout_add(100, self.start_klv_timer)

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
            self.klvsrc.emit("end-of-stream")
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
    parser.add_argument("--klv-rate-hz", type=int, default=30)

    args = parser.parse_args()

    sender = H264KlvUdpSender(
        host=args.host,
        port=args.port,
        width=args.width,
        height=args.height,
        fps=args.fps,
        bitrate_kbps=args.bitrate_kbps,
        klv_rate_hz=args.klv_rate_hz,
    )

    sender.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
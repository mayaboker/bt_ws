#!/usr/bin/env python3

"""
gst-launch-1.0 v4l2src device=/dev/video0 ! video/x-raw,width=640,height=512,framerate=30/1 ! autovideosink
"""
import sys
import time
import threading

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib


Gst.init(None)


def get_element_or_raise(pipeline, name):
    elem = pipeline.get_by_name(name)
    if elem is None:
        raise RuntimeError(f"Could not find GStreamer element named {name!r}")
    return elem


class CameraRecorder:
    def __init__(self, device="/dev/video0", width=640, height=512, fps=30):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps

        self.loop = GLib.MainLoop()
        self.loop_thread = None

        pipeline_desc = f"""
            v4l2src name=camera
                ! video/x-raw,width={self.width},height={self.height},framerate={self.fps}/1
                ! tee name=tee

            tee.
                ! queue name=live-queue
                ! videoconvert name=live-convert
                ! autovideosink name=live-sink
        """

        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.pipeline.set_name("camera-pipeline")

        self.src = get_element_or_raise(self.pipeline, "camera")
        self.tee = get_element_or_raise(self.pipeline, "tee")
        self.live_queue = get_element_or_raise(self.pipeline, "live-queue")
        self.live_convert = get_element_or_raise(self.pipeline, "live-convert")
        self.live_sink = get_element_or_raise(self.pipeline, "live-sink")
        self.src.set_property("device", self.device)

        self.record_bin = None
        self.record_tee_pad = None
        self.record_block_probe_id = None
        self.record_eos_probe_id = None
        self.record_eos_sent = False
        self.recording = False
        self.stopping = False

        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_bus_message)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()

    def shutdown(self):
        if self.recording:
            self.stop_recording()

        self.pipeline.set_state(Gst.State.NULL)

        if self.loop.is_running():
            self.loop.quit()

        if self.loop_thread:
            self.loop_thread.join(timeout=2)

    def start_recording(self, filename):
        if self.recording:
            raise RuntimeError("Already recording")

        self.record_bin = self._create_record_bin(filename)
        self.pipeline.add(self.record_bin)

        self.record_tee_pad = self.tee.request_pad_simple("src_%u")
        record_sink_pad = self.record_bin.get_static_pad("sink")

        if self.record_tee_pad.link(record_sink_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("Failed to link tee to recording branch")

        # Start the recording branch only after it is linked to the tee, so it
        # receives stream-start/caps/segment events in the normal order.
        self.record_bin.sync_state_with_parent()

        self.recording = True
        self.stopping = False
        self.record_block_probe_id = None
        self.record_eos_probe_id = None
        self.record_eos_sent = False

        print(f"Recording started: {filename}")

    def stop_recording(self):
        if not self.recording or not self.record_bin:
            return

        print("Stopping recording...")

        self.stopping = True

        record_sink_pad = self.record_bin.get_static_pad("sink")
        if record_sink_pad is None:
            raise RuntimeError("Recording branch has no sink pad")

        if self.record_tee_pad is None:
            raise RuntimeError("Recording branch has no tee pad")

        record_sink = self.record_bin.get_by_name("record-sink")
        if record_sink is None:
            raise RuntimeError("Recording branch has no filesink")

        record_filesink_pad = record_sink.get_static_pad("sink")
        if record_filesink_pad is None:
            raise RuntimeError("Recording filesink has no sink pad")

        def eos_cb(pad, info):
            event = info.get_event()
            if event and event.type == Gst.EventType.EOS:
                self.record_eos_probe_id = None
                GLib.idle_add(self._finish_stop_recording)
                return Gst.PadProbeReturn.REMOVE
            return Gst.PadProbeReturn.OK

        self.record_eos_probe_id = record_filesink_pad.add_probe(
            Gst.PadProbeType.EVENT_DOWNSTREAM,
            eos_cb,
        )

        def block_cb(pad, info):
            if not self.record_eos_sent:
                self.record_eos_sent = True
                record_sink_pad.send_event(Gst.Event.new_eos())
            return Gst.PadProbeReturn.OK

        # Block new buffers at the tee output, then send EOS into the
        # recording branch so mp4mux can finalize the file.
        self.record_block_probe_id = self.record_tee_pad.add_probe(
            Gst.PadProbeType.BLOCK_DOWNSTREAM,
            block_cb,
        )

    def _finish_stop_recording(self):
        if not self.record_bin:
            return

        # Unlink tee from recording branch.
        record_sink_pad = self.record_bin.get_static_pad("sink")

        if self.record_tee_pad:
            if self.record_block_probe_id is not None:
                self.record_tee_pad.remove_probe(self.record_block_probe_id)
                self.record_block_probe_id = None
            self.record_tee_pad.unlink(record_sink_pad)
            self.tee.release_request_pad(self.record_tee_pad)
            self.record_tee_pad = None

        record_sink = self.record_bin.get_by_name("record-sink")
        if record_sink and self.record_eos_probe_id is not None:
            record_filesink_pad = record_sink.get_static_pad("sink")
            if record_filesink_pad:
                record_filesink_pad.remove_probe(self.record_eos_probe_id)
            self.record_eos_probe_id = None

        # Remove branch.
        self.record_bin.set_state(Gst.State.NULL)
        self.pipeline.remove(self.record_bin)

        self.record_bin = None
        self.recording = False
        self.stopping = False
        self.record_eos_sent = False

        print("Recording stopped and file finalized")
        return False

    def _create_record_bin(self, filename):
        """
        Recording branch:

            queue ! videoconvert ! x264enc ! h264parse ! mp4mux ! filesink

        The bin exposes one ghost sink pad, so it can be linked directly to tee.
        """
        record_desc = f"""
            queue name=record-queue
                ! videoconvert name=record-convert
                ! video/x-raw,format=I420
                ! x264enc name=record-encoder
                          tune=zerolatency
                          speed-preset=veryfast
                          key-int-max={self.fps}
                ! h264parse name=record-parser
                ! mp4mux name=record-muxer
                ! filesink name=record-sink sync=false
        """

        record_bin = Gst.parse_bin_from_description(record_desc, True)
        record_bin.set_name("record-bin")

        if record_bin.get_static_pad("sink") is None:
            raise RuntimeError("Recording bin did not expose a sink ghost pad")

        record_sink = record_bin.get_by_name("record-sink")
        if record_sink is None:
            raise RuntimeError("Recording bin did not create a filesink")
        record_sink.set_property("location", filename)

        return record_bin

    def _on_bus_message(self, bus, message):
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer ERROR: {err}", file=sys.stderr)
            if debug:
                print(f"Debug: {debug}", file=sys.stderr)
            self.loop.quit()

        elif msg_type == Gst.MessageType.EOS:
            # EOS is expected when stopping the recording branch.
            # Do not shut down the whole app if this EOS came from stopping.
            if self.stopping:
                self._finish_stop_recording()
            else:
                print("Pipeline EOS")
                self.loop.quit()


def main():
    rec = CameraRecorder(
        device="/dev/video0",
        width=640,
        height=512,
        fps=30,
    )

    rec.start()

    try:
        print("Camera running")
        time.sleep(2)

        rec.start_recording("first.mp4")
        time.sleep(5)
        rec.stop_recording()

        time.sleep(5)

        rec.start_recording("second.mp4")
        time.sleep(5)
        rec.stop_recording()

        time.sleep(2)

    finally:
        rec.shutdown()


if __name__ == "__main__":
    main()

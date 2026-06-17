#!/usr/bin/env python3

"""
gst-launch-1.0 filesrc location=first.mp4 ! decodebin ! videoconvert ! autovideosink

v4l2-ctl --list-formats-ext -d /dev/video0

gst-launch-1.0 v4l2src device=/dev/video0 ! video/x-raw,width=640,height=512,framerate=30/1 ! autovideosink

gst-launch-1.0 \
  filesrc location=second.i420 \
  ! rawvideoparse width=640 height=512 framerate=30/1 \
  ! videoconvert \
  ! autovideosink


Why it uses this structure:
- tee lets preview keep running while recording starts/stops.
- queue isolates the recording branch from the live preview branch.
- videoconvert normalizes the camera format.
- videorate forces the requested FPS.
- MP4 mode encodes and muxes, so the file is playable as video.
- Raw mode writes raw frames directly, so playback needs width/height/fps/format.
When stop_recording() runs:
- It blocks the recording tee output on the next buffer.
- It detaches that branch from the live camera stream.
- It sends EOS into the detached recording branch.
- EOS lets mp4mux write the MP4 trailer/final metadata.
- The branch is removed from the pipeline.
- The key idea is: preview is permanent, recording is dynamic.

Example usage:
curl -X POST http://127.0.0.1:8000/record/start \
  -H 'content-type: application/json' \
  -d '{"filename":"remote_test.mp4"}'

curl -X POST http://127.0.0.1:8000/record/stop

curl http://127.0.0.1:8000/record/list
"""
import argparse
import os
import sys
import threading

import gi
import uvicorn
from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib


Gst.init(None)
logger.remove()
logger.add(
    sys.stderr,
    format="{time:HH:mm:ss} | {level:<8} | {line} | {message}",
)


def get_element_or_raise(pipeline, name):
    elem = pipeline.get_by_name(name)
    if elem is None:
        raise RuntimeError(f"Could not find GStreamer element named {name!r}")
    return elem


class CameraRecorder:
    def __init__(
        self,
        device="/dev/video0",
        width=640,
        height=512,
        fps=30,
        record_format="mp4",
    ):
        if record_format not in {"mp4", "raw"}:
            raise ValueError("record_format must be 'mp4' or 'raw'")

        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.record_format = record_format
        self.record_filename = None

        self.loop = GLib.MainLoop()
        self.loop_thread = None

        pipeline_desc = f"""
            v4l2src name=camera
                ! video/x-raw,format=I420,width={self.width},height={self.height},framerate={self.fps}/1
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
        self.record_stop_timeout_id = None
        self.record_eos_sent = False
        self.record_first_pts = None
        self.record_first_dts = None
        self.stop_finished_event = None
        self.recording = False
        self.stopping = False

        self.pipeline.set_property("message-forward", True)
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_bus_message)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

        self.loop_thread = threading.Thread(target=self.loop.run, daemon=True)
        self.loop_thread.start()

    def shutdown(self):
        if self.recording and not self.stopping:
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
        self.record_filename = filename
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
        self.record_stop_timeout_id = None
        self.record_eos_sent = False
        self.record_first_pts = None
        self.record_first_dts = None

        logger.info(f"Recording started: {filename} ({self.record_format})")

    def stop_recording(self):
        if not self.recording or not self.record_bin:
            return None

        logger.info("Stopping recording...")

        self.stopping = True
        self.stop_finished_event = threading.Event()

        record_sink_pad = self.record_bin.get_static_pad("sink")
        if record_sink_pad is None:
            raise RuntimeError("Recording branch has no sink pad")

        if self.record_tee_pad is None:
            raise RuntimeError("Recording branch has no tee pad")

        def block_cb(pad, info):
            if not self.record_eos_sent:
                self.record_eos_sent = True
                self.record_block_probe_id = None
                pad.unlink(record_sink_pad)
                self.tee.release_request_pad(pad)
                self.record_tee_pad = None
                logger.info("Recording branch detached from tee")
                GLib.idle_add(self._send_recording_eos)
                return Gst.PadProbeReturn.REMOVE
            return Gst.PadProbeReturn.OK

        # Stop this tee output on the next buffer, detach it from the live
        # source, then send EOS into the detached recording branch.
        self.record_block_probe_id = self.record_tee_pad.add_probe(
            Gst.PadProbeType.BLOCK_DOWNSTREAM,
            block_cb,
        )
        return self.stop_finished_event

    def _send_recording_eos(self):
        if not self.stopping or not self.record_bin:
            return False

        record_sink_pad = self.record_bin.get_static_pad("sink")
        if record_sink_pad is None:
            logger.warning("Recording branch has no sink pad for EOS")
            return False

        if not record_sink_pad.send_event(Gst.Event.new_eos()):
            logger.warning("Failed to send EOS to recording branch")

        self.record_stop_timeout_id = GLib.timeout_add_seconds(
            5,
            self._finish_stop_recording_after_timeout,
        )
        return False

    def _finish_stop_recording_after_timeout(self):
        self.record_stop_timeout_id = None
        if self.stopping and self.record_bin:
            logger.warning("Recording stop timed out waiting for EOS; cleaning up branch")
            self._finish_stop_recording()
        return False

    def _finish_stop_recording(self):
        if not self.record_bin:
            return

        if self.record_stop_timeout_id is not None:
            GLib.source_remove(self.record_stop_timeout_id)
            self.record_stop_timeout_id = None

        if self.record_tee_pad is not None:
            record_sink_pad = self.record_bin.get_static_pad("sink")
            if self.record_block_probe_id is not None:
                self.record_tee_pad.remove_probe(self.record_block_probe_id)
                self.record_block_probe_id = None
            if record_sink_pad is not None:
                self.record_tee_pad.unlink(record_sink_pad)
            self.tee.release_request_pad(self.record_tee_pad)
            self.record_tee_pad = None

        # Remove branch.
        self.record_bin.set_state(Gst.State.NULL)
        self.pipeline.remove(self.record_bin)

        self._print_recording_summary()

        self.record_bin = None
        self.record_filename = None
        self.recording = False
        self.stopping = False
        self.record_eos_sent = False
        self.record_first_pts = None
        self.record_first_dts = None
        stop_finished_event = self.stop_finished_event
        self.stop_finished_event = None

        logger.info("Recording stopped and file finalized")
        if stop_finished_event is not None:
            stop_finished_event.set()
        return False

    def _print_recording_summary(self):
        if self.record_format != "raw" or not self.record_filename:
            return

        try:
            file_size = os.path.getsize(self.record_filename)
        except OSError as exc:
            logger.warning(f"Could not stat raw recording {self.record_filename}: {exc}")
            return

        frame_size = self.width * self.height * 3 // 2
        if frame_size <= 0:
            return

        frames = file_size / frame_size
        duration = frames / self.fps
        logger.info(
            f"Raw recording size={file_size} bytes, "
            f"frames={frames:.1f}, duration_at_{self.fps}fps={duration:.2f}s"
        )

    def _rebase_recording_timestamps(self, pad, info):
        buf = info.get_buffer()
        if buf is None:
            return Gst.PadProbeReturn.OK

        if self.record_first_pts is None and buf.pts != Gst.CLOCK_TIME_NONE:
            self.record_first_pts = buf.pts

        if self.record_first_dts is None and buf.dts != Gst.CLOCK_TIME_NONE:
            self.record_first_dts = buf.dts

        if self.record_first_pts is not None and buf.pts != Gst.CLOCK_TIME_NONE:
            buf.pts = max(0, buf.pts - self.record_first_pts)

        if self.record_first_dts is not None and buf.dts != Gst.CLOCK_TIME_NONE:
            buf.dts = max(0, buf.dts - self.record_first_dts)

        return Gst.PadProbeReturn.OK

    def _create_record_bin(self, filename):
        """
        Recording branch, selected by self.record_format:

            mp4: queue ! videoconvert ! x264enc ! h264parse ! mp4mux ! filesink
            raw: queue ! videoconvert ! video/x-raw,format=I420 ! filesink

        The bin exposes one ghost sink pad, so it can be linked directly to tee.
        """
        if self.record_format == "mp4":
            record_desc = f"""
            queue name=record-queue flush-on-eos=true
                ! videoconvert name=record-convert
                ! videorate name=record-rate drop-only=true
                ! video/x-raw,format=I420,framerate={self.fps}/1
                ! x264enc name=record-encoder
                          tune=zerolatency
                          speed-preset=veryfast
                          key-int-max={self.fps}
                ! h264parse name=record-parser
                ! mp4mux name=record-muxer
                ! filesink name=record-sink sync=false
        """
        else:
            record_desc = f"""
            queue name=record-queue flush-on-eos=true
                ! videoconvert name=record-convert
                ! videorate name=record-rate drop-only=true
                ! video/x-raw,format=I420,framerate={self.fps}/1
                ! filesink name=record-sink sync=false
        """

        record_bin = Gst.parse_bin_from_description(record_desc, True)
        record_bin.set_name("record-bin")
        record_bin.set_property("message-forward", True)

        if record_bin.get_static_pad("sink") is None:
            raise RuntimeError("Recording bin did not expose a sink ghost pad")

        record_sink_pad = record_bin.get_static_pad("sink")
        record_sink_pad.add_probe(
            Gst.PadProbeType.BUFFER,
            self._rebase_recording_timestamps,
        )

        record_sink = record_bin.get_by_name("record-sink")
        if record_sink is None:
            raise RuntimeError("Recording bin did not create a filesink")
        record_sink.set_property("location", filename)

        return record_bin

    def _on_bus_message(self, bus, message):
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            logger.error(f"GStreamer ERROR: {err}")
            if debug:
                logger.debug(f"Debug: {debug}")
            self.loop.quit()

        elif msg_type == Gst.MessageType.EOS:
            # EOS is expected when stopping the recording branch.
            # Do not shut down the whole app if this EOS came from stopping.
            if self.stopping:
                self._finish_stop_recording()
            else:
                logger.info("Pipeline EOS")
                self.loop.quit()

        elif msg_type == Gst.MessageType.ELEMENT:
            structure = message.get_structure()
            if structure is None or structure.get_name() != "GstBinForwarded":
                return

            forwarded = structure.get_value("message")
            if forwarded and forwarded.type == Gst.MessageType.EOS and self.stopping:
                source_name = forwarded.src.get_name() if forwarded.src else "unknown"
                logger.info(f"Recording branch EOS forwarded from {source_name}")
                self._finish_stop_recording()


class StartRecordingRequest(BaseModel):
    filename: str


class RecorderRequestError(ValueError):
    pass


class RecorderConflictError(RuntimeError):
    pass


class RecorderService:
    def __init__(
        self,
        recorder: CameraRecorder,
        target_folder: str,
        record_format: str,
    ):
        self.recorder = recorder
        self.target_folder = target_folder
        self.record_format = record_format
        self.extension = ".mp4" if record_format == "mp4" else ".i420"
        self.lock = threading.Lock()

    def start(self, filename: str):
        safe_filename = self._normalize_filename(filename)
        output_path = os.path.join(self.target_folder, safe_filename)

        with self.lock:
            if self.recorder.recording or self.recorder.stopping:
                raise RecorderConflictError("Recording is already active")

            self._run_on_gst_thread(
                lambda: self.recorder.start_recording(output_path),
                timeout=5,
            )

        return {"recording": True, "filename": safe_filename}

    def stop(self):
        with self.lock:
            if not self.recorder.recording or self.recorder.stopping:
                raise RecorderConflictError("No active recording")

            stop_finished_event = self._run_on_gst_thread(
                self.recorder.stop_recording,
                timeout=5,
            )

            if stop_finished_event is not None and not stop_finished_event.wait(15):
                raise TimeoutError("Timed out waiting for recording to finalize")

        return {"recording": False}

    def list_files(self):
        files = []
        for name in os.listdir(self.target_folder):
            path = os.path.join(self.target_folder, name)
            if os.path.isfile(path) and name.endswith(self.extension):
                files.append(name)
        return {"files": sorted(files)}

    def status(self):
        filename = None
        if self.recorder.record_filename:
            filename = os.path.basename(self.recorder.record_filename)
        return {
            "recording": bool(self.recorder.recording),
            "filename": filename,
            "format": self.record_format,
        }

    def shutdown(self):
        with self.lock:
            if self.recorder.recording and self.recorder.stopping:
                stop_finished_event = self.recorder.stop_finished_event
                if stop_finished_event is not None:
                    stop_finished_event.wait(15)

            elif self.recorder.recording:
                try:
                    stop_finished_event = self._run_on_gst_thread(
                        self.recorder.stop_recording,
                        timeout=5,
                    )
                    if stop_finished_event is not None:
                        stop_finished_event.wait(15)
                except Exception as exc:
                    logger.warning(f"Failed to stop recording during shutdown: {exc}")

        self.recorder.shutdown()

    def _normalize_filename(self, filename: str):
        if not filename:
            raise RecorderRequestError("filename is required")

        if os.path.isabs(filename) or os.path.basename(filename) != filename:
            raise RecorderRequestError("filename must be a basename, not a path")

        stem, ext = os.path.splitext(filename)
        if not stem or stem in {".", ".."}:
            raise RecorderRequestError("filename is invalid")

        if ext and ext.lower() != self.extension:
            raise RecorderRequestError(f"filename extension must be {self.extension}")

        return f"{stem}{self.extension}"

    def _run_on_gst_thread(self, func, timeout: float):
        done = threading.Event()
        result = {}

        def runner():
            try:
                result["value"] = func()
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()
            return False

        GLib.idle_add(runner)

        if not done.wait(timeout):
            raise TimeoutError("Timed out waiting for GStreamer operation")

        if "error" in result:
            raise result["error"]

        return result.get("value")


def create_app(service: RecorderService):
    app = FastAPI(title="BT GST Recorder")

    @app.post("/record/start")
    def start_recording(request: StartRecordingRequest):
        try:
            return service.start(request.filename)
        except RecorderRequestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RecorderConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to start recording")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/record/stop")
    def stop_recording():
        try:
            return service.stop()
        except RecorderConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to stop recording")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/record/list")
    def list_recordings():
        return service.list_files()

    @app.get("/record/status")
    def recording_status():
        return service.status()

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--record-format", choices=["mp4", "raw"], default="mp4")
    parser.add_argument("--target-folder", default="./output")
    parser.add_argument("--api-host", default="0.0.0.0")
    parser.add_argument("--api-port", type=int, default=8000)
    args = parser.parse_args()

    os.makedirs(args.target_folder, exist_ok=True)

    rec = CameraRecorder(
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        record_format=args.record_format,
    )

    service = RecorderService(
        recorder=rec,
        target_folder=args.target_folder,
        record_format=args.record_format,
    )
    app = create_app(service)

    rec.start()

    try:
        logger.info(
            f"Camera running; API listening on http://{args.api_host}:{args.api_port}"
        )
        if args.record_format == "raw":
            logger.info(
                "Raw playback example: "
                f"gst-launch-1.0 filesrc location={args.target_folder}/example.i420 "
                f"! rawvideoparse format=i420 width={args.width} height={args.height} "
                f"framerate={args.fps}/1 ! videoconvert ! autovideosink"
            )
        uvicorn.run(app, host=args.api_host, port=args.api_port)
    finally:
        service.shutdown()


if __name__ == "__main__":
    main()

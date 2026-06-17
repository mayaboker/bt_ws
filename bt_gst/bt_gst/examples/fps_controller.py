import queue
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GLib


Gst.init(None)


CMD_INIT = "init"
CMD_SHUTDOWN = "shutdown"
CMD_SET_FPS = "set_fps"
CMD_STATUS = "status"

SUPPORTED_FPS = (1, 5, 10, 20, 30)
DEFAULT_FPS = 30


@dataclass
class Command:
    name: str
    args: dict[str, Any]
    future: Future


class FpsController:
    def __init__(self):
        self.commands: queue.Queue[Command] = queue.Queue()

        self.context = GLib.MainContext()
        self.loop = GLib.MainLoop.new(self.context, False)
        self.thread = threading.Thread(target=self._thread_main, daemon=True)

        self.pipeline = None
        self.capsfilter = None
        self.fps = DEFAULT_FPS
        self.started = False

    def start(self):
        self.thread.start()
        return self.call_sync(CMD_INIT, timeout=5)

    def stop(self):
        try:
            self.call_sync(CMD_SHUTDOWN, timeout=5)
        finally:
            self._invoke(lambda: self.loop.quit() or False)
            self.thread.join(timeout=2)

    def submit(self, name: str, args: dict | None = None) -> Future:
        future = Future()
        cmd = Command(name=name, args=args or {}, future=future)
        self.commands.put(cmd)
        self._invoke(self._process_commands)
        return future

    def call_sync(self, name: str, args: dict | None = None, timeout: float = 2):
        future = self.submit(name, args)
        return future.result(timeout=timeout)

    def _invoke(self, callback):
        self.context.invoke_full(GLib.PRIORITY_DEFAULT, callback)

    def _thread_main(self):
        self.context.push_thread_default()
        try:
            self.loop.run()
        finally:
            self.context.pop_thread_default()

    def _process_commands(self):
        while True:
            try:
                cmd = self.commands.get_nowait()
            except queue.Empty:
                break

            try:
                result = self._handle_command(cmd)
                cmd.future.set_result(result)
            except Exception as exc:
                cmd.future.set_exception(exc)

        return False

    def _handle_command(self, cmd: Command):
        name = cmd.name
        args = cmd.args

        if name == CMD_INIT:
            return self._init_pipeline()
        if name == CMD_SHUTDOWN:
            return self._shutdown_pipeline()
        if name == CMD_SET_FPS:
            return self._set_fps(args["fps"])
        if name == CMD_STATUS:
            return self._status()

        raise RuntimeError(f"Unknown command: {name}")

    def _init_pipeline(self):
        if self.started:
            return {"ok": True, "already_started": True, **self._status_fields()}

        self.pipeline = Gst.parse_launch(
            "v4l2src device=/dev/video0 "
            "! video/x-raw,format=YUY2,width=640,height=512,framerate=30/1 "
            "! videorate name=rate drop-only=true "
            "! capsfilter name=fps_caps "
            "! videoconvert "
            "! fpsdisplaysink sync=false "
        )

        self.capsfilter = self.pipeline.get_by_name("fps_caps")
        if self.capsfilter is None:
            raise RuntimeError("Could not find fps capsfilter")

        self._apply_fps_caps(self.fps)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start FPS control pipeline")

        self.started = True
        return {"ok": True, **self._status_fields()}

    def _shutdown_pipeline(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.capsfilter = None

        self.started = False
        return {"ok": True, **self._status_fields()}

    def _set_fps(self, fps: int):
        fps = self._validate_fps(fps)
        if self.capsfilter is None:
            raise RuntimeError("Pipeline is not running")

        self._apply_fps_caps(fps)
        self.fps = fps
        return {"ok": True, **self._status_fields()}

    def _validate_fps(self, fps: int):
        if fps not in SUPPORTED_FPS:
            raise ValueError(f"FPS must be one of: {', '.join(map(str, SUPPORTED_FPS))}")
        return fps

    def _apply_fps_caps(self, fps: int):
        caps = Gst.Caps.from_string(f"video/x-raw,framerate={fps}/1")
        self.capsfilter.set_property("caps", caps)

    def _status(self):
        return {"ok": True, **self._status_fields()}

    def _status_fields(self):
        return {
            "started": self.started,
            "fps": self.fps,
            "supported_fps": list(SUPPORTED_FPS),
            "has_pipeline": self.pipeline is not None,
            "has_capsfilter": self.capsfilter is not None,
        }

    def _on_bus_message(self, bus, message):
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"GStreamer error: {err}")
            if debug:
                print(f"GStreamer debug: {debug}")

        elif msg_type == Gst.MessageType.EOS:
            print("GStreamer EOS")

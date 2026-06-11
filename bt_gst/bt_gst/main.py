import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from bt_gst import __version__
from bt_gst.cli import PlayCommand, VersionCommand, parse_args
from bt_gst.zmq_io import TrackerMetaPublisher, ZmqPublisherError

DEFAULT_VIDEO = Path(__file__).resolve().parents[1] / "data" / "vtest.avi"
GST_PLUGIN_PATH = Path(__file__).resolve().parents[1] / "plugins"
TRACKER_META_NAME = "bt-tracker-meta"


@dataclass(frozen=True)
class TrackerMeta:
    dx: int
    dy: int
    score: float


class PlaybackError(RuntimeError):
    """Raised when GStreamer playback fails."""


def build_video_pipeline_description(video_path: Path) -> str:
    resolved_path = video_path.resolve()
    location = str(resolved_path).replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'filesrc location="{location}" ! decodebin ! videoconvert ! '
        "btpassthrough ! tee name=metadata_tee "
        "metadata_tee. ! queue ! gtksink name=video_sink "
        "metadata_tee. ! queue leaky=downstream max-size-buffers=1 ! "
        "appsink name=metadata_sink emit-signals=false sync=false max-buffers=1 drop=true"
    )


def configure_gst_plugin_path() -> None:
    plugin_path = str(GST_PLUGIN_PATH)
    existing_path = os.environ.get("GST_PLUGIN_PATH")
    if not existing_path:
        os.environ["GST_PLUGIN_PATH"] = plugin_path
        return

    paths = existing_path.split(os.pathsep)
    if plugin_path not in paths:
        os.environ["GST_PLUGIN_PATH"] = os.pathsep.join([plugin_path, *paths])


def play_video(video_path: Path = DEFAULT_VIDEO) -> None:
    configure_gst_plugin_path()

    try:
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("GstApp", "1.0")
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gst, GstApp, Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "GStreamer Python bindings are unavailable. Install PyGObject and "
            "the native GStreamer/Gtk introspection packages."
        ) from exc

    Gst.init(None)
    Gtk.init(None)

    pipeline_description = build_video_pipeline_description(video_path)
    try:
        pipeline = Gst.parse_launch(pipeline_description)
    except Exception as exc:
        raise PlaybackError(f"failed to create GStreamer pipeline: {exc}") from exc

    sink = pipeline.get_by_name("video_sink")
    if sink is None:
        raise RuntimeError(
            "GStreamer element 'gtksink' was not found. Install the GTK "
            "GStreamer plugin package, usually gst-plugins-good."
        )

    metadata_sink = pipeline.get_by_name("metadata_sink")
    if metadata_sink is None:
        raise RuntimeError("GStreamer element 'metadata_sink' was not found.")

    running = True

    def close_window(window: object) -> None:
        nonlocal running
        running = False

    window = Gtk.Window(title=f"bt-gst: {video_path.name}")
    window.set_default_size(960, 540)
    window.connect("destroy", close_window)
    window.add(sink.get_property("widget"))
    window.show_all()

    bus = pipeline.get_bus()

    publisher = TrackerMetaPublisher()

    try:
        try:
            publisher.start()
        except ZmqPublisherError as exc:
            raise PlaybackError(str(exc)) from exc

        state_result = pipeline.set_state(Gst.State.PLAYING)
        if state_result == Gst.StateChangeReturn.FAILURE:
            raise PlaybackError("failed to start GStreamer pipeline")

        while running:
            while Gtk.events_pending():
                Gtk.main_iteration()

            message = bus.timed_pop_filtered(
                10_000_000,
                Gst.MessageType.ERROR | Gst.MessageType.EOS,
            )
            if message is not None and _handle_bus_message(message):
                break

            sample = metadata_sink.try_pull_sample(10 * Gst.MSECOND)
            if sample is None:
                continue

            buffer = sample.get_buffer()
            if buffer is None:
                continue

            tracker_meta = read_tracker_meta(buffer)
            if tracker_meta is not None:
                publisher.publish(tracker_meta)
                print_tracker_meta(tracker_meta)
    finally:
        publisher.close()
        pipeline.set_state(Gst.State.NULL)


def read_tracker_meta(buffer: object) -> TrackerMeta | None:
    meta = buffer.get_custom_meta(TRACKER_META_NAME)
    if meta is None:
        return None

    structure = meta.get_structure()
    return TrackerMeta(
        dx=structure.get_value("dx"),
        dy=structure.get_value("dy"),
        score=structure.get_value("score"),
    )


def print_tracker_meta(meta: TrackerMeta) -> None:
    print(f"{TRACKER_META_NAME} dx={meta.dx} dy={meta.dy} score={meta.score}")


def _handle_bus_message(message: object) -> bool:
    from gi.repository import Gst

    if message.type == Gst.MessageType.ERROR:
        error, debug = message.parse_error()
        message_text = f"GStreamer error: {error.message}"
        if debug:
            message_text = f"{message_text}\n{debug}"
        raise PlaybackError(message_text)
    elif message.type == Gst.MessageType.EOS:
        return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    command = parse_args(argv)
    if isinstance(command, int):
        return command
    if isinstance(command, VersionCommand):
        print(__version__)
        return 0
    if isinstance(command, PlayCommand):
        try:
            play_video(command.video)
        except PlaybackError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    raise RuntimeError(f"unsupported command: {command!r}")


if __name__ == "__main__":
    raise SystemExit(main())

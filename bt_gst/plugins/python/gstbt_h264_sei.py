import json
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstBase", "1.0")
from gi.repository import GObject, Gst, GstBase  # noqa: E402

EXAMPLES_PATH = Path(__file__).resolve().parents[2] / "bt_gst" / "examples"
if str(EXAMPLES_PATH) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_PATH))

from h264_sei import insert_sei_before_first_vcl  # noqa: E402

Gst.init(None)

H264_CAPS = "video/x-h264,stream-format=byte-stream,alignment=au"


def buffer_to_bytes(buffer: Gst.Buffer) -> bytes | None:
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        return None

    try:
        return bytes(map_info.data)
    finally:
        buffer.unmap(map_info)


def clone_timing_and_flags(source: Gst.Buffer, target: Gst.Buffer) -> None:
    target.pts = source.pts
    target.dts = source.dts
    target.duration = source.duration
    target.offset = source.offset
    target.offset_end = source.offset_end
    target.set_flags(source.get_flags())


def build_sei_payload(buffer: Gst.Buffer) -> bytes:
    return json.dumps(
        {
            "unix_time": time.time(),
            "pts": int(buffer.pts),
            "message": "bt-gst h264 sei",
        },
        separators=(",", ":"),
    ).encode("utf-8")


class BtH264Sei(GstBase.BaseTransform):
    __gstmetadata__ = (
        "BT H264 SEI",
        "Filter/Video",
        "Injects user_data_unregistered SEI into H.264 access units",
        "bt_ws",
    )

    __gsttemplates__ = (
        Gst.PadTemplate.new(
            "src",
            Gst.PadDirection.SRC,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string(H264_CAPS),
        ),
        Gst.PadTemplate.new(
            "sink",
            Gst.PadDirection.SINK,
            Gst.PadPresence.ALWAYS,
            Gst.Caps.from_string(H264_CAPS),
        ),
    )

    def __init__(self) -> None:
        super().__init__()
        self.set_in_place(False)
        self.set_passthrough(False)

    def do_prepare_output_buffer(
        self,
        input_buffer: Gst.Buffer,
    ) -> tuple[Gst.FlowReturn, Gst.Buffer | None]:
        access_unit = buffer_to_bytes(input_buffer)
        if access_unit is None:
            return Gst.FlowReturn.ERROR, None

        payload = build_sei_payload(input_buffer)
        output_data = insert_sei_before_first_vcl(access_unit, payload)
        output_buffer = Gst.Buffer.new_wrapped(output_data)
        clone_timing_and_flags(input_buffer, output_buffer)

        print(f"send H264 SEI: pts={input_buffer.pts}, bytes={len(payload)}")
        return Gst.FlowReturn.OK, output_buffer

    def do_transform(
        self,
        input_buffer: Gst.Buffer,
        output_buffer: Gst.Buffer,
    ) -> Gst.FlowReturn:
        return Gst.FlowReturn.OK


GObject.type_register(BtH264Sei)
if Gst.ElementFactory.find("bt_h264_sei") is None:
    Gst.Element.register(None, "bt_h264_sei", Gst.Rank.NONE, BtH264Sei)
__gstelementfactory__ = ("bt_h264_sei", Gst.Rank.NONE, BtH264Sei)

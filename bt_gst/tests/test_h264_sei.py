import importlib.util
import sys
from pathlib import Path

import pytest

EXAMPLES_PATH = Path(__file__).resolve().parents[1] / "bt_gst" / "examples"
PLUGIN_PATH = (
    Path(__file__).resolve().parents[1] / "plugins" / "python" / "gstbt_h264_sei.py"
)

if str(EXAMPLES_PATH) not in sys.path:
    sys.path.insert(0, str(EXAMPLES_PATH))

from h264_sei import (  # noqa: E402
    BT_SEI_UUID,
    extract_user_data_unregistered,
    insert_sei_before_first_vcl,
    iter_annexb_nalus,
)


def load_h264_sei_plugin_module():
    spec = importlib.util.spec_from_file_location("gstbt_h264_sei", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_insert_sei_before_first_vcl_nal() -> None:
    aud = b"\x00\x00\x00\x01\x09\xf0"
    idr = b"\x00\x00\x00\x01\x65\x88\x84"

    output = insert_sei_before_first_vcl(aud + idr, b"payload")
    nals = [(output[nal_header] & 0x1F) for _, nal_header, _ in iter_annexb_nalus(output)]

    assert nals == [9, 6, 5]
    assert extract_user_data_unregistered(output) == [b"payload"]


def test_extract_sei_ignores_different_uuid() -> None:
    output = insert_sei_before_first_vcl(
        b"\x00\x00\x00\x01\x65\x88\x84",
        b"payload",
        uuid=b"0123456789abcdef",
    )

    assert extract_user_data_unregistered(output, uuid=BT_SEI_UUID) == []


def test_sei_payload_escapes_and_unescapes_start_code_bytes() -> None:
    payload = b'{"zero":"\x00\x00\x01","three":"\x00\x00\x03"}'

    output = insert_sei_before_first_vcl(b"\x00\x00\x00\x01\x65\x88\x84", payload)

    assert extract_user_data_unregistered(output) == [payload]


@pytest.mark.skipif(
    importlib.util.find_spec("gi") is None,
    reason="PyGObject is unavailable",
)
def test_h264_sei_transform_prepares_larger_output_buffer() -> None:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    module = load_h264_sei_plugin_module()
    element = module.BtH264Sei()
    input_data = b"\x00\x00\x00\x01\x09\xf0\x00\x00\x00\x01\x65\x88\x84"
    input_buffer = Gst.Buffer.new_wrapped(input_data)
    input_buffer.pts = 123
    input_buffer.dts = 100
    input_buffer.duration = 33
    input_buffer.offset = 7
    input_buffer.offset_end = 8
    input_buffer.set_flags(Gst.BufferFlags.DELTA_UNIT)

    result, output_buffer = element.do_prepare_output_buffer(input_buffer)

    assert result == Gst.FlowReturn.OK
    assert output_buffer is not None
    assert output_buffer.get_size() > input_buffer.get_size()
    assert output_buffer.pts == input_buffer.pts
    assert output_buffer.dts == input_buffer.dts
    assert output_buffer.duration == input_buffer.duration
    assert output_buffer.offset == input_buffer.offset
    assert output_buffer.offset_end == input_buffer.offset_end
    assert output_buffer.has_flags(Gst.BufferFlags.DELTA_UNIT)
    assert module.buffer_to_bytes(output_buffer) is not None
    assert extract_user_data_unregistered(module.buffer_to_bytes(output_buffer))

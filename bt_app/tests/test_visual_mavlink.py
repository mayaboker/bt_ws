import struct

import pytest

from bt_app.visual_mavlink import (
    MAX_MESSAGEPACK_SIZE,
    RED_DETECTION_PROTOCOL_VERSION,
    V2_EXTENSION_PAYLOAD_SIZE,
    VisualMavlinkCodecError,
    decode_red_detection,
    encode_red_detection,
)


def detection(**overrides):
    value = {
        "type": "red-detection",
        "frame_id": 42,
        "timestamp_ns": None,
        "found": True,
        "x": 210,
        "y": 130,
        "width": 80,
        "height": 60,
        "locked": True,
        "lock_found_frames": 10,
        "lock_missing_frames": 0,
    }
    value.update(overrides)
    return value


def test_red_detection_round_trip_uses_padded_versioned_envelope():
    payload = encode_red_detection(detection())

    assert len(payload) == V2_EXTENSION_PAYLOAD_SIZE
    assert payload[0] == RED_DETECTION_PROTOCOL_VERSION
    assert decode_red_detection(payload) == detection()


def test_red_detection_round_trip_preserves_timestamp():
    expected = detection(timestamp_ns=123456789)
    assert decode_red_detection(encode_red_detection(expected)) == expected


def test_decoder_rejects_wrong_version_and_truncated_payload():
    wrong_version = bytearray(encode_red_detection(detection()))
    wrong_version[0] += 1
    with pytest.raises(VisualMavlinkCodecError, match="unsupported"):
        decode_red_detection(wrong_version)

    with pytest.raises(VisualMavlinkCodecError, match="truncated"):
        decode_red_detection(struct.pack("<BH", 1, MAX_MESSAGEPACK_SIZE))


def test_encoder_requires_exact_red_detection_schema():
    invalid = detection()
    invalid.pop("locked")
    with pytest.raises(VisualMavlinkCodecError, match="missing"):
        encode_red_detection(invalid)

import msgpack
import pytest

from bt_gst.bridge.zmq_models import (
    MESSAGE_TYPE_FIELD,
    RedDetectionMessage,
    decode_request,
    decode_telemetry_message,
    encode_message,
)


@pytest.mark.parametrize(
    "message",
    [
        {"type": "start", "x": 10, "y": 20},
        {"type": "stop"},
        {"type": "resize", "width": 80, "height": 90},
        {"type": "adjustment", "delta_x": -10, "delta_y": 10},
    ],
)
def test_track_request_round_trip(message) -> None:
    assert decode_request(encode_message(message)) == message


@pytest.mark.parametrize("timestamp_ns", [123456789, None])
def test_red_detection_message_round_trip(timestamp_ns: int | None) -> None:
    message = RedDetectionMessage(
        frame_id=9,
        timestamp_ns=timestamp_ns,
        found=True,
        x=10,
        y=20,
        width=30,
        height=40,
        locked=True,
        lock_found_frames=10,
        lock_missing_frames=0,
    )

    assert decode_telemetry_message(encode_message(message)) == message


def test_red_detection_message_has_stable_type() -> None:
    payload = msgpack.unpackb(
        encode_message(RedDetectionMessage(1, None, False, 0, 0, 0, 0)),
        raw=False,
    )

    assert payload["type"] == "red-detection"


def test_legacy_red_detection_decodes_as_unlocked() -> None:
    payload = msgpack.packb(
        {
            "type": "red-detection",
            "frame_id": 1,
            "timestamp_ns": None,
            "found": True,
            "x": 1,
            "y": 2,
            "width": 3,
            "height": 4,
        },
        use_bin_type=True,
    )

    message = decode_telemetry_message(payload)

    assert isinstance(message, RedDetectionMessage)
    assert not message.locked
    assert message.lock_found_frames == 0
    assert message.lock_missing_frames == 0


def test_encoded_message_contains_stable_type_field() -> None:
    payload = msgpack.unpackb(
        encode_message({"type": "start", "x": 1, "y": 2}),
        raw=False,
    )

    assert payload[MESSAGE_TYPE_FIELD] == "start"
    assert payload["x"] == 1
    assert payload["y"] == 2


def test_decode_request_rejects_unknown_type() -> None:
    payload = msgpack.packb({"type": "unknown"}, use_bin_type=True)

    with pytest.raises(ValueError, match="unsupported request message type"):
        decode_request(payload)


def test_decode_telemetry_rejects_removed_tracker_type() -> None:
    payload = msgpack.packb({"type": "tracker-data"}, use_bin_type=True)

    with pytest.raises(ValueError, match="unsupported telemetry message type"):
        decode_telemetry_message(payload)

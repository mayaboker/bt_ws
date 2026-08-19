from dataclasses import FrozenInstanceError

import msgpack
import pytest

from bt_msgs import TRACKER_STATE_UNKNOWN, TrackerResultMessage


def wire_message(**overrides: object) -> dict[str, object]:
    message: dict[str, object] = {
        "tracker_id": 0,
        "frame_id": 7,
        "timestamp_ns": 123456789,
        "locked": True,
        "bbox_x": 10,
        "bbox_y": 20,
        "bbox_width": 30,
        "bbox_height": 40,
        "score": 0.75,
        "state": TRACKER_STATE_UNKNOWN,
        "dx": -5,
        "dy": 6,
    }
    message.update(overrides)
    return message


def test_tracker_result_encode_decode_round_trip() -> None:
    message = TrackerResultMessage(**wire_message())

    assert TrackerResultMessage.decode(message.encode()) == message


def test_tracker_result_defaults_are_explicit_on_the_wire() -> None:
    message = TrackerResultMessage(frame_id=7, timestamp_ns=None)

    assert msgpack.unpackb(message.encode(), raw=False) == wire_message(
        frame_id=7,
        timestamp_ns=None,
        locked=False,
        bbox_x=0,
        bbox_y=0,
        bbox_width=0,
        bbox_height=0,
        score=0.0,
        dx=0,
        dy=0,
    )


def test_tracker_result_is_frozen_and_slotted() -> None:
    message = TrackerResultMessage(frame_id=1, timestamp_ns=None)

    assert not hasattr(message, "__dict__")
    with pytest.raises(FrozenInstanceError):
        message.frame_id = 2


def test_decode_ignores_unknown_fields() -> None:
    payload = msgpack.packb(
        wire_message(future_field="supported"), use_bin_type=True
    )

    assert TrackerResultMessage.decode(payload) == TrackerResultMessage(
        **wire_message()
    )


def test_decode_requires_a_mapping() -> None:
    payload = msgpack.packb([1, 2], use_bin_type=True)

    with pytest.raises(ValueError, match="must contain a mapping"):
        TrackerResultMessage.decode(payload)


def test_decode_requires_every_wire_field() -> None:
    message = wire_message()
    del message["score"]

    with pytest.raises(ValueError, match="score"):
        TrackerResultMessage.decode(msgpack.packb(message, use_bin_type=True))


@pytest.mark.parametrize("payload", [b"\x81", msgpack.packb({}) + b"trailing"])
def test_decode_normalizes_messagepack_failures(payload: bytes) -> None:
    with pytest.raises(ValueError, match="MessagePack"):
        TrackerResultMessage.decode(payload)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("tracker_id", True, "tracker_id must be an integer"),
        ("frame_id", "7", "frame_id must be an integer"),
        ("timestamp_ns", -1, "timestamp_ns must be nonnegative"),
        ("locked", 1, "locked must be a boolean"),
        ("bbox_x", -1, "bbox_x must be nonnegative"),
        ("score", 1, "score must be a float"),
        ("score", 1.1, "score must be between"),
        ("state", -1, "state must be nonnegative"),
        ("dx", 1.5, "dx must be an integer"),
    ],
)
def test_decode_rejects_invalid_fields(field: str, value: object, error: str) -> None:
    payload = msgpack.packb(wire_message(**{field: value}), use_bin_type=True)

    with pytest.raises(ValueError, match=error):
        TrackerResultMessage.decode(payload)


def test_locked_result_requires_a_positive_box() -> None:
    with pytest.raises(ValueError, match="positive bounding-box size"):
        TrackerResultMessage(
            **wire_message(bbox_width=0),
        )


def test_unlocked_result_requires_an_all_zero_box() -> None:
    with pytest.raises(ValueError, match="all-zero bounding box"):
        TrackerResultMessage(
            **wire_message(locked=False),
        )


def test_encode_normalizes_oversized_integer_failure() -> None:
    message = TrackerResultMessage(frame_id=1 << 100, timestamp_ns=None)

    with pytest.raises(ValueError, match="unable to encode"):
        message.encode()

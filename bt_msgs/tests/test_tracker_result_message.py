import msgpack
import pytest

from bt_msgs import TrackerResultMessage


@pytest.mark.parametrize("timestamp", [123456789, None])
def test_tracker_result_encode_decode_round_trip(timestamp: int | None) -> None:
    message = TrackerResultMessage(frame_id=7, timestamp=timestamp)

    assert TrackerResultMessage.decode(message.encode()) == message


def test_tracker_result_wire_mapping() -> None:
    message = TrackerResultMessage(frame_id=7, timestamp=123)

    assert msgpack.unpackb(message.encode(), raw=False) == {
        "frame_id": 7,
        "timestamp": 123,
    }


def test_tracker_result_decode_requires_mapping() -> None:
    payload = msgpack.packb([1, 2], use_bin_type=True)

    with pytest.raises(ValueError, match="must contain a mapping"):
        TrackerResultMessage.decode(payload)


def test_tracker_result_decode_requires_both_fields() -> None:
    payload = msgpack.packb({"frame_id": 1}, use_bin_type=True)

    with pytest.raises(ValueError, match="timestamp"):
        TrackerResultMessage.decode(payload)


@pytest.mark.parametrize(
    "message",
    [
        {"frame_id": True, "timestamp": 1},
        {"frame_id": 1, "timestamp": "invalid"},
    ],
)
def test_tracker_result_rejects_non_integer_fields(message: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        TrackerResultMessage.decode(msgpack.packb(message, use_bin_type=True))


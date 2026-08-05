import msgpack
import pytest

from bt_gst.bridge.zmq_models import (
    MESSAGE_TYPE_FIELD,
    RedDetectionMessage,
    TrackAdjustmentRequest,
    TrackerDataMessage,
    TrackerDebugMessage,
    TrackResizeRequest,
    TrackStartRequest,
    TrackStopRequest,
    decode_request,
    decode_telemetry_message,
    decode_tracker_message,
    encode_message,
)


@pytest.mark.parametrize(
    "message",
    [
        TrackStartRequest(x=10, y=20),
        TrackStopRequest(),
        TrackResizeRequest(width=80, height=90),
        TrackAdjustmentRequest(delta_x=-10, delta_y=10),
    ],
)
def test_track_request_round_trip(message) -> None:
    assert decode_request(encode_message(message)) == message


@pytest.mark.parametrize(
    "message",
    [
        TrackerDataMessage(
            frame_id=7,
            timestamp=123.5,
            dx=1,
            dy=-2,
            score=0.75,
            status=1,
        ),
        TrackerDebugMessage(
            frame_number=8,
            status=1,
            active_feature_count=3,
            features_json='[{"x":1.0,"y":2.0}]',
        ),
    ],
)
def test_tracker_message_round_trip(message) -> None:
    assert decode_tracker_message(encode_message(message)) == message


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
    )

    assert decode_telemetry_message(encode_message(message)) == message


def test_red_detection_message_has_stable_type() -> None:
    payload = msgpack.unpackb(
        encode_message(RedDetectionMessage(1, None, False, 0, 0, 0, 0)),
        raw=False,
    )

    assert payload["type"] == "red-detection"


def test_encoded_message_contains_stable_type_field() -> None:
    payload = msgpack.unpackb(
        encode_message(TrackStartRequest(x=1, y=2)),
        raw=False,
    )

    assert payload[MESSAGE_TYPE_FIELD] == "start"
    assert payload["x"] == 1
    assert payload["y"] == 2


def test_decode_request_rejects_unknown_type() -> None:
    payload = msgpack.packb({"type": "unknown"}, use_bin_type=True)

    with pytest.raises(ValueError, match="unsupported request message type"):
        decode_request(payload)

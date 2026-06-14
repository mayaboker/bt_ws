"""MessagePack models for tracker IO transport."""

from dataclasses import asdict, dataclass, field
from typing import TypeAlias

import msgpack

MESSAGE_TYPE_FIELD = "type"

TYPE_TRACK_START = "start"
TYPE_TRACK_STOP = "stop"
TYPE_TRACK_RESIZE = "resize"
TYPE_TRACK_ADJUSTMENT = "adjustment"
TYPE_TRACKER_DATA = "tracker-data"
TYPE_TRACKER_DEBUG = "tracker-debug"


@dataclass(frozen=True)
class TrackStartRequest:
    x: int
    y: int
    type: str = field(default=TYPE_TRACK_START, init=False)


@dataclass(frozen=True)
class TrackStopRequest:
    type: str = field(default=TYPE_TRACK_STOP, init=False)


@dataclass(frozen=True)
class TrackResizeRequest:
    width: int
    height: int
    type: str = field(default=TYPE_TRACK_RESIZE, init=False)


@dataclass(frozen=True)
class TrackAdjustmentRequest:
    delta_x: int
    delta_y: int
    type: str = field(default=TYPE_TRACK_ADJUSTMENT, init=False)


@dataclass(frozen=True)
class TrackerDataMessage:
    frame_id: int
    timestamp: float
    dx: int
    dy: int
    score: float
    status: int
    type: str = field(default=TYPE_TRACKER_DATA, init=False)


@dataclass(frozen=True)
class TrackerDebugMessage:
    frame_number: int
    status: int
    active_feature_count: int
    features_json: str
    type: str = field(default=TYPE_TRACKER_DEBUG, init=False)


TrackRequest: TypeAlias = (
    TrackStartRequest | TrackStopRequest | TrackResizeRequest | TrackAdjustmentRequest
)
TrackerMessage: TypeAlias = TrackerDataMessage | TrackerDebugMessage
TransportMessage: TypeAlias = TrackRequest | TrackerMessage


def encode_message(message: TransportMessage) -> bytes:
    return msgpack.packb(asdict(message), use_bin_type=True)


def decode_request(payload: bytes) -> TrackRequest:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(data, dict):
        raise ValueError("messagepack payload must decode to a map")

    message_type = data.get(MESSAGE_TYPE_FIELD)
    if message_type == TYPE_TRACK_START:
        return TrackStartRequest(x=int(data["x"]), y=int(data["y"]))
    if message_type == TYPE_TRACK_STOP:
        return TrackStopRequest()
    if message_type == TYPE_TRACK_RESIZE:
        return TrackResizeRequest(width=int(data["width"]), height=int(data["height"]))
    if message_type == TYPE_TRACK_ADJUSTMENT:
        return TrackAdjustmentRequest(
            delta_x=int(data["delta_x"]),
            delta_y=int(data["delta_y"]),
        )
    raise ValueError(f"unsupported request message type: {message_type!r}")


def decode_tracker_message(payload: bytes) -> TrackerMessage:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(data, dict):
        raise ValueError("messagepack payload must decode to a map")

    message_type = data.get(MESSAGE_TYPE_FIELD)
    if message_type == TYPE_TRACKER_DATA:
        return TrackerDataMessage(
            frame_id=int(data["frame_id"]),
            timestamp=float(data["timestamp"]),
            dx=int(data["dx"]),
            dy=int(data["dy"]),
            score=float(data["score"]),
            status=int(data["status"]),
        )
    if message_type == TYPE_TRACKER_DEBUG:
        return TrackerDebugMessage(
            frame_number=int(data["frame_number"]),
            status=int(data["status"]),
            active_feature_count=int(data["active_feature_count"]),
            features_json=str(data["features_json"]),
        )
    raise ValueError(f"unsupported tracker message type: {message_type!r}")

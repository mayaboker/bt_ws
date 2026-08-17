"""MessagePack models for tracker IO transport."""

from dataclasses import asdict, dataclass, field
from typing import TypeAlias

import msgpack

MESSAGE_TYPE_FIELD = "type"

TYPE_TRACK_START = "start"
TYPE_TRACK_STOP = "stop"
TYPE_TRACK_RESIZE = "resize"
TYPE_TRACK_ADJUSTMENT = "adjustment"
TYPE_RED_DETECTION = "red-detection"


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
class RedDetectionMessage:
    frame_id: int
    timestamp_ns: int | None
    found: bool
    x: int
    y: int
    width: int
    height: int
    locked: bool = False
    lock_found_frames: int = 0
    lock_missing_frames: int = 0
    type: str = field(default=TYPE_RED_DETECTION, init=False)


TrackRequest: TypeAlias = (
    TrackStartRequest | TrackStopRequest | TrackResizeRequest | TrackAdjustmentRequest
)
TelemetryMessage: TypeAlias = RedDetectionMessage
TransportMessage: TypeAlias = TrackRequest | TelemetryMessage


def encode_message(message: TransportMessage) -> bytes:
    return msgpack.packb(asdict(message), use_bin_type=True)


def decode_request(payload: bytes) -> TrackRequest:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(data, dict):
        raise TypeError("messagepack payload must decode to a map")

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


def decode_telemetry_message(payload: bytes) -> TelemetryMessage:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(data, dict):
        raise TypeError("messagepack payload must decode to a map")

    message_type = data.get(MESSAGE_TYPE_FIELD)
    if message_type == TYPE_RED_DETECTION:
        timestamp_ns = data["timestamp_ns"]
        return RedDetectionMessage(
            frame_id=int(data["frame_id"]),
            timestamp_ns=None if timestamp_ns is None else int(timestamp_ns),
            found=bool(data["found"]),
            x=int(data["x"]),
            y=int(data["y"]),
            width=int(data["width"]),
            height=int(data["height"]),
            locked=bool(data.get("locked", False)),
            lock_found_frames=int(data.get("lock_found_frames", 0)),
            lock_missing_frames=int(data.get("lock_missing_frames", 0)),
        )
    raise ValueError(f"unsupported telemetry message type: {message_type!r}")

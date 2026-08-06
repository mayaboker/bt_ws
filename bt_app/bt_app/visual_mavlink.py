"""Versioned red-detection telemetry carried in MAVLink V2_EXTENSION."""

from __future__ import annotations

import struct
from typing import Any, Mapping

import msgpack


V2_EXTENSION_RED_DETECTION_MESSAGE_TYPE = 2
RED_DETECTION_PROTOCOL_VERSION = 1
V2_EXTENSION_PAYLOAD_SIZE = 249
_ENVELOPE_FORMAT = "<BH"
_ENVELOPE_SIZE = struct.calcsize(_ENVELOPE_FORMAT)
MAX_MESSAGEPACK_SIZE = V2_EXTENSION_PAYLOAD_SIZE - _ENVELOPE_SIZE

RED_DETECTION_FIELDS = (
    "type",
    "frame_id",
    "timestamp_ns",
    "found",
    "x",
    "y",
    "width",
    "height",
    "locked",
    "lock_found_frames",
    "lock_missing_frames",
)


class VisualMavlinkCodecError(ValueError):
    """Raised when visual MAVLink telemetry violates the wire contract."""


def encode_red_detection(data: Mapping[str, Any]) -> bytes:
    normalized = _validate_red_detection(data)
    packed = msgpack.packb(normalized, use_bin_type=True)
    if len(packed) > MAX_MESSAGEPACK_SIZE:
        raise VisualMavlinkCodecError(
            f"red-detection MessagePack is {len(packed)} bytes; "
            f"maximum is {MAX_MESSAGEPACK_SIZE}"
        )
    envelope = struct.pack(
        _ENVELOPE_FORMAT,
        RED_DETECTION_PROTOCOL_VERSION,
        len(packed),
    )
    return (envelope + packed).ljust(V2_EXTENSION_PAYLOAD_SIZE, b"\x00")


def decode_red_detection(payload: bytes | bytearray) -> dict[str, Any]:
    raw = bytes(payload)
    if len(raw) < _ENVELOPE_SIZE:
        raise VisualMavlinkCodecError("red-detection envelope is truncated")
    version, packed_length = struct.unpack_from(_ENVELOPE_FORMAT, raw)
    if version != RED_DETECTION_PROTOCOL_VERSION:
        raise VisualMavlinkCodecError(
            f"unsupported red-detection protocol version {version}"
        )
    if packed_length > MAX_MESSAGEPACK_SIZE:
        raise VisualMavlinkCodecError(
            f"red-detection payload length {packed_length} exceeds "
            f"{MAX_MESSAGEPACK_SIZE}"
        )
    end = _ENVELOPE_SIZE + packed_length
    if end > len(raw):
        raise VisualMavlinkCodecError("red-detection MessagePack is truncated")
    try:
        data = msgpack.unpackb(
            raw[_ENVELOPE_SIZE:end],
            raw=False,
            strict_map_key=False,
        )
    except (ValueError, TypeError, msgpack.exceptions.UnpackException) as exc:
        raise VisualMavlinkCodecError(f"invalid red-detection MessagePack: {exc}") from exc
    if not isinstance(data, dict):
        raise VisualMavlinkCodecError("red-detection MessagePack must be a map")
    return _validate_red_detection(data)


def _validate_red_detection(data: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in RED_DETECTION_FIELDS if field not in data]
    if missing:
        raise VisualMavlinkCodecError(
            "red-detection fields are missing: " + ", ".join(missing)
        )
    if data["type"] != "red-detection":
        raise VisualMavlinkCodecError("message type must be 'red-detection'")
    if not isinstance(data["found"], bool) or not isinstance(data["locked"], bool):
        raise VisualMavlinkCodecError("found and locked must be booleans")
    integer_fields = (
        "frame_id",
        "x",
        "y",
        "width",
        "height",
        "lock_found_frames",
        "lock_missing_frames",
    )
    if any(
        isinstance(data[field], bool) or not isinstance(data[field], int)
        for field in integer_fields
    ):
        raise VisualMavlinkCodecError("red-detection numeric fields must be integers")
    timestamp_ns = data["timestamp_ns"]
    if timestamp_ns is not None and (
        isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int)
    ):
        raise VisualMavlinkCodecError("timestamp_ns must be an integer or null")
    return {field: data[field] for field in RED_DETECTION_FIELDS}

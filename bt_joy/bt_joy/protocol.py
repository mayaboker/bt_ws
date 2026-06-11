"""UDP wire protocol for joystick channel and keepalive frames."""

from __future__ import annotations

import struct
import time
import zlib

MAGIC = b"BTJY"
KEEPALIVE_REQUEST_MAGIC = b"BTKA"
KEEPALIVE_RESPONSE_MAGIC = b"BTKR"
VERSION = 1
HEADER_FORMAT = "<4sBIQB"
KEEPALIVE_REQUEST_FORMAT = "<4sBIQ"
KEEPALIVE_RESPONSE_FORMAT = "<4sBIQQQ"
CRC_FORMAT = "<I"


def timestamp_us() -> int:
    return time.time_ns() // 1000


def pack_frame(channels: list[int], sequence: int, timestamp: int | None = None) -> bytes:
    """Pack channels as a timestamped binary frame with a CRC32 trailer.

    Layout:
    - magic: 4 bytes, "BTJY"
    - version: uint8
    - sequence: uint32
    - timestamp_us: uint64
    - channel_count: uint8
    - channels: uint16[channel_count]
    - crc32: uint32 over all previous bytes
    """
    if len(channels) > 255:
        raise ValueError("A frame can contain at most 255 channels")

    sent_at = timestamp_us() if timestamp is None else timestamp
    header = struct.pack(HEADER_FORMAT, MAGIC, VERSION, sequence, sent_at, len(channels))
    payload = struct.pack(f"<{len(channels)}H", *[_clamp_u16(value) for value in channels])
    body = header + payload
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(CRC_FORMAT, crc)


def pack_keepalive_request(sequence: int, timestamp: int | None = None) -> bytes:
    sent_at = timestamp_us() if timestamp is None else timestamp
    body = struct.pack(KEEPALIVE_REQUEST_FORMAT, KEEPALIVE_REQUEST_MAGIC, VERSION, sequence, sent_at)
    return _append_crc(body)


def unpack_keepalive_request(frame: bytes) -> tuple[int, int]:
    body = _validate_body(frame)
    expected_size = struct.calcsize(KEEPALIVE_REQUEST_FORMAT)
    if len(body) != expected_size:
        raise ValueError("Keepalive request size mismatch")

    magic, version, sequence, sent_at = struct.unpack(KEEPALIVE_REQUEST_FORMAT, body)
    _validate_magic_and_version(magic, KEEPALIVE_REQUEST_MAGIC, version)
    return sequence, sent_at


def pack_keepalive_response(
    sequence: int,
    client_sent_at: int,
    server_received_at: int,
) -> bytes:
    delay_us = max(0, server_received_at - client_sent_at)
    body = struct.pack(
        KEEPALIVE_RESPONSE_FORMAT,
        KEEPALIVE_RESPONSE_MAGIC,
        VERSION,
        sequence,
        client_sent_at,
        server_received_at,
        delay_us,
    )
    return _append_crc(body)


def unpack_keepalive_response(frame: bytes) -> tuple[int, int, int, int]:
    body = _validate_body(frame)
    expected_size = struct.calcsize(KEEPALIVE_RESPONSE_FORMAT)
    if len(body) != expected_size:
        raise ValueError("Keepalive response size mismatch")

    magic, version, sequence, client_sent_at, server_received_at, delay_us = struct.unpack(
        KEEPALIVE_RESPONSE_FORMAT, body
    )
    _validate_magic_and_version(magic, KEEPALIVE_RESPONSE_MAGIC, version)
    return sequence, client_sent_at, server_received_at, delay_us


def is_keepalive_request(frame: bytes) -> bool:
    return frame.startswith(KEEPALIVE_REQUEST_MAGIC)


def is_keepalive_response(frame: bytes) -> bool:
    return frame.startswith(KEEPALIVE_RESPONSE_MAGIC)


def unpack_frame(frame: bytes) -> tuple[int, int, list[int]]:
    body = _validate_body(frame)
    header_size = struct.calcsize(HEADER_FORMAT)

    magic, version, sequence, sent_at, channel_count = struct.unpack(
        HEADER_FORMAT, body[:header_size]
    )
    _validate_magic_and_version(magic, MAGIC, version)

    expected_size = header_size + channel_count * 2
    if len(body) != expected_size:
        raise ValueError("Frame channel payload size mismatch")

    channels = list(struct.unpack(f"<{channel_count}H", body[header_size:]))
    return sequence, sent_at, channels


def _append_crc(body: bytes) -> bytes:
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return body + struct.pack(CRC_FORMAT, crc)


def _validate_body(frame: bytes) -> bytes:
    crc_size = struct.calcsize(CRC_FORMAT)
    if len(frame) < crc_size:
        raise ValueError("Frame is too short")

    expected_crc = struct.unpack(CRC_FORMAT, frame[-crc_size:])[0]
    body = frame[:-crc_size]
    actual_crc = zlib.crc32(body) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise ValueError("Frame CRC mismatch")
    return body


def _validate_magic_and_version(magic: bytes, expected_magic: bytes, version: int) -> None:
    if magic != expected_magic:
        raise ValueError("Frame magic mismatch")
    if version != VERSION:
        raise ValueError(f"Unsupported frame version: {version}")


def _clamp_u16(value: int) -> int:
    return max(0, min(65535, int(value)))

#!/usr/bin/env python3

from __future__ import annotations

from collections.abc import Iterator


USER_DATA_UNREGISTERED = 5
H264_SEI_NAL_TYPE = 6
BT_SEI_UUID = b"BTGSTSEI01234567"


def make_user_data_unregistered_sei(payload: bytes, uuid: bytes = BT_SEI_UUID) -> bytes:
    if len(uuid) != 16:
        raise ValueError("H.264 user_data_unregistered SEI UUID must be 16 bytes")

    sei_payload = uuid + payload
    rbsp = (
        _encode_sei_value(USER_DATA_UNREGISTERED)
        + _encode_sei_value(len(sei_payload))
        + sei_payload
        + b"\x80"
    )

    return b"\x00\x00\x00\x01" + bytes([H264_SEI_NAL_TYPE]) + _escape_rbsp(rbsp)


def insert_sei_before_first_vcl(
    access_unit: bytes,
    payload: bytes,
    uuid: bytes = BT_SEI_UUID,
) -> bytes:
    sei_nal = make_user_data_unregistered_sei(payload, uuid)
    insert_at = _first_vcl_start(access_unit)

    if insert_at is None:
        return sei_nal + access_unit

    return access_unit[:insert_at] + sei_nal + access_unit[insert_at:]


def extract_user_data_unregistered(
    access_unit: bytes,
    uuid: bytes = BT_SEI_UUID,
) -> list[bytes]:
    payloads = []

    for _start, nal_header, nal_end in iter_annexb_nalus(access_unit):
        if access_unit[nal_header] & 0x1F != H264_SEI_NAL_TYPE:
            continue

        rbsp = _unescape_ebsp(access_unit[nal_header + 1 : nal_end])
        payloads.extend(_extract_matching_sei_payloads(rbsp, uuid))

    return payloads


def iter_annexb_nalus(data: bytes) -> Iterator[tuple[int, int, int]]:
    offset = 0

    while True:
        start = _find_start_code(data, offset)
        if start is None:
            return

        nal_header = start + _start_code_size(data, start)
        if nal_header >= len(data):
            return

        next_start = _find_start_code(data, nal_header + 1)
        nal_end = next_start if next_start is not None else len(data)
        yield start, nal_header, nal_end

        if next_start is None:
            return
        offset = next_start


def _first_vcl_start(data: bytes) -> int | None:
    for start, nal_header, _nal_end in iter_annexb_nalus(data):
        nal_type = data[nal_header] & 0x1F
        if 1 <= nal_type <= 5:
            return start
    return None


def _find_start_code(data: bytes, offset: int) -> int | None:
    three_byte = data.find(b"\x00\x00\x01", offset)
    four_byte = data.find(b"\x00\x00\x00\x01", offset)

    if three_byte == -1 and four_byte == -1:
        return None
    if three_byte == -1:
        return four_byte
    if four_byte == -1:
        return three_byte
    return min(three_byte, four_byte)


def _start_code_size(data: bytes, start: int) -> int:
    if data[start : start + 4] == b"\x00\x00\x00\x01":
        return 4
    return 3


def _encode_sei_value(value: int) -> bytes:
    chunks = bytearray()
    while value >= 255:
        chunks.append(255)
        value -= 255
    chunks.append(value)
    return bytes(chunks)


def _escape_rbsp(rbsp: bytes) -> bytes:
    escaped = bytearray()
    zero_count = 0

    for byte in rbsp:
        if zero_count >= 2 and byte <= 3:
            escaped.append(3)
            zero_count = 0

        escaped.append(byte)
        zero_count = zero_count + 1 if byte == 0 else 0

    return bytes(escaped)


def _unescape_ebsp(ebsp: bytes) -> bytes:
    rbsp = bytearray()
    zero_count = 0
    index = 0

    while index < len(ebsp):
        byte = ebsp[index]
        if zero_count >= 2 and byte == 3:
            index += 1
            zero_count = 0
            continue

        rbsp.append(byte)
        zero_count = zero_count + 1 if byte == 0 else 0
        index += 1

    return bytes(rbsp)


def _extract_matching_sei_payloads(rbsp: bytes, uuid: bytes) -> list[bytes]:
    payloads = []
    offset = 0

    while offset + 1 < len(rbsp):
        if rbsp[offset] == 0x80:
            break

        payload_type, offset = _read_sei_value(rbsp, offset)
        payload_size, offset = _read_sei_value(rbsp, offset)
        end = offset + payload_size
        if end > len(rbsp):
            break

        payload = rbsp[offset:end]
        if (
            payload_type == USER_DATA_UNREGISTERED
            and len(payload) >= 16
            and payload[:16] == uuid
        ):
            payloads.append(payload[16:])

        offset = end

    return payloads


def _read_sei_value(rbsp: bytes, offset: int) -> tuple[int, int]:
    value = 0

    while offset < len(rbsp):
        byte = rbsp[offset]
        offset += 1
        value += byte
        if byte != 255:
            return value, offset

    return value, offset

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


MSP_V1_HEADER = b"$M"
MSP_V2_HEADER = b"$X"
MSP_REQUEST = b"<"
MSP_RESPONSE = b">"
MSP_ERROR = b"!"


class MspProtocolError(RuntimeError):
    pass


class ByteTransport(Protocol):
    def read(self, size: int, timeout: float) -> bytes:
        ...

    def write(self, data: bytes) -> None:
        ...


@dataclass(frozen=True)
class MspFrame:
    command: int
    payload: bytes = b""
    direction: bytes = MSP_RESPONSE
    version: int = 1

    @property
    def is_error(self) -> bool:
        return self.direction == MSP_ERROR


class MspCodec:
    def encode_request(
        self,
        command: int,
        payload: bytes = b"",
        version: int | None = None,
    ) -> bytes:
        if version is None:
            version = 1 if command <= 255 and len(payload) <= 255 else 2

        if version == 1:
            return self.encode_v1(command, payload, MSP_REQUEST)

        if version == 2:
            return self.encode_v2(command, payload, MSP_REQUEST)

        raise ValueError(f"Unsupported MSP version: {version}")

    def encode_response(
        self,
        command: int,
        payload: bytes = b"",
        version: int = 1,
        error: bool = False,
    ) -> bytes:
        direction = MSP_ERROR if error else MSP_RESPONSE
        if version == 1:
            return self.encode_v1(command, payload, direction)
        if version == 2:
            return self.encode_v2(command, payload, direction)
        raise ValueError(f"Unsupported MSP version: {version}")

    def encode_v1(self, command: int, payload: bytes, direction: bytes) -> bytes:
        if not 0 <= command <= 255:
            raise ValueError("MSP v1 command must be 0..255")
        if len(payload) > 255:
            raise ValueError("MSP v1 payload must be <= 255 bytes")

        checksum = len(payload) ^ command
        for byte in payload:
            checksum ^= byte

        return MSP_V1_HEADER + direction + bytes([len(payload), command]) + payload + bytes([checksum])

    def encode_v2(self, command: int, payload: bytes, direction: bytes) -> bytes:
        if not 0 <= command <= 0xFFFF:
            raise ValueError("MSP v2 command must be 0..65535")
        if len(payload) > 0xFFFF:
            raise ValueError("MSP v2 payload must be <= 65535 bytes")

        flags = 0
        body = (
            bytes([flags])
            + command.to_bytes(2, "little")
            + len(payload).to_bytes(2, "little")
            + payload
        )
        checksum = self.crc8_dvb_s2(body)
        return MSP_V2_HEADER + direction + body + bytes([checksum])

    def read_frame(self, transport: ByteTransport, timeout: float = 0.5) -> MspFrame:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            remaining = max(0.001, deadline - time.monotonic())
            if transport.read(1, remaining) != b"$":
                continue

            version_byte = transport.read(1, max(0.001, deadline - time.monotonic()))
            if version_byte == b"M":
                return self._read_v1_after_header(transport, deadline)
            if version_byte == b"X":
                return self._read_v2_after_header(transport, deadline)

        raise TimeoutError("No MSP frame received")

    def _read_v1_after_header(
        self,
        transport: ByteTransport,
        deadline: float,
    ) -> MspFrame:
        direction = self._read_exact(transport, 1, deadline)
        if direction not in (MSP_REQUEST, MSP_RESPONSE, MSP_ERROR):
            raise MspProtocolError(f"Invalid MSP v1 direction: {direction!r}")

        size = self._read_exact(transport, 1, deadline)[0]
        command = self._read_exact(transport, 1, deadline)[0]
        payload = self._read_exact(transport, size, deadline)
        received_checksum = self._read_exact(transport, 1, deadline)[0]

        checksum = size ^ command
        for byte in payload:
            checksum ^= byte

        if checksum != received_checksum:
            raise MspProtocolError(
                f"Bad MSP v1 checksum: got 0x{received_checksum:02x}, "
                f"expected 0x{checksum:02x}"
            )

        return MspFrame(command=command, payload=payload, direction=direction, version=1)

    def _read_v2_after_header(
        self,
        transport: ByteTransport,
        deadline: float,
    ) -> MspFrame:
        direction = self._read_exact(transport, 1, deadline)
        if direction not in (MSP_REQUEST, MSP_RESPONSE, MSP_ERROR):
            raise MspProtocolError(f"Invalid MSP v2 direction: {direction!r}")

        flags = self._read_exact(transport, 1, deadline)
        command_bytes = self._read_exact(transport, 2, deadline)
        size_bytes = self._read_exact(transport, 2, deadline)
        size = int.from_bytes(size_bytes, "little")
        payload = self._read_exact(transport, size, deadline)
        received_checksum = self._read_exact(transport, 1, deadline)[0]

        crc_data = flags + command_bytes + size_bytes + payload
        checksum = self.crc8_dvb_s2(crc_data)
        if checksum != received_checksum:
            raise MspProtocolError(
                f"Bad MSP v2 checksum: got 0x{received_checksum:02x}, "
                f"expected 0x{checksum:02x}"
            )

        return MspFrame(
            command=int.from_bytes(command_bytes, "little"),
            payload=payload,
            direction=direction,
            version=2,
        )

    def _read_exact(
        self,
        transport: ByteTransport,
        size: int,
        deadline: float,
    ) -> bytes:
        data = b""
        while len(data) < size:
            remaining = max(0.001, deadline - time.monotonic())
            data += transport.read(size - len(data), remaining)

        return data

    def crc8_dvb_s2(self, data: bytes) -> int:
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0xD5) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

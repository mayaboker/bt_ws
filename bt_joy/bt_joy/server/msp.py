"""Standalone MSP protocol helpers for bt_joy."""

from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

MSP_V1_HEADER = b"$M"
MSP_REQUEST = b"<"
MSP_RESPONSE = b">"
MSP_ERROR = b"!"

MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_BOARD_INFO = 4
MSP_BUILD_INFO = 5
MSP_STATUS = 101
MSP_RC = 105
MSP_ALTITUDE = 109
MSP_STATUS_EX = 150
MSP_SET_RAW_RC = 200

RC_CHANNEL_COUNT = 8
RC_MID = 1500
ARMING_DISABLED_FLAG_NAMES = (
    "NO_GYRO",
    "FAILSAFE",
    "RX_FAILSAFE",
    "NOT_DISARMED",
    "BOXFAILSAFE",
    "RUNAWAY_TAKEOFF",
    "CRASH_DETECTED",
    "THROTTLE",
    "ANGLE",
    "BOOT_GRACE_TIME",
    "NOPREARM",
    "LOAD",
    "CALIBRATING",
    "CLI",
    "CMS_MENU",
    "BST",
    "MSP",
    "PARALYZE",
    "GPS",
    "RESC",
    "DSHOT_TELEM",
    "REBOOT_REQUIRED",
    "DSHOT_BITBANG",
    "ACC_CALIBRATION",
    "MOTOR_PROTOCOL",
    "CRASHFLIP",
    "ALTHOLD",
    "POSHOLD",
    "ARM_SWITCH",
)


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

    @property
    def is_error(self) -> bool:
        return self.direction == MSP_ERROR


@dataclass(frozen=True)
class MspStatus:
    cycle_time_us: int
    i2c_errors: int
    sensors_mask: int
    box_mode_flags: int
    config_profile: int | None = None
    average_system_load_percent: int | None = None
    pid_profile_count: int | None = None
    control_rate_profile: int | None = None
    arming_disabled_flags_count: int | None = None
    arming_disabled_flags: int | None = None
    arming_disabled_flag_names: tuple[str, ...] = ()
    config_state_flags: int | None = None
    cpu_temp_celsius: int | None = None


@dataclass(frozen=True)
class MspAltitude:
    altitude_m: float
    vertical_speed_m_s: float


@dataclass(frozen=True)
class MspApiVersion:
    protocol: int
    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor} protocol={self.protocol}"


@dataclass(frozen=True)
class MspFcVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class MspBuildInfo:
    date: str | None
    time: str | None
    revision: str | None
    raw: bytes


@dataclass(frozen=True)
class MspBoardInfo:
    identifier: str | None
    hardware_revision: int | None
    raw: bytes


class MspCodec:
    def encode_request(self, command: int, payload: bytes = b"") -> bytes:
        return self.encode_v1(command, payload, MSP_REQUEST)

    def encode_v1(self, command: int, payload: bytes, direction: bytes) -> bytes:
        if not 0 <= command <= 255:
            raise ValueError("MSP v1 command must be 0..255")
        if len(payload) > 255:
            raise ValueError("MSP v1 payload must be <= 255 bytes")

        checksum = len(payload) ^ command
        for byte in payload:
            checksum ^= byte

        return MSP_V1_HEADER + direction + bytes([len(payload), command]) + payload + bytes([checksum])

    def read_frame(self, transport: ByteTransport, timeout: float = 0.5) -> MspFrame:
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            remaining = max(0.001, deadline - time.monotonic())
            if transport.read(1, remaining) != b"$":
                continue
            if transport.read(1, max(0.001, deadline - time.monotonic())) == b"M":
                return self._read_v1_after_header(transport, deadline)

        raise TimeoutError("No MSP frame received")

    def _read_v1_after_header(self, transport: ByteTransport, deadline: float) -> MspFrame:
        direction = self._read_exact(transport, 1, deadline)
        if direction not in (MSP_REQUEST, MSP_RESPONSE, MSP_ERROR):
            raise MspProtocolError(f"Invalid MSP direction: {direction!r}")

        size = self._read_exact(transport, 1, deadline)[0]
        command = self._read_exact(transport, 1, deadline)[0]
        payload = self._read_exact(transport, size, deadline)
        received_checksum = self._read_exact(transport, 1, deadline)[0]

        checksum = size ^ command
        for byte in payload:
            checksum ^= byte

        if checksum != received_checksum:
            raise MspProtocolError(
                f"Bad MSP checksum: got 0x{received_checksum:02x}, expected 0x{checksum:02x}"
            )

        return MspFrame(command=command, payload=payload, direction=direction)

    def _read_exact(self, transport: ByteTransport, size: int, deadline: float) -> bytes:
        data = b""
        while len(data) < size:
            remaining = max(0.001, deadline - time.monotonic())
            data += transport.read(size - len(data), remaining)
        return data


class TcpMspTransport:
    def __init__(self, host: str, port: int, connect_timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self._socket: socket.socket | None = None

    def __enter__(self) -> "TcpMspTransport":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def open(self) -> None:
        self._socket = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def write(self, data: bytes) -> None:
        self._require_socket().sendall(data)

    def read(self, size: int, timeout: float) -> bytes:
        sock = self._require_socket()
        sock.settimeout(timeout)
        try:
            data = sock.recv(size)
        except socket.timeout as exc:
            raise TimeoutError(f"Timeout while reading {size} TCP bytes") from exc
        if not data:
            raise ConnectionError("MSP TCP socket closed")
        return data

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("MSP TCP transport is not open")
        return self._socket


class SerialMspTransport:
    def __init__(self, device: str, baudrate: int = 115200) -> None:
        self.device = device
        self.baudrate = baudrate
        self._serial = None

    def __enter__(self) -> "SerialMspTransport":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def open(self) -> None:
        import serial

        self._serial = serial.Serial(
            port=self.device,
            baudrate=self.baudrate,
            timeout=0,
            write_timeout=1,
        )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
            self._serial = None

    def write(self, data: bytes) -> None:
        serial_port = self._require_serial()
        serial_port.write(data)
        serial_port.flush()

    def read(self, size: int, timeout: float) -> bytes:
        serial_port = self._require_serial()
        serial_port.timeout = timeout
        data = serial_port.read(size)
        if len(data) != size:
            raise TimeoutError(f"Timeout while reading {size} serial bytes")
        return data

    def _require_serial(self):
        if self._serial is None:
            raise RuntimeError("MSP serial transport is not open")
        return self._serial


class MspClient:
    def __init__(self, transport: ByteTransport, codec: MspCodec | None = None) -> None:
        self.transport = transport
        self.codec = codec or MspCodec()

    def send_raw_rc(self, channels: Sequence[int]) -> None:
        rc_channels = normalize_rc_channels(channels)
        payload = struct.pack("<8H", *rc_channels)
        self.transport.write(self.codec.encode_request(MSP_SET_RAW_RC, payload))

    def read_status(self, timeout: float = 0.5) -> MspStatus:
        return parse_status_ex(self.read_command(MSP_STATUS_EX, timeout=timeout))

    def read_rc(self, timeout: float = 0.5) -> list[int]:
        return unpack_u16_list(self.read_command(MSP_RC, timeout=timeout))

    def read_altitude(self, timeout: float = 0.5) -> MspAltitude:
        return parse_altitude(self.read_command(MSP_ALTITUDE, timeout=timeout))

    def read_version(self, timeout: float = 0.5) -> bytes:
        """Request MSP_FC_VERSION and return raw payload bytes.

        The payload format can vary by firmware; callers should parse
        the returned bytes as needed. This method returns the raw
        payload on success or raises on timeout/error.
        """
        return self.read_command(MSP_FC_VERSION, timeout=timeout)

    def read_api_version(self, timeout: float = 0.5) -> MspApiVersion:
        return parse_api_version(self.read_command(MSP_API_VERSION, timeout=timeout))

    def read_fc_variant(self, timeout: float = 0.5) -> str:
        return parse_ascii(self.read_command(MSP_FC_VARIANT, timeout=timeout))

    def read_fc_version(self, timeout: float = 0.5) -> MspFcVersion:
        return parse_fc_version(self.read_command(MSP_FC_VERSION, timeout=timeout))

    def read_board_info(self, timeout: float = 0.5) -> MspBoardInfo:
        return parse_board_info(self.read_command(MSP_BOARD_INFO, timeout=timeout))

    def read_build_info(self, timeout: float = 0.5) -> MspBuildInfo:
        return parse_build_info(self.read_command(MSP_BUILD_INFO, timeout=timeout))

    def read_command(self, command: int, timeout: float = 0.5) -> bytes:
        self.transport.write(self.codec.encode_request(command))
        while True:
            frame = self.codec.read_frame(self.transport, timeout=timeout)
            if frame.command != command:
                continue
            if frame.is_error:
                raise MspProtocolError(f"MSP error response for command {command}")
            return frame.payload


def normalize_rc_channels(channels: Sequence[int]) -> list[int]:
    normalized = [max(0, min(65535, int(channel))) for channel in channels[:RC_CHANNEL_COUNT]]
    while len(normalized) < RC_CHANNEL_COUNT:
        normalized.append(RC_MID)
    return normalized


def unpack_u16_list(payload: bytes) -> list[int]:
    count = len(payload) // 2
    return list(struct.unpack_from("<" + "H" * count, payload))


def parse_altitude(payload: bytes) -> MspAltitude:
    if len(payload) < 6:
        raise ValueError(f"MSP_ALTITUDE payload too short: {len(payload)} bytes")
    altitude_cm, vertical_speed_cm_s = struct.unpack_from("<ih", payload)
    return MspAltitude(
        altitude_m=altitude_cm / 100.0,
        vertical_speed_m_s=vertical_speed_cm_s / 100.0,
    )


def parse_status(payload: bytes) -> MspStatus:
    if len(payload) < 10:
        raise ValueError(f"MSP_STATUS payload too short: {len(payload)} bytes")

    cycle_time_us, i2c_errors, sensors_mask = struct.unpack_from("<HHH", payload, 0)
    box_mode_flags = struct.unpack_from("<I", payload, 6)[0]
    config_profile = payload[10] if len(payload) > 10 else None
    return MspStatus(
        cycle_time_us=cycle_time_us,
        i2c_errors=i2c_errors,
        sensors_mask=sensors_mask,
        box_mode_flags=box_mode_flags,
        config_profile=config_profile,
    )


def parse_status_ex(payload: bytes) -> MspStatus:
    if len(payload) < 16:
        raise ValueError(f"MSP_STATUS_EX payload too short: {len(payload)} bytes")

    cycle_time_us, i2c_errors, sensors_mask = struct.unpack_from("<HHH", payload, 0)
    box_mode_flags = struct.unpack_from("<I", payload, 6)[0]
    config_profile = payload[10]
    average_system_load_percent = struct.unpack_from("<H", payload, 11)[0]
    pid_profile_count = payload[13]
    control_rate_profile = payload[14]
    flight_mode_extra_byte_count = payload[15] & 0x0F
    arming_flags_offset = 16 + flight_mode_extra_byte_count
    if len(payload) < arming_flags_offset + 5:
        raise ValueError(f"MSP_STATUS_EX arming flags payload too short: {len(payload)} bytes")

    arming_disabled_flags_count = payload[arming_flags_offset]
    arming_disabled_flags = struct.unpack_from("<I", payload, arming_flags_offset + 1)[0]
    config_state_flags_offset = arming_flags_offset + 5
    config_state_flags = payload[config_state_flags_offset] if len(payload) > config_state_flags_offset else None
    cpu_temp_offset = config_state_flags_offset + 1
    cpu_temp_celsius = (
        struct.unpack_from("<H", payload, cpu_temp_offset)[0] if len(payload) >= cpu_temp_offset + 2 else None
    )

    return MspStatus(
        cycle_time_us=cycle_time_us,
        i2c_errors=i2c_errors,
        sensors_mask=sensors_mask,
        box_mode_flags=box_mode_flags,
        config_profile=config_profile,
        average_system_load_percent=average_system_load_percent,
        pid_profile_count=pid_profile_count,
        control_rate_profile=control_rate_profile,
        arming_disabled_flags_count=arming_disabled_flags_count,
        arming_disabled_flags=arming_disabled_flags,
        arming_disabled_flag_names=decode_arming_disabled_flags(arming_disabled_flags),
        config_state_flags=config_state_flags,
        cpu_temp_celsius=cpu_temp_celsius,
    )


def decode_arming_disabled_flags(flags: int) -> tuple[str, ...]:
    return tuple(
        name for bit, name in enumerate(ARMING_DISABLED_FLAG_NAMES) if flags & (1 << bit)
    )


def parse_api_version(payload: bytes) -> MspApiVersion:
    if len(payload) < 3:
        raise ValueError(f"MSP_API_VERSION payload too short: {len(payload)} bytes")
    return MspApiVersion(protocol=payload[0], major=payload[1], minor=payload[2])


def parse_fc_version(payload: bytes) -> MspFcVersion:
    if len(payload) < 3:
        raise ValueError(f"MSP_FC_VERSION payload too short: {len(payload)} bytes")
    return MspFcVersion(major=payload[0], minor=payload[1], patch=payload[2])


def parse_board_info(payload: bytes) -> MspBoardInfo:
    identifier = parse_ascii(payload[:4]) if len(payload) >= 4 else None
    hardware_revision = struct.unpack_from("<H", payload, 4)[0] if len(payload) >= 6 else None
    return MspBoardInfo(identifier=identifier, hardware_revision=hardware_revision, raw=payload)


def parse_build_info(payload: bytes) -> MspBuildInfo:
    date = parse_ascii(payload[:11]) if len(payload) >= 11 else None
    build_time = parse_ascii(payload[11:19]) if len(payload) >= 19 else None
    revision = parse_ascii(payload[19:]) if len(payload) > 19 else None
    return MspBuildInfo(date=date, time=build_time, revision=revision, raw=payload)


def parse_ascii(payload: bytes) -> str:
    return payload.rstrip(b"\x00").decode("ascii", errors="replace")

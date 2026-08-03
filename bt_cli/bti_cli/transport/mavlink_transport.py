from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import time
from typing import Any, Callable

from pymavlink import mavutil


class MavlinkTransportError(RuntimeError):
    """Raised when a MAVLink parameter operation is rejected."""


class MavlinkTransportTimeout(TimeoutError):
    """Raised when the remote component does not complete an operation."""


@dataclass(frozen=True)
class ParameterValue:
    name: str
    value: int | float | bool
    parameter_type: int
    count: int
    index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "type": self.parameter_type,
            "count": self.count,
            "index": self.index,
        }


class MavlinkParameterTransport:
    def __init__(
        self,
        endpoint: tuple[str, int] = ("127.0.0.1", 14551),
        *,
        target_system: int = 1,
        target_component: int = 1,
        timeout_s: float = 3.0,
        retries: int = 3,
    ) -> None:
        self.endpoint = endpoint
        self.target_system = target_system
        self.target_component = target_component
        self.timeout_s = timeout_s
        self.retries = retries
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.bind(("0.0.0.0", 0))
        self._socket.settimeout(min(timeout_s, 0.2))
        self._mav = mavutil.mavlink.MAVLink(None, srcSystem=255, srcComponent=190)
        self._parser = mavutil.mavlink.MAVLink(None)
        self._parser.robust_parsing = True

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> "MavlinkParameterTransport":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def list(self) -> list[ParameterValue]:
        values: dict[int, ParameterValue] = {}
        expected_count: int | None = None
        for _ in range(self.retries):
            if expected_count is None:
                request = self._mav.param_request_list_encode(
                    self.target_system,
                    self.target_component,
                )
                self._send(request)
            else:
                for index in range(expected_count):
                    if index not in values:
                        self._send(self._request_read(index=index))

            deadline = time.monotonic() + self.timeout_s
            while time.monotonic() < deadline:
                message = self._receive_until(
                    deadline, lambda item: item.get_type() == "PARAM_VALUE"
                )
                if message is None:
                    break
                value = self._decode_parameter(message)
                expected_count = value.count
                values[value.index] = value
                if len(values) == expected_count:
                    return [values[index] for index in range(expected_count)]

        raise MavlinkTransportTimeout(
            f"Received {len(values)} of {expected_count or 0} parameters from "
            f"{self.endpoint[0]}:{self.endpoint[1]}"
        )

    def get(self, name: str) -> ParameterValue:
        for _ in range(self.retries):
            self._send(self._request_read(name=name))
            deadline = time.monotonic() + self.timeout_s
            message = self._receive_until(
                deadline,
                lambda item: (
                    item.get_type() == "PARAM_VALUE"
                    and self._decode_name(item.param_id) == name
                ),
            )
            if message is not None:
                return self._decode_parameter(message)
        raise MavlinkTransportTimeout(f"No value received for parameter {name}")

    def set(self, name: str, raw_value: str) -> ParameterValue:
        current = self.get(name)
        requested = self._parse_cli_value(raw_value, current.parameter_type)
        encoded = self._encode_value(requested, current.parameter_type)
        wire_requested = self._decode_value(encoded, current.parameter_type)
        request = self._mav.param_set_encode(
            self.target_system,
            self.target_component,
            name.encode("ascii"),
            encoded,
            current.parameter_type,
        )
        for _ in range(self.retries):
            self._send(request)
            deadline = time.monotonic() + self.timeout_s
            message = self._receive_until(
                deadline,
                lambda item: (
                    item.get_type() == "PARAM_VALUE"
                    and self._decode_name(item.param_id) == name
                ),
            )
            if message is None:
                continue
            updated = self._decode_parameter(message)
            if updated.value != wire_requested:
                raise MavlinkTransportError(
                    f"Parameter {name} rejected {wire_requested!r}; current value is "
                    f"{updated.value!r}"
                )
            return updated
        raise MavlinkTransportTimeout(f"No acknowledgement received for {name}")

    def save(self) -> None:
        request = self._mav.command_long_encode(
            self.target_system,
            self.target_component,
            mavutil.mavlink.MAV_CMD_PREFLIGHT_STORAGE,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        for _ in range(self.retries):
            self._send(request)
            deadline = time.monotonic() + self.timeout_s
            message = self._receive_until(
                deadline,
                lambda item: (
                    item.get_type() == "COMMAND_ACK"
                    and int(item.command) == mavutil.mavlink.MAV_CMD_PREFLIGHT_STORAGE
                ),
            )
            if message is None:
                continue
            if int(message.result) != mavutil.mavlink.MAV_RESULT_ACCEPTED:
                raise MavlinkTransportError(
                    f"Parameter save rejected with MAV_RESULT {message.result}"
                )
            return
        raise MavlinkTransportTimeout("No acknowledgement received for parameter save")

    def _request_read(self, *, name: str = "", index: int = -1) -> Any:
        return self._mav.param_request_read_encode(
            self.target_system,
            self.target_component,
            name.encode("ascii"),
            index,
        )

    def _send(self, message: Any) -> None:
        self._socket.sendto(message.pack(self._mav), self.endpoint)

    def _receive_until(
        self,
        deadline: float,
        predicate: Callable[[Any], bool],
    ) -> Any | None:
        while time.monotonic() < deadline:
            try:
                payload, _ = self._socket.recvfrom(2048)
            except socket.timeout:
                continue
            try:
                for byte in payload:
                    message = self._parser.parse_char(bytes([byte]))
                    if message is not None and predicate(message):
                        return message
            except mavutil.mavlink.MAVError:
                continue
        return None

    def _decode_parameter(self, message: Any) -> ParameterValue:
        return ParameterValue(
            name=self._decode_name(message.param_id),
            value=self._decode_value(message.param_value, int(message.param_type)),
            parameter_type=int(message.param_type),
            count=int(message.param_count),
            index=int(message.param_index),
        )

    @staticmethod
    def _decode_name(value: str | bytes) -> str:
        if isinstance(value, bytes):
            return value.split(b"\0", 1)[0].decode("ascii", errors="replace")
        return value.split("\0", 1)[0]

    @staticmethod
    def _decode_value(value: float, parameter_type: int) -> int | float | bool:
        if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_REAL32:
            return float(value)
        raw = struct.pack("<f", float(value))
        if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_INT32:
            return struct.unpack("<i", raw)[0]
        if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_UINT8:
            return bool(struct.unpack("<I", raw)[0])
        raise MavlinkTransportError(
            f"Unsupported MAVLink parameter type {parameter_type}"
        )

    @staticmethod
    def _encode_value(value: int | float | bool, parameter_type: int) -> float:
        if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_REAL32:
            return float(value)
        if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_INT32:
            return struct.unpack("<f", struct.pack("<i", int(value)))[0]
        if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_UINT8:
            return struct.unpack("<f", struct.pack("<I", int(bool(value))))[0]
        raise MavlinkTransportError(
            f"Unsupported MAVLink parameter type {parameter_type}"
        )

    @staticmethod
    def _parse_cli_value(raw_value: str, parameter_type: int) -> int | float | bool:
        try:
            if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_REAL32:
                return float(raw_value)
            if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_INT32:
                return int(raw_value, 0)
            if parameter_type == mavutil.mavlink.MAV_PARAM_TYPE_UINT8:
                normalized = raw_value.strip().lower()
                if normalized in {"1", "true"}:
                    return True
                if normalized in {"0", "false"}:
                    return False
        except ValueError as exc:
            raise MavlinkTransportError(
                f"Invalid parameter value: {raw_value}"
            ) from exc
        raise MavlinkTransportError(f"Unsupported parameter value: {raw_value}")

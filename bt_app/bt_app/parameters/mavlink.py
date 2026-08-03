from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any, Callable

from loguru import logger
from pymavlink import mavutil

from bt_app.parameters.service import ParameterService


PARAMETER_STREAM_INTERVAL_S = 0.02
PREFLIGHT_STORAGE_WRITE = 1


@dataclass(frozen=True)
class MavlinkParameterResponse:
    message: Any
    destination: tuple[str, int]
    delay_s: float = 0.0


class MavlinkParameterProtocol:
    """Classic MAVLink parameter protocol backed by ``ParameterService``."""

    def __init__(
        self,
        *,
        service: ParameterService,
        mav: Any,
        system_id: int,
        component_id: int,
        gcs_addr: tuple[str, int],
        is_armed: Callable[[], bool],
    ) -> None:
        self._service = service
        self._mav = mav
        self._system_id = system_id
        self._component_id = component_id
        self._gcs_addr = gcs_addr
        self._is_armed = is_armed

    def handle(
        self,
        message: Any,
        source: tuple[str, int],
    ) -> list[MavlinkParameterResponse]:
        message_type = message.get_type()
        if message_type == "PARAM_REQUEST_LIST":
            return self._handle_list(message, source)
        if message_type == "PARAM_REQUEST_READ":
            return self._handle_read(message, source)
        if message_type == "PARAM_SET":
            return self._handle_set(message, source)
        if message_type == "COMMAND_LONG":
            return self._handle_command(message, source)
        return []

    def _handle_list(
        self,
        message: Any,
        source: tuple[str, int],
    ) -> list[MavlinkParameterResponse]:
        if not self._is_targeted(message):
            return []

        snapshot = self._service.snapshot()
        return [
            MavlinkParameterResponse(
                self._encode_value(snapshot, index),
                source,
                delay_s=index * PARAMETER_STREAM_INTERVAL_S,
            )
            for index in range(len(snapshot))
        ]

    def _handle_read(
        self,
        message: Any,
        source: tuple[str, int],
    ) -> list[MavlinkParameterResponse]:
        if not self._is_targeted(message):
            return []

        snapshot = self._service.snapshot()
        index = int(message.param_index)
        if index < 0:
            requested_name = self._decode_name(message.param_id)
            index = self._find_index(snapshot, requested_name)
        if index < 0 or index >= len(snapshot):
            logger.warning(
                "Unknown MAVLink parameter read: id={} index={}",
                self._decode_name(message.param_id),
                message.param_index,
            )
            return []
        return [MavlinkParameterResponse(self._encode_value(snapshot, index), source)]

    def _handle_set(
        self,
        message: Any,
        source: tuple[str, int],
    ) -> list[MavlinkParameterResponse]:
        if not self._is_targeted(message):
            return []

        name = self._decode_name(message.param_id)
        snapshot = self._service.snapshot()
        index = self._find_index(snapshot, name)
        if index < 0:
            logger.warning("Unknown MAVLink parameter set: {}", name)
            return [self._status_text(f"Unknown parameter: {name}", source)]

        expected_type = self._mavlink_type(snapshot[index][1])
        if int(message.param_type) != expected_type:
            logger.warning(
                "MAVLink parameter type mismatch for {}: expected={} received={}",
                name,
                expected_type,
                message.param_type,
            )
            return [
                MavlinkParameterResponse(self._encode_value(snapshot, index), source)
            ]

        try:
            requested_value = self._decode_value(
                message.param_value, snapshot[index][1]
            )
            self._service.set(name, requested_value)
        except (TypeError, ValueError) as exc:
            logger.warning("Rejected MAVLink parameter set {}: {}", name, exc)
        updated_snapshot = self._service.snapshot()
        updated_index = self._find_index(updated_snapshot, name)
        response_message = self._encode_value(updated_snapshot, updated_index)
        destinations = self._unique_destinations(source, self._gcs_addr)
        return [
            MavlinkParameterResponse(response_message, destination)
            for destination in destinations
        ]

    def _handle_command(
        self,
        message: Any,
        source: tuple[str, int],
    ) -> list[MavlinkParameterResponse]:
        if not self._is_targeted(message):
            return []

        command = int(message.command)
        if command == mavutil.mavlink.MAV_CMD_PREFLIGHT_STORAGE:
            return self._handle_storage_command(message, source)

        request_capabilities = getattr(
            mavutil.mavlink,
            "MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES",
            520,
        )
        requests_version = command == request_capabilities or (
            command == mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE
            and int(message.param1) == mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION
        )
        if not requests_version:
            return []

        return [
            MavlinkParameterResponse(
                self._command_ack(command, mavutil.mavlink.MAV_RESULT_ACCEPTED), source
            ),
            MavlinkParameterResponse(self._autopilot_version(), source),
        ]

    def _handle_storage_command(
        self,
        message: Any,
        source: tuple[str, int],
    ) -> list[MavlinkParameterResponse]:
        result = mavutil.mavlink.MAV_RESULT_UNSUPPORTED
        if int(message.param1) == PREFLIGHT_STORAGE_WRITE:
            if self._is_armed():
                result = mavutil.mavlink.MAV_RESULT_DENIED
            else:
                try:
                    self._service.save()
                except (OSError, RuntimeError) as exc:
                    logger.exception("Failed to persist MAVLink parameters: {}", exc)
                    result = mavutil.mavlink.MAV_RESULT_FAILED
                else:
                    result = mavutil.mavlink.MAV_RESULT_ACCEPTED
        return [
            MavlinkParameterResponse(
                self._command_ack(message.command, result),
                source,
            )
        ]

    def _encode_value(
        self,
        snapshot: tuple[tuple[str, str, Any], ...],
        index: int,
    ) -> Any:
        name, type_name, value = snapshot[index]
        return self._mav.param_value_encode(
            name.encode("ascii"),
            self._encode_wire_value(value, type_name),
            self._mavlink_type(type_name),
            len(snapshot),
            index,
        )

    def _encode_wire_value(self, value: Any, type_name: str) -> float:
        if type_name == "float":
            return float(value)
        if type_name == "int":
            return struct.unpack("<f", struct.pack("<i", int(value)))[0]
        if type_name == "bool":
            return struct.unpack("<f", struct.pack("<I", int(bool(value))))[0]
        raise ValueError(f"Unsupported MAVLink parameter type: {type_name}")

    def _decode_value(self, value: float, type_name: str) -> Any:
        if type_name == "float":
            return float(value)
        raw = struct.pack("<f", float(value))
        if type_name == "int":
            return struct.unpack("<i", raw)[0]
        if type_name == "bool":
            decoded = struct.unpack("<I", raw)[0]
            if decoded not in (0, 1):
                raise ValueError("Boolean parameter must be 0 or 1")
            return bool(decoded)
        raise ValueError(f"Unsupported MAVLink parameter type: {type_name}")

    @staticmethod
    def _decode_name(value: str | bytes) -> str:
        if isinstance(value, bytes):
            return value.split(b"\0", 1)[0].decode("ascii", errors="replace")
        return value.split("\0", 1)[0]

    @staticmethod
    def _find_index(
        snapshot: tuple[tuple[str, str, Any], ...],
        name: str,
    ) -> int:
        return next(
            (
                index
                for index, (candidate, _, _) in enumerate(snapshot)
                if candidate == name
            ),
            -1,
        )

    def _mavlink_type(self, type_name: str) -> int:
        if type_name == "float":
            return mavutil.mavlink.MAV_PARAM_TYPE_REAL32
        if type_name == "int":
            return mavutil.mavlink.MAV_PARAM_TYPE_INT32
        if type_name == "bool":
            return mavutil.mavlink.MAV_PARAM_TYPE_UINT8
        raise ValueError(f"Unsupported MAVLink parameter type: {type_name}")

    def _is_targeted(self, message: Any) -> bool:
        return int(message.target_system) in (0, self._system_id) and int(
            message.target_component
        ) in (0, self._component_id)

    def _command_ack(self, command: int, result: int) -> Any:
        return self._mav.command_ack_encode(int(command), int(result))

    def _autopilot_version(self) -> Any:
        return self._mav.autopilot_version_encode(
            mavutil.mavlink.MAV_PROTOCOL_CAPABILITY_PARAM_ENCODE_BYTEWISE,
            0,
            0,
            0,
            0,
            bytes(8),
            bytes(8),
            bytes(8),
            0,
            0,
            0,
        )

    def _status_text(
        self,
        text: str,
        source: tuple[str, int],
    ) -> MavlinkParameterResponse:
        message = self._mav.statustext_encode(
            mavutil.mavlink.MAV_SEVERITY_WARNING,
            text.encode("utf-8")[:50],
        )
        return MavlinkParameterResponse(message, source)

    @staticmethod
    def _unique_destinations(
        *destinations: tuple[str, int],
    ) -> tuple[tuple[str, int], ...]:
        return tuple(dict.fromkeys(destinations))

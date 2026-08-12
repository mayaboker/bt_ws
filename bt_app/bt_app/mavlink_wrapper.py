#!/usr/bin/env python3

import socket
import struct
import time
import math
from dataclasses import dataclass
from typing import Any, Callable, ClassVar, Mapping

from loguru import logger as log
from pymavlink import mavutil

from bt_app.common import MavSeverity
from bt_app.context import Context
from bt_app.parameters.mavlink import MavlinkParameterProtocol, MavlinkParameterResponse
from bt_app.parameters.service import ParameterService
from bt_app.scheduler import Command, CommandScheduler, ScheduledCommand, SchedulerContext
from bt_app.visual_mavlink import (
    V2_EXTENSION_RED_DETECTION_MESSAGE_TYPE,
    VisualMavlinkCodecError,
    encode_red_detection,
)


QOPENHD_ADDR = ("127.0.0.1", 14550)
LOCAL_ADDR = ("0.0.0.0", 14551)

SYS_ID = 1
COMP_ID = mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1
GLOBAL_POSITION_INT_INTERVAL_S = 0.5
ATTITUDE_INTERVAL_S = 0.5
SYS_STATUS_INTERVAL_S = 2.0
RC_CHANNELS_INTERVAL_S = 0.5
V2_EXTENSION_CHANNEL_STATUS_INTERVAL_S = 0.1
V2_EXTENSION_CHANNEL_STATUS_MESSAGE_TYPE = 1
V2_EXTENSION_CHANNEL_STATUS_VERSION = 1
V2_EXTENSION_CHANNEL_STATUS_COMMAND_ID = 1
V2_EXTENSION_CHANNEL_STATUS_FLAGS = 0
V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT = "<BBBH8H"
V2_EXTENSION_PAYLOAD_SIZE = 249
SAFE_DEFAULT_RC_CHANNELS = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)
UNKNOWN_GLOBAL_POSITION_HEADING = 65535
MAX_UINT16 = 65535
UNKNOWN_RSSI = 255
UNKNOWN_CURRENT_BATTERY = -1
UNKNOWN_BATTERY_REMAINING = -1


def make_base_mode(armed: bool) -> int:
    base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    if armed:
        base_mode |= mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    return base_mode


@dataclass
class HeartbeatCommand(Command):
    key: ClassVar[str | None] = "mavlink_heartbeat"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_heartbeat()


@dataclass
class GlobalPositionIntCommand(Command):
    key: ClassVar[str | None] = "mavlink_global_position_int"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_global_position_int()


@dataclass
class AttitudeCommand(Command):
    key: ClassVar[str | None] = "mavlink_attitude"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_attitude()


@dataclass
class SysStatusCommand(Command):
    key: ClassVar[str | None] = "mavlink_sys_status"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_sys_status()


@dataclass
class SendRcChannelsCommand(Command):
    key: ClassVar[str | None] = "mavlink_rc_channels"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_rc_channels()


@dataclass
class SendChannelStatusV2ExtensionCommand(Command):
    key: ClassVar[str | None] = "mavlink_v2_extension_channel_status"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_channel_status_v2_extension()


@dataclass
class SendRedDetectionV2ExtensionCommand(Command):
    key: ClassVar[str | None] = "mavlink_v2_extension_red_detection"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_latest_red_detection()


@dataclass
class NamedValueFloatCommand(Command):
    key: ClassVar[str | None] = "mavlink_named_value_float"
    service: "MavlinkService"
    named: str
    value: float

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_named_value_float(self.named, self.value)


@dataclass
class ReceivePendingCommand(Command):
    key: ClassVar[str | None] = "mavlink_receive_pending"
    service: "MavlinkService"

    def execute(self, context: SchedulerContext) -> None:
        self.service._receive_pending()


@dataclass
class SendTextToGcsCommand(Command):
    key: ClassVar[str | None] = None
    service: "MavlinkService"
    text: str
    severity: int = MavSeverity.INFO

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_text_to_gcs(self.text, self.severity)


@dataclass
class SendProtocolMessageCommand(Command):
    key: ClassVar[str | None] = None
    service: "MavlinkService"
    response: MavlinkParameterResponse

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_message_to(
            self.response.message,
            self.response.destination,
        )


class MavlinkService:
    def __init__(
        self,
        *,
        context: Context,
        parameter_service: ParameterService | None = None,
        qopenhd_addr=QOPENHD_ADDR,
        local_addr=LOCAL_ADDR,
        heartbeat_interval_s: float = 1.0,
        global_position_interval_s: float = GLOBAL_POSITION_INT_INTERVAL_S,
        attitude_interval_s: float = ATTITUDE_INTERVAL_S,
        sys_status_interval_s: float = SYS_STATUS_INTERVAL_S,
        rc_channels_interval_s: float = RC_CHANNELS_INTERVAL_S,
        v2_extension_channel_status_interval_s: float = V2_EXTENSION_CHANNEL_STATUS_INTERVAL_S,
        visual_detection_supplier: Callable[[], Mapping[str, Any] | None] | None = None,
        visual_mavlink_rate_hz: float = 20.0,
        poll_interval_s: float = 0.01,
    ) -> None:
        self.context = context
        self.qopenhd_addr = qopenhd_addr
        self.local_addr = local_addr
        self.heartbeat_interval_s = heartbeat_interval_s
        self.global_position_interval_s = global_position_interval_s
        self.attitude_interval_s = attitude_interval_s
        self.sys_status_interval_s = sys_status_interval_s
        self.rc_channels_interval_s = rc_channels_interval_s
        self.v2_extension_channel_status_interval_s = (
            v2_extension_channel_status_interval_s
        )
        if visual_mavlink_rate_hz <= 0:
            raise ValueError("visual_mavlink_rate_hz must be > 0")
        self.visual_detection_supplier = visual_detection_supplier
        self.visual_mavlink_interval_s = 1.0 / visual_mavlink_rate_hz
        self._last_visual_emission_key: tuple[int, int | None] | None = None
        self._last_visual_warning_at = float("-inf")
        self.poll_interval_s = poll_interval_s
        self._started = False
        self._socket = None
        self._boot_time_s = time.monotonic()
        self._mav = mavutil.mavlink.MAVLink(
            None, srcSystem=SYS_ID, srcComponent=COMP_ID
        )
        self._parser = mavutil.mavlink.MAVLink(None)
        self._parser.robust_parsing = True
        self._parameter_protocol = (
            MavlinkParameterProtocol(
                service=parameter_service,
                mav=self._mav,
                system_id=SYS_ID,
                component_id=COMP_ID,
                gcs_addr=self.qopenhd_addr,
                is_armed=lambda: bool(self.context.armed),
            )
            if parameter_service is not None
            else None
        )
        self._scheduler = CommandScheduler(
            context=self.context,
            on_error=lambda exc, command: log.exception(
                "MAVLink scheduler command {} failed: {}",
                command.__class__.__name__,
                exc,
            ),
        )

    def start(self) -> None:
        if self._started:
            return

        self._open_socket()
        self._scheduler.start()
        self._scheduler.schedule(
            HeartbeatCommand(self),
            interval_s=self.heartbeat_interval_s,
            key=HeartbeatCommand.key,
        )
        self._scheduler.schedule(
            GlobalPositionIntCommand(self),
            interval_s=self.global_position_interval_s,
            key=GlobalPositionIntCommand.key,
        )
        self._scheduler.schedule(
            AttitudeCommand(self),
            interval_s=self.attitude_interval_s,
            key=AttitudeCommand.key,
        )
        self._scheduler.schedule(
            SysStatusCommand(self),
            interval_s=self.sys_status_interval_s,
            key=SysStatusCommand.key,
        )
        self._scheduler.schedule(
            SendRcChannelsCommand(self),
            interval_s=self.rc_channels_interval_s,
            key=SendRcChannelsCommand.key,
        )
        self._scheduler.schedule(
            SendChannelStatusV2ExtensionCommand(self),
            interval_s=self.v2_extension_channel_status_interval_s,
            key=SendChannelStatusV2ExtensionCommand.key,
        )

        if self.visual_detection_supplier is not None:
            self._scheduler.schedule(
                SendRedDetectionV2ExtensionCommand(self),
                interval_s=self.visual_mavlink_interval_s,
                key=SendRedDetectionV2ExtensionCommand.key,
            )

        self._scheduler.schedule(
            ReceivePendingCommand(self),
            interval_s=self.poll_interval_s,
            key=ReceivePendingCommand.key,
        )
        self._started = True
        log.info(
            "MAVLink service started on {} -> {}",
            self.local_addr,
            self.qopenhd_addr,
        )

    def stop(self, timeout: float | None = 2.0) -> None:
        self._scheduler.stop(timeout=timeout)
        self._close_socket()
        self._started = False

    def send_text_to_gcs(
        self,
        text: str,
        severity: int = MavSeverity.INFO,
    ) -> None:
        self._scheduler.submit(SendTextToGcsCommand(self, text, severity))

    def send_named_value_to_gcs(self, name, value):
        command = NamedValueFloatCommand(self, name, value)
        self._scheduler.submit(
            ScheduledCommand(
                command=command,
                key_override=f"mavlink_named_value_float:{name}",
            )
        )

    def _open_socket(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(self.local_addr)
        sock.setblocking(False)
        self._socket = sock

    def _send_heartbeat(self) -> None:
        if self._socket is None:
            return

        msg = self._mav.heartbeat_encode(
            mavutil.mavlink.MAV_TYPE_GENERIC,
            mavutil.mavlink.MAV_AUTOPILOT_GENERIC,
            make_base_mode(self.context.armed),
            int(self.context.state),
            mavutil.mavlink.MAV_STATE_ACTIVE,
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _send_global_position_int(self) -> None:
        """
        The filtered global position (e.g. fused GPS and accelerometers). The position is in GPS-frame (right-handed, Z-up). It is designed as scaled integer message since the resolution of float is not sufficient.
        | Field Name | Type | Units | Description |
        | --- | --- | --- | --- |
        | time_boot_ms | uint32_t | ms | Timestamp (time since system boot). |
        | lat | int32_t | degE7 | Latitude, expressed |
        | lon | int32_t | degE7 | Longitude, expressed |
        | alt | int32_t | mm | Altitude (MSL). Note that virtually all GPS modules provide both WGS84 and MSL. |
        | relative_alt | int32_t | mm | Altitude above home |
        | vx | int16_t | cm/s | Ground X Speed (Latitude, positive north) |
        | vy | int16_t | cm/s | Ground Y Speed (Longitude, positive east) |
        | vz | int16_t | cm/s | Ground Z Speed (Altitude, positive down) |
        | hdg | uint16_t | cdeg | Vehicle heading (yaw angle), 0.0..359.99 degrees. If unknown, set to: UINT16_MAX |
        """
        if self._socket is None:
            return

        alt_mm = int(float(getattr(self.context, "drone_alt", 0.0)) * 1000.0)
        # bt-app/MSP uses upward-positive velocity while MAVLink
        # GLOBAL_POSITION_INT.vz is positive down.
        vz_cm_s = int(
            round(
                -float(getattr(self.context, "drone_vertical_speed", 0.0))
                * 100.0
            )
        )
        vz_cm_s = max(-32768, min(32767, vz_cm_s))
        msg = self._mav.global_position_int_encode(
            self._time_boot_ms(),
            0,
            0,
            alt_mm,
            alt_mm,
            0,
            0,
            vz_cm_s,
            UNKNOWN_GLOBAL_POSITION_HEADING,
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _send_attitude(self) -> None:
        if self._socket is None:
            return
        msg = self._mav.attitude_encode(
            self._time_boot_ms(),
            math.radians(float(self.context.drone_roll_deg)),
            math.radians(float(self.context.drone_pitch_deg)),
            math.radians(float(self.context.drone_heading_deg)),
            0.0,
            0.0,
            0.0,
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _send_sys_status(self) -> None:
        """
        TODO: calc the voltage and current against real FC
        """
        if self._socket is None:
            return

        voltage_mv = int(float(getattr(self.context, "battery_voltage", 0.0)) * 1000.0)
        voltage_mv = max(0, min(voltage_mv, MAX_UINT16))
        msg = self._mav.sys_status_encode(
            0,
            0,
            0,
            0,
            voltage_mv,
            UNKNOWN_CURRENT_BATTERY,
            UNKNOWN_BATTERY_REMAINING,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _send_rc_channels(self) -> None:
        if self._socket is None:
            return

        AETR_CHANNELS = 4
        COMMAND_CHANNELS = 18
        channels = tuple(
            int(channel) for channel in getattr(self.context, "drone_rc", ())
        )
        channel_count = min(len(channels), AETR_CHANNELS)
        raw_channels = [MAX_UINT16] * COMMAND_CHANNELS
        raw_channels[:channel_count] = channels[:channel_count]
        msg = self._mav.rc_channels_encode(
            self._time_boot_ms(),
            channel_count,
            *raw_channels,
            UNKNOWN_RSSI,
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _send_v2_extension(self, message_type: int, payload: bytes) -> None:
        if self._socket is None:
            return

        padded_payload = payload[:V2_EXTENSION_PAYLOAD_SIZE].ljust(
            V2_EXTENSION_PAYLOAD_SIZE,
            b"\x00",
        )
        msg = self._mav.v2_extension_encode(0, 0, 0, message_type, padded_payload)
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _make_channel_status_payload(self) -> bytes:
        channels = getattr(self.context, "sent_rc", None)
        if not channels or len(channels) != len(SAFE_DEFAULT_RC_CHANNELS):
            channels = SAFE_DEFAULT_RC_CHANNELS

        normalized_channels = tuple(
            max(0, min(int(channel), MAX_UINT16)) for channel in channels
        )
        return struct.pack(
            V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT,
            V2_EXTENSION_CHANNEL_STATUS_VERSION,
            V2_EXTENSION_CHANNEL_STATUS_COMMAND_ID,
            int(self.context.state),
            V2_EXTENSION_CHANNEL_STATUS_FLAGS,
            *normalized_channels,
        )

    def _send_channel_status_v2_extension(self) -> None:
        self._send_v2_extension(
            V2_EXTENSION_CHANNEL_STATUS_MESSAGE_TYPE,
            self._make_channel_status_payload(),
        )

    def _send_latest_red_detection(self) -> None:
        supplier = self.visual_detection_supplier
        if supplier is None:
            return
        detection = supplier()
        if detection is None:
            return
        try:
            emission_key = (
                int(detection["frame_id"]),
                None
                if detection["timestamp_ns"] is None
                else int(detection["timestamp_ns"]),
            )
            if emission_key == self._last_visual_emission_key:
                return
            payload = encode_red_detection(detection)
        except (KeyError, TypeError, ValueError, VisualMavlinkCodecError) as exc:
            now = time.monotonic()
            if now - self._last_visual_warning_at >= 2.0:
                self._last_visual_warning_at = now
                log.warning("Unable to publish visual MAVLink telemetry: {}", exc)
            return
        self._send_v2_extension(V2_EXTENSION_RED_DETECTION_MESSAGE_TYPE, payload)
        self._last_visual_emission_key = emission_key

    def _send_named_value_float(self, named: str, value: float) -> None:
        if self._socket is None:
            return

        msg = self._mav.named_value_float_encode(
            self._time_boot_ms(), self._named_value_name_bytes(named), value
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _named_value_name_bytes(self, named: str | bytes) -> bytes:
        if isinstance(named, bytes):
            return named[:10]
        return named.encode("ascii", errors="replace")[:10]

    def _send_text_to_gcs(
        self,
        text: str,
        severity: int = MavSeverity.INFO,
    ) -> None:
        if self._socket is None:
            return

        msg = self._mav.statustext_encode(int(severity), text.encode("utf-8")[:50])
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _receive_pending(self) -> None:
        if self._socket is None:
            return

        try:
            data, addr = self._socket.recvfrom(2048)
        except BlockingIOError:
            return

        try:
            for byte in data:
                msg = self._parser.parse_char(bytes([byte]))
                if msg is not None and self._parameter_protocol is not None:
                    self._schedule_protocol_responses(
                        self._parameter_protocol.handle(msg, addr)
                    )
        except mavutil.mavlink.MAVError as exc:
            log.warning("Discarding malformed MAVLink packet from {}: {}", addr, exc)

    def _schedule_protocol_responses(
        self,
        responses: list[MavlinkParameterResponse],
    ) -> None:
        for response in responses:
            self._scheduler.submit(
                SendProtocolMessageCommand(self, response),
                delay_s=response.delay_s,
            )

    def _send_message_to(self, message, destination: tuple[str, int]) -> None:
        if self._socket is None:
            return
        self._socket.sendto(message.pack(self._mav), destination)

    def _time_boot_ms(self) -> int:
        return int((time.monotonic() - self._boot_time_s) * 1000.0) & 0xFFFFFFFF

    def _close_socket(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()


def main() -> None:
    service = MavlinkService(context=Context())
    service.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        log.warning("Stopping MAVLink service")
    finally:
        service.stop()


if __name__ == "__main__":
    main()

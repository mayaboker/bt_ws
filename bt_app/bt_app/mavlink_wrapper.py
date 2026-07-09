#!/usr/bin/env python3

import socket
import time
from dataclasses import dataclass
from typing import ClassVar

from loguru import logger as log
from pymavlink import mavutil

from bt_app.context import Context
from bt_app.scheduler import Command, CommandScheduler, SchedulerContext


QOPENHD_ADDR = ("127.0.0.1", 14550)
LOCAL_ADDR = ("0.0.0.0", 14551)

SYS_ID = 1
COMP_ID = mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1
GLOBAL_POSITION_INT_INTERVAL_S = 0.5
UNKNOWN_GLOBAL_POSITION_HEADING = 65535


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
    severity: int = mavutil.mavlink.MAV_SEVERITY_INFO

    def execute(self, context: SchedulerContext) -> None:
        self.service._send_text_to_gcs(self.text, self.severity)


class MavlinkService:
    def __init__(
        self,
        *,
        context: Context,
        qopenhd_addr=QOPENHD_ADDR,
        local_addr=LOCAL_ADDR,
        heartbeat_interval_s: float = 1.0,
        global_position_interval_s: float = GLOBAL_POSITION_INT_INTERVAL_S,
        poll_interval_s: float = 0.01,
    ) -> None:
        self.context = context
        self.qopenhd_addr = qopenhd_addr
        self.local_addr = local_addr
        self.heartbeat_interval_s = heartbeat_interval_s
        self.global_position_interval_s = global_position_interval_s
        self.poll_interval_s = poll_interval_s
        self._started = False
        self._socket = None
        self._boot_time_s = time.monotonic()
        self._mav = mavutil.mavlink.MAVLink(None, srcSystem=SYS_ID, srcComponent=COMP_ID)
        self._parser = mavutil.mavlink.MAVLink(None)
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
        severity: int = mavutil.mavlink.MAV_SEVERITY_INFO,
    ) -> None:
        self._scheduler.submit(SendTextToGcsCommand(self, text, severity))

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
        if self._socket is None:
            return

        alt_mm = int(float(getattr(self.context, "drone_alt", 0.0)) * 1000.0)
        msg = self._mav.global_position_int_encode(
            self._time_boot_ms(),
            0,
            0,
            alt_mm,
            alt_mm,
            0,
            0,
            0,
            UNKNOWN_GLOBAL_POSITION_HEADING,
        )
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _send_text_to_gcs(
        self,
        text: str,
        severity: int = mavutil.mavlink.MAV_SEVERITY_INFO,
    ) -> None:
        if self._socket is None:
            return

        msg = self._mav.statustext_encode(severity, text.encode("utf-8")[:50])
        self._socket.sendto(msg.pack(self._mav), self.qopenhd_addr)

    def _receive_pending(self) -> None:
        if self._socket is None:
            return

        try:
            data, addr = self._socket.recvfrom(2048)
        except BlockingIOError:
            return

        for byte in data:
            msg = self._parser.parse_char(bytes([byte]))
            # if msg is not None:
            #     log.debug("Received MAVLink: {} from {}", msg.get_type(), addr)

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

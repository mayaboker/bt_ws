#!/usr/bin/env python3

import socket
import threading
import time

from loguru import logger as log
from pymavlink import mavutil

from bt_app.context import Context


QOPENHD_ADDR = ("127.0.0.1", 14550)
LOCAL_ADDR = ("0.0.0.0", 14551)

SYS_ID = 1
COMP_ID = mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1


def make_base_mode(armed: bool) -> int:
    base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    if armed:
        base_mode |= mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
    return base_mode


class MavlinkService:
    def __init__(
        self,
        *,
        context: Context,
        qopenhd_addr=QOPENHD_ADDR,
        local_addr=LOCAL_ADDR,
        heartbeat_interval_s: float = 1.0,
        poll_interval_s: float = 0.01,
    ) -> None:
        self.context = context
        self.qopenhd_addr = qopenhd_addr
        self.local_addr = local_addr
        self.heartbeat_interval_s = heartbeat_interval_s
        self.poll_interval_s = poll_interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket = None
        self._mav = mavutil.mavlink.MAVLink(None, srcSystem=SYS_ID, srcComponent=COMP_ID)
        self._parser = mavutil.mavlink.MAVLink(None)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="mavlink-service",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                self._thread = None
        self._close_socket()

    def _run(self) -> None:
        self._open_socket()
        last_heartbeat = 0.0
        log.info(
            "MAVLink service started on {} -> {}",
            self.local_addr,
            self.qopenhd_addr,
        )

        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_interval_s:
                    self._send_heartbeat()
                    last_heartbeat = now

                self._receive_pending()
                time.sleep(self.poll_interval_s)
        finally:
            self._close_socket()

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

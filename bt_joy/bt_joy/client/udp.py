"""UDP sender for joystick frames."""

from __future__ import annotations

import socket
from typing import NamedTuple


class UdpPacket(NamedTuple):
    payload: bytes
    address: tuple[str, int]


class UdpSender:
    def __init__(self, host: str, port: int) -> None:
        self.address = (host, port)
        self._socket: socket.socket | None = None

    def __enter__(self) -> "UdpSender":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def open(self) -> None:
        if self._socket is None:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def send(self, payload: bytes) -> None:
        if self._socket is None:
            raise RuntimeError("UdpSender is not open")
        self._socket.sendto(payload, self.address)

    def receive_available(self) -> list[UdpPacket]:
        if self._socket is None:
            raise RuntimeError("UdpSender is not open")

        packets = []
        while True:
            try:
                payload, address = self._socket.recvfrom(4096)
            except BlockingIOError:
                return packets
            packets.append(UdpPacket(payload, address))

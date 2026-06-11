from __future__ import annotations

import socket
from abc import ABC, abstractmethod


class MspTransport(ABC):
    @abstractmethod
    def open(self) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def write(self, data: bytes) -> None:
        pass

    @abstractmethod
    def read(self, size: int, timeout: float) -> bytes:
        pass

    def __enter__(self) -> "MspTransport":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class TcpMspTransport(MspTransport):
    def __init__(self, host: str, port: int, connect_timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self._socket: socket.socket | None = None

    def open(self) -> None:
        self._socket = socket.create_connection(
            (self.host, self.port),
            timeout=self.connect_timeout,
        )

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
            raise TimeoutError(f"Timeout while reading {size} bytes") from exc

        if not data:
            raise ConnectionError("MSP TCP socket closed")
        return data

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("TCP MSP transport is not open")
        return self._socket


class UdpMspTransport(MspTransport):
    def __init__(self, host: str, port: int, bind: tuple[str, int] | None = None) -> None:
        self.host = host
        self.port = port
        self.bind = bind
        self._socket: socket.socket | None = None
        self._buffer = bytearray()

    def open(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.bind is not None:
            self._socket.bind(self.bind)
        self._socket.connect((self.host, self.port))

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._buffer.clear()

    def write(self, data: bytes) -> None:
        self._require_socket().send(data)

    def read(self, size: int, timeout: float) -> bytes:
        while len(self._buffer) < size:
            sock = self._require_socket()
            sock.settimeout(timeout)
            try:
                self._buffer.extend(sock.recv(4096))
            except socket.timeout as exc:
                raise TimeoutError(f"Timeout while reading {size} UDP bytes") from exc

        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("UDP MSP transport is not open")
        return self._socket


class SerialMspTransport(MspTransport):
    def __init__(self, device: str, baudrate: int = 115200) -> None:
        self.device = device
        self.baudrate = baudrate
        self._serial = None

    def open(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "Serial MSP transport requires pyserial. Install the bt-app "
                "package dependencies or install pyserial."
            ) from exc

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
            raise RuntimeError("Serial MSP transport is not open")
        return self._serial

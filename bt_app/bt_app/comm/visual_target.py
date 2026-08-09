"""Receive red-target detection telemetry over ZeroMQ."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger as log
import msgpack
import zmq


DEFAULT_VISUAL_ZMQ_ENDPOINT = "tcp://127.0.0.1:5556"


@dataclass(frozen=True)
class VisualDetectionMessage:
    frame_id: int
    timestamp_ns: int | None
    found: bool
    x: int
    y: int
    width: int
    height: int
    locked: bool = False
    lock_found_frames: int = 0
    lock_missing_frames: int = 0


def decode_visual_detection(payload: bytes) -> VisualDetectionMessage | None:
    data = msgpack.unpackb(payload, raw=False, strict_map_key=False)
    if not isinstance(data, dict):
        raise ValueError("visual telemetry payload must decode to a map")
    if data.get("type") != "red-detection":
        return None
    timestamp_ns = data["timestamp_ns"]
    return VisualDetectionMessage(
        frame_id=int(data["frame_id"]),
        timestamp_ns=None if timestamp_ns is None else int(timestamp_ns),
        found=bool(data["found"]),
        x=int(data["x"]),
        y=int(data["y"]),
        width=int(data["width"]),
        height=int(data["height"]),
        locked=bool(data.get("locked", False)),
        lock_found_frames=int(data.get("lock_found_frames", 0)),
        lock_missing_frames=int(data.get("lock_missing_frames", 0)),
    )


class VisualTargetComm:
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_VISUAL_ZMQ_ENDPOINT,
        context: Any = None,
        on_result: Callable[[VisualDetectionMessage], Any] | None = None,
        poll_timeout_ms: int = 50,
    ) -> None:
        self.endpoint = endpoint
        self.context = context or zmq.Context.instance()
        self.on_result = on_result
        self.poll_timeout_ms = poll_timeout_ms
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: Any = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name="visual-target-zmq",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                self._thread = None

    def _receive_loop(self) -> None:
        socket = self.context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 1)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        socket.connect(self.endpoint)
        self._socket = socket
        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        try:
            while not self._stop_event.is_set():
                if not poller.poll(self.poll_timeout_ms):
                    continue
                result = None
                while True:
                    try:
                        payload = socket.recv(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        return
                    try:
                        candidate = decode_visual_detection(payload)
                    except (
                        KeyError,
                        TypeError,
                        ValueError,
                        msgpack.exceptions.UnpackException,
                    ) as exc:
                        log.warning("Ignored invalid visual telemetry: {}", exc)
                        continue
                    if candidate is not None:
                        result = candidate
                if result is not None and self.on_result is not None:
                    self.on_result(result)
        finally:
            self._close_socket()

    def _close_socket(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.close(linger=0)

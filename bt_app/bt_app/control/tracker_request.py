"""Non-blocking, ordered tracker-request publisher."""

from __future__ import annotations

import queue
import threading
from collections.abc import Mapping
from typing import Any

import msgpack
from loguru import logger


class TrackerRequestPublisher:
    def __init__(
        self,
        endpoint: str,
        *,
        context: Any = None,
        queue_size: int = 100,
    ) -> None:
        self.endpoint = endpoint
        self._context = context
        self._owns_context = context is None
        self._queue: queue.Queue[Mapping[str, object] | None] = queue.Queue(queue_size)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="tracker-request-zmq",
            daemon=True,
        )
        self._thread.start()

    def start_tracking(self, x: int, y: int) -> bool:
        return self._enqueue({"type": "start", "x": int(x), "y": int(y)})

    def adjust(self, delta_x: int, delta_y: int) -> bool:
        return self._enqueue(
            {"type": "adjustment", "delta_x": int(delta_x), "delta_y": int(delta_y)}
        )

    def resize(self, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            raise ValueError("tracker dimensions must be greater than zero")
        return self._enqueue(
            {"type": "resize", "width": int(width), "height": int(height)}
        )

    def stop_tracking(self) -> bool:
        return self._enqueue({"type": "stop"})

    def stop(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self.stop_tracking()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            logger.warning("tracker request queue full during shutdown")
        thread.join(timeout=timeout)
        if not thread.is_alive():
            self._thread = None

    def _enqueue(self, message: Mapping[str, object]) -> bool:
        try:
            self._queue.put_nowait(message)
            return True
        except queue.Full:
            logger.warning("tracker request dropped because command queue is full")
            return False

    def _run(self) -> None:
        import zmq

        context = self._context or zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.SNDHWM, self._queue.maxsize)
        try:
            socket.connect(self.endpoint)
            while True:
                message = self._queue.get()
                if message is None:
                    return
                try:
                    socket.send(
                        msgpack.packb(dict(message), use_bin_type=True),
                        flags=zmq.NOBLOCK,
                    )
                except zmq.Again:
                    logger.warning("tracker request dropped because ZMQ would block")
                except zmq.ZMQError as exc:
                    logger.warning("tracker request send failed: {}", exc)
        except zmq.ZMQError as exc:
            logger.warning("tracker request publisher unavailable endpoint={} reason={}", self.endpoint, exc)
        finally:
            socket.close(linger=0)
            if self._owns_context:
                context.term()

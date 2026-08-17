import threading
import time

import zmq
from bt_msgs import TrackerResultMessage
from loguru import logger

publisher_logger = logger.bind(component="bt_gst.zmq_publisher")


class ZmqPublisherError(RuntimeError):
    """Raised when the tracker-result publisher cannot start or stop cleanly."""


class ZmqFramePublisher:
    """Publish the latest tracker-result message without blocking GStreamer."""

    def __init__(
        self,
        endpoint: str,
        *,
        bind: bool = True,
        max_rate_hz: int = 30,
    ) -> None:
        self.endpoint = endpoint
        self.bind = bind
        self.max_rate_hz = max_rate_hz
        self._condition = threading.Condition()
        self._pending_message: TrackerResultMessage | None = None
        self._stopping = False
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self, timeout: float = 2.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._condition:
            self._pending_message = None
            self._stopping = False
        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run,
            name="red-detection-zmq-publisher",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop()
            raise ZmqPublisherError("ZMQ publisher startup timed out")
        if self._startup_error is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
            raise ZmqPublisherError(
                f"ZMQ publisher could not start: {self._startup_error}"
            ) from self._startup_error

    def publish(self, message: TrackerResultMessage) -> None:
        with self._condition:
            if self._stopping:
                return
            self._pending_message = message
            self._condition.notify()

    def stop(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        with self._condition:
            self._stopping = True
            self._condition.notify()
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise ZmqPublisherError("ZMQ publisher did not stop")
        self._thread = None

    def _run(self) -> None:
        context = None
        socket = None
        try:
            context = zmq.Context()
            socket = context.socket(zmq.PUB)
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.SNDHWM, 1)
            if self.bind:
                socket.bind(self.endpoint)
            else:
                socket.connect(self.endpoint)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            if socket is not None:
                socket.close(linger=0)
            if context is not None:
                context.term()
            return

        self._ready.set()
        minimum_interval = 1.0 / self.max_rate_hz
        last_send = float("-inf")
        try:
            while True:
                with self._condition:
                    while self._pending_message is None and not self._stopping:
                        self._condition.wait()
                    if self._stopping:
                        return

                    send_at = last_send + minimum_interval
                    remaining = send_at - time.monotonic()
                    while remaining > 0 and not self._stopping:
                        self._condition.wait(timeout=remaining)
                        remaining = send_at - time.monotonic()
                    if self._stopping:
                        return
                    message = self._pending_message
                    self._pending_message = None

                try:
                    socket.send(message.encode(), flags=zmq.NOBLOCK)
                except zmq.Again:
                    publisher_logger.debug("dropped tracker result reason=send-would-block")
                except zmq.ZMQError as exc:
                    publisher_logger.warning("tracker result send failed error={}", exc)
                last_send = time.monotonic()
        finally:
            socket.close(linger=0)
            context.term()

from __future__ import annotations

import threading

from loguru import logger
import zmq

from bt_app.common import Event, ZMQ_TRACKER_RESULT_ENDPOINT, ZMQ_TRACKER_RESULT_TOPIC
from bt_app.bt_app.context_old import Context
from bt_app.msgs import TrackerResult, unpack_tracker_result


class TrackerResultComm:
    """Receive tracker results from ZMQ and expose them as events."""

    def __init__(
        self,
        *,
        endpoint: str = ZMQ_TRACKER_RESULT_ENDPOINT,
        topic: bytes = ZMQ_TRACKER_RESULT_TOPIC,
        context=None,
        poll_timeout_ms: int = 50,
    ) -> None:
        self.endpoint = endpoint
        self.topic = topic
        self.context = context or zmq.Context.instance()
        self.poll_timeout_ms = poll_timeout_ms
        self.on_result = Event()

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._receive_loop,
            name="tracker-result-zmq",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if not self._thread.is_alive():
                self._thread = None
        self._close_socket()

    def _receive_loop(self) -> None:
        socket = self.context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 2)
        socket.setsockopt(zmq.SUBSCRIBE, self.topic)
        socket.connect(self.endpoint)
        self._socket = socket

        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)

        logger.info(
            "Subscribed to tracker results from {} on topic {}",
            self.endpoint,
            self.topic.decode("utf-8", errors="replace"),
        )

        try:
            while not self._stop_event.is_set():
                if not poller.poll(self.poll_timeout_ms):
                    continue

                result = self._recv_latest_result(socket)
                if result is not None:
                    self.on_result.emit(result)
        finally:
            self._close_socket()

    def _recv_latest_result(self, socket) -> TrackerResult | None:
        latest = None

        while True:
            try:
                _topic, payload = socket.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                return latest
            except zmq.ZMQError:
                raise

            latest = unpack_tracker_result(payload)

    def _close_socket(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.close(linger=0)


class Telemetry:
    """Apply tracker telemetry to the shared flight context."""

    def __init__(
        self,
        *,
        context: Context
    ) -> None:
        self.context = context
        self.tracker_result_comm = TrackerResultComm()
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        self.tracker_result_comm.on_result += self.handle_tracker_result
        self.tracker_result_comm.start()
        self._started = True
        logger.info("Telemetry is updating tracker state in flight context")

    def stop(self) -> None:
        if not self._started:
            return

        self.tracker_result_comm.on_result -= self.handle_tracker_result
        self.tracker_result_comm.stop()
        self._started = False

    def handle_tracker_result(self, result: TrackerResult) -> None:
        self.context.set_tracker_result(result)

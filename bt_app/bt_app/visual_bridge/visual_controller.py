import threading
from collections.abc import Callable

import zmq
from bt_msgs import TrackerResultMessage
from loguru import logger as log

DEFAULT_VISUAL_ZMQ_ENDPOINT = "tcp://127.0.0.1:5556"


class VisualTargetComm:
    """Receive the newest tracker result without blocking the application loop."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_VISUAL_ZMQ_ENDPOINT,
        context: zmq.Context | None = None,
        on_result: Callable[[TrackerResultMessage], None] | None = None,
        poll_timeout_ms: int = 50,
    ) -> None:
        if poll_timeout_ms <= 0:
            raise ValueError("poll_timeout_ms must be greater than zero")
        self.endpoint = endpoint
        self.context = context or zmq.Context.instance()
        self.on_result = on_result
        self.poll_timeout_ms = poll_timeout_ms
        self._stop_event = threading.Event()
        self._startup_event = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 2.0) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._startup_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._receive_loop,
            name="visual-target-zmq",
            daemon=True,
        )
        self._thread.start()
        if not self._startup_event.wait(timeout):
            self.stop(timeout=timeout)
            raise RuntimeError("visual bridge did not start before the timeout")
        if self._startup_error is not None:
            self._thread.join(timeout)
            self._thread = None
            raise RuntimeError("unable to start visual bridge") from self._startup_error

    def stop(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop_event.set()
        thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError("visual bridge did not stop before the timeout")
        self._thread = None

    def _receive_loop(self) -> None:
        socket = None
        try:
            socket = self.context.socket(zmq.SUB)
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.RCVHWM, 1)
            socket.setsockopt(zmq.SUBSCRIBE, b"")
            socket.connect(self.endpoint)
            self._startup_event.set()
            poller = zmq.Poller()
            poller.register(socket, zmq.POLLIN)
            while not self._stop_event.is_set():
                if not poller.poll(self.poll_timeout_ms):
                    continue
                newest = None
                while True:
                    try:
                        payload = socket.recv(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    try:
                        newest = TrackerResultMessage.decode(payload)
                    except (TypeError, ValueError) as exc:
                        log.warning("Ignored invalid tracker result: {}", exc)
                if newest is not None and self.on_result is not None:
                    try:
                        self.on_result(newest)
                    except Exception:
                        log.exception("Visual bridge result callback failed")
        except Exception as exc:
            if not self._startup_event.is_set():
                self._startup_error = exc
                self._startup_event.set()
            elif not self._stop_event.is_set():
                log.exception("Visual bridge receiver failed: {}", exc)
        finally:
            if not self._startup_event.is_set():
                self._startup_event.set()
            if socket is not None:
                socket.close(linger=0)

"""Non-blocking target-selector command receiver for the pipeline runner."""

from __future__ import annotations

import threading
import time

import zmq
from bt_msgs import TargetSelectorCommandMessage, TargetSelectorState
from loguru import logger

selector_logger = logger.bind(component="bt_gst.selector_subscriber")


class SelectorSubscriberError(RuntimeError):
    pass


class ZmqSelectorSubscriber:
    def __init__(self, endpoint: str, *, bind: bool = False) -> None:
        self.endpoint = endpoint
        self.bind = bind
        self._lock = threading.Lock()
        self._latest = None
        self._received_at_s = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._startup_error = None
        self._thread = None

    def start(self, timeout: float = 2.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._ready.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run, name="target-selector-zmq", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop()
            raise SelectorSubscriberError("selector subscriber startup timed out")
        if self._startup_error is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
            raise SelectorSubscriberError(
                f"selector subscriber could not start: {self._startup_error}"
            ) from self._startup_error

    def stop(self, timeout: float = 2.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise SelectorSubscriberError("selector subscriber did not stop")
        self._thread = None

    def latest(self, *, max_age_s: float, now_s: float | None = None):
        now_s = time.monotonic() if now_s is None else now_s
        with self._lock:
            message = self._latest
            received_at_s = self._received_at_s
        if message is None or received_at_s is None:
            return None
        if now_s - received_at_s <= max_age_s:
            return message
        return TargetSelectorCommandMessage(
            timestamp_ns=time.monotonic_ns(),
            center_x=message.center_x,
            center_y=message.center_y,
            state=TargetSelectorState.DISABLED,
        )

    def _run(self) -> None:
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 1)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        try:
            if self.bind:
                socket.bind(self.endpoint)
            else:
                socket.connect(self.endpoint)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            socket.close(linger=0)
            context.term()
            return
        self._ready.set()
        try:
            while not self._stop.is_set():
                if not socket.poll(timeout=100):
                    continue
                payload = socket.recv()
                try:
                    message = TargetSelectorCommandMessage.decode(payload)
                except ValueError as exc:
                    selector_logger.warning("dropped selector command error={}", exc)
                    continue
                with self._lock:
                    self._latest = message
                    self._received_at_s = time.monotonic()
        finally:
            socket.close(linger=0)
            context.term()

import queue
import threading
import time
from dataclasses import asdict
from typing import Any

DEFAULT_TRACKER_META_ENDPOINT = "tcp://127.0.0.1:5556"
TRACKER_META_TOPIC = b"tracker_meta"
TRACKER_META_VERSION = 1


class ZmqPublisherError(RuntimeError):
    """Raised when the ZMQ publisher cannot start."""


def encode_tracker_meta(meta: Any, timestamp_ns: int | None = None) -> bytes:
    import msgpack

    payload = {
        "version": TRACKER_META_VERSION,
        "timestamp_ns": timestamp_ns if timestamp_ns is not None else time.time_ns(),
        **asdict(meta),
    }
    return msgpack.packb(payload, use_bin_type=True)


class TrackerMetaPublisher:
    def __init__(self, endpoint: str = DEFAULT_TRACKER_META_ENDPOINT) -> None:
        self.endpoint = endpoint
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return

        try:
            import msgpack  # noqa: F401
            import zmq  # noqa: F401
        except ImportError as exc:
            raise ZmqPublisherError(
                "failed to import ZMQ tracker metadata publisher dependencies"
            ) from exc

        self._thread = threading.Thread(
            target=self._run,
            name="bt-gst-tracker-meta-publisher",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

        if self._startup_error is not None:
            self.close()
            raise ZmqPublisherError(
                f"failed to start ZMQ tracker metadata publisher at {self.endpoint}: "
                f"{self._startup_error}"
            ) from self._startup_error

    def publish(self, meta: Any) -> None:
        if self._closed.is_set():
            return

        message = encode_tracker_meta(meta)
        self._replace_queued_message(message)

    def close(self) -> None:
        self._closed.set()
        self._replace_queued_message(None)
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _replace_queued_message(self, message: bytes | None) -> None:
        try:
            self._queue.put_nowait(message)
            return
        except queue.Full:
            pass

        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            pass

    def _run(self) -> None:
        import zmq

        context = zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.setsockopt(zmq.SNDHWM, 1)
        socket.setsockopt(zmq.LINGER, 0)

        try:
            socket.bind(self.endpoint)
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            socket.close(linger=0)
            context.term()
            return

        self._ready.set()

        try:
            while True:
                message = self._queue.get()
                if message is None:
                    break

                try:
                    socket.send_multipart(
                        [TRACKER_META_TOPIC, message],
                        flags=zmq.NOBLOCK,
                    )
                except zmq.Again:
                    continue
        finally:
            socket.close(linger=0)
            context.term()

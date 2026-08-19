import threading
from collections.abc import Callable

from bt_msgs import TrackerResultMessage
from loguru import logger as log

from .visual_controller import VisualTargetComm


class VisualBridgeManager:
    """Own the tracker-result communication lifecycle for the application."""

    def __init__(self, endpoint: str) -> None:
        self._subscribers: list[Callable[[TrackerResultMessage], None]] = []
        self._subscriber_lock = threading.Lock()
        self._comm = VisualTargetComm(
            endpoint=endpoint,
            on_result=self._on_tracker_result,
        )

    @property
    def is_running(self) -> bool:
        return self._comm.is_running

    def start(self) -> None:
        self._comm.start()

    def stop(self) -> None:
        self._comm.stop()

    def subscribe(self, callback: Callable[[TrackerResultMessage], None]) -> None:
        with self._subscriber_lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[TrackerResultMessage], None]) -> None:
        with self._subscriber_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _on_tracker_result(self, message: TrackerResultMessage) -> None:
        with self._subscriber_lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(message)
            except Exception:
                log.exception("Visual tracker result subscriber failed")

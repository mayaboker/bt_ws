from bt_msgs import TrackerResultMessage
from loguru import logger as log

from .visual_controller import VisualTargetComm


class VisualBridgeManager:
    """Own the tracker-result communication lifecycle for the application."""

    def __init__(self, endpoint: str) -> None:
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

    @staticmethod
    def _on_tracker_result(message: TrackerResultMessage) -> None:
        log.info(
            "Incoming tracker result frame_id={} timestamp_ns={}",
            message.frame_id,
            message.timestamp_ns,
        )

"""Communication adapters and their wire-level message models."""

from bt_app.comm.visual_target import (
    DEFAULT_VISUAL_ZMQ_ENDPOINT,
    VisualDetectionMessage,
    VisualTargetComm,
    decode_visual_detection,
)

__all__ = [
    "DEFAULT_VISUAL_ZMQ_ENDPOINT",
    "VisualDetectionMessage",
    "VisualTargetComm",
    "decode_visual_detection",
]

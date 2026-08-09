"""Communication adapters and their wire-level message models."""

from bt_app.comm.gst_bridge import (
    DEFAULT_VISUAL_ZMQ_ENDPOINT,
    VisualDetectionMessage,
    GST_Bridge,
    decode_visual_detection,
)

__all__ = [
    "DEFAULT_VISUAL_ZMQ_ENDPOINT",
    "VisualDetectionMessage",
    "GST_Bridge",
    "decode_visual_detection",
]

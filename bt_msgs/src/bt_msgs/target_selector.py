"""MessagePack wire model for image-space target-selector commands."""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import msgpack


class TargetSelectorState(IntEnum):
    DISABLED = 0
    SELECTING = 1
    LOCKED = 2


_WIRE_FIELDS = ("timestamp_ns", "center_x", "center_y", "state")


@dataclass(frozen=True, slots=True)
class TargetSelectorCommandMessage:
    """Absolute normalized selector position and selection lifecycle state."""

    timestamp_ns: int
    center_x: float
    center_y: float
    state: TargetSelectorState
    roi_width: int | None = None
    roi_height: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.timestamp_ns, bool) or not isinstance(
            self.timestamp_ns, int
        ):
            raise ValueError("timestamp_ns must be an integer")
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be nonnegative")
        for name, value in (("center_x", self.center_x), ("center_y", self.center_y)):
            if isinstance(value, bool) or not isinstance(value, float):
                raise ValueError(f"{name} must be a float")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0")
        if not isinstance(self.state, TargetSelectorState):
            raise ValueError("state must be a TargetSelectorState")
        if (self.roi_width is None) != (self.roi_height is None):
            raise ValueError("roi_width and roi_height must be provided together")
        for name, value in (
            ("roi_width", self.roi_width),
            ("roi_height", self.roi_height),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")

    def encode(self) -> bytes:
        try:
            data = {
                "timestamp_ns": self.timestamp_ns,
                "center_x": self.center_x,
                "center_y": self.center_y,
                "state": int(self.state),
            }
            if self.roi_width is not None:
                data["roi_width"] = self.roi_width
                data["roi_height"] = self.roi_height
            return msgpack.packb(data, use_bin_type=True)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"unable to encode target selector command: {exc}"
            ) from exc

    @classmethod
    def decode(
        cls, payload: bytes | bytearray | memoryview
    ) -> "TargetSelectorCommandMessage":
        try:
            data = msgpack.unpackb(payload, raw=False)
        except (msgpack.UnpackException, TypeError, ValueError) as exc:
            raise ValueError(f"invalid target selector MessagePack: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("target selector payload must contain a mapping")
        missing = [field for field in _WIRE_FIELDS if field not in data]
        if missing:
            raise ValueError(
                "target selector fields are missing: " + ", ".join(missing)
            )
        try:
            state = TargetSelectorState(_required_integer(data, "state"))
        except ValueError as exc:
            raise ValueError("state must be a valid TargetSelectorState") from exc
        return cls(
            timestamp_ns=_required_integer(data, "timestamp_ns"),
            center_x=_required_float(data, "center_x"),
            center_y=_required_float(data, "center_y"),
            state=state,
            roi_width=_optional_integer(data, "roi_width"),
            roi_height=_optional_integer(data, "roi_height"),
        )


def _required_integer(data: dict[Any, Any], field: str) -> int:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _required_float(data: dict[Any, Any], field: str) -> float:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, float):
        raise ValueError(f"{field} must be a float")
    return value


def _optional_integer(data: dict[Any, Any], field: str) -> int | None:
    if field not in data:
        return None
    return _required_integer(data, field)

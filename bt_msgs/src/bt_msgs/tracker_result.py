"""MessagePack wire model for generic tracker results."""

from dataclasses import dataclass
from typing import Any

import msgpack

TRACKER_STATE_UNKNOWN = 0
_WIRE_FIELDS = (
    "tracker_id",
    "frame_id",
    "timestamp_ns",
    "locked",
    "bbox_x",
    "bbox_y",
    "bbox_width",
    "bbox_height",
    "score",
    "state",
    "dx",
    "dy",
)


@dataclass(frozen=True, slots=True)
class TrackerResultMessage:
    """Immutable generic tracker result shared between workspace processes."""

    frame_id: int
    timestamp_ns: int | None
    tracker_id: int = 0
    locked: bool = False
    bbox_x: int = 0
    bbox_y: int = 0
    bbox_width: int = 0
    bbox_height: int = 0
    score: float = 0.0
    state: int = TRACKER_STATE_UNKNOWN
    dx: int = 0
    dy: int = 0

    def __post_init__(self) -> None:
        _validate_nonnegative_integer("tracker_id", self.tracker_id)
        _validate_nonnegative_integer("frame_id", self.frame_id)
        if self.timestamp_ns is not None:
            _validate_nonnegative_integer("timestamp_ns", self.timestamp_ns)
        if not isinstance(self.locked, bool):
            raise ValueError("locked must be a boolean")  # noqa: TRY004
        for name, value in (
            ("bbox_x", self.bbox_x),
            ("bbox_y", self.bbox_y),
            ("bbox_width", self.bbox_width),
            ("bbox_height", self.bbox_height),
        ):
            _validate_nonnegative_integer(name, value)
        if isinstance(self.score, bool) or not isinstance(self.score, float):
            raise ValueError("score must be a float")  # noqa: TRY004
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        _validate_nonnegative_integer("state", self.state)
        _validate_integer("dx", self.dx)
        _validate_integer("dy", self.dy)

        box = (self.bbox_x, self.bbox_y, self.bbox_width, self.bbox_height)
        if self.locked:
            if self.bbox_width <= 0 or self.bbox_height <= 0:
                raise ValueError(
                    "locked tracker result must have a positive bounding-box size"
                )
        elif any(box):
            raise ValueError(
                "unlocked tracker result must have an all-zero bounding box"
            )

    def encode(self) -> bytes:
        """Serialize this tracker result as an explicit MessagePack mapping."""
        try:
            return msgpack.packb(
                {
                    "tracker_id": self.tracker_id,
                    "frame_id": self.frame_id,
                    "timestamp_ns": self.timestamp_ns,
                    "locked": self.locked,
                    "bbox_x": self.bbox_x,
                    "bbox_y": self.bbox_y,
                    "bbox_width": self.bbox_width,
                    "bbox_height": self.bbox_height,
                    "score": self.score,
                    "state": self.state,
                    "dx": self.dx,
                    "dy": self.dy,
                },
                use_bin_type=True,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"unable to encode tracker result: {exc}") from exc

    @classmethod
    def decode(
        cls,
        payload: bytes | bytearray | memoryview,
    ) -> "TrackerResultMessage":
        """Deserialize and validate one MessagePack tracker-result mapping."""
        try:
            data = msgpack.unpackb(payload, raw=False)
        except (msgpack.UnpackException, TypeError, ValueError) as exc:
            raise ValueError(f"invalid tracker result MessagePack: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(  # noqa: TRY004 - malformed wire payload
                "tracker result payload must contain a mapping"
            )
        missing = [field for field in _WIRE_FIELDS if field not in data]
        if missing:
            raise ValueError(
                "tracker result fields are missing: " + ", ".join(missing)
            )
        return cls(
            tracker_id=_required_integer(data, "tracker_id"),
            frame_id=_required_integer(data, "frame_id"),
            timestamp_ns=_optional_integer(data, "timestamp_ns"),
            locked=_required_boolean(data, "locked"),
            bbox_x=_required_integer(data, "bbox_x"),
            bbox_y=_required_integer(data, "bbox_y"),
            bbox_width=_required_integer(data, "bbox_width"),
            bbox_height=_required_integer(data, "bbox_height"),
            score=_required_float(data, "score"),
            state=_required_integer(data, "state"),
            dx=_required_integer(data, "dx"),
            dy=_required_integer(data, "dy"),
        )


def _validate_integer(field: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")  # noqa: TRY004


def _validate_nonnegative_integer(field: str, value: object) -> None:
    _validate_integer(field, value)
    if value < 0:  # type: ignore[operator]
        raise ValueError(f"{field} must be nonnegative")


def _required_integer(data: dict[Any, Any], field: str) -> int:
    value = data[field]
    _validate_integer(field, value)
    return value


def _optional_integer(data: dict[Any, Any], field: str) -> int | None:
    value = data[field]
    if value is None:
        return None
    _validate_integer(field, value)
    return value


def _required_boolean(data: dict[Any, Any], field: str) -> bool:
    value = data[field]
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")  # noqa: TRY004
    return value


def _required_float(data: dict[Any, Any], field: str) -> float:
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, float):
        raise ValueError(f"{field} must be a float")  # noqa: TRY004
    return value

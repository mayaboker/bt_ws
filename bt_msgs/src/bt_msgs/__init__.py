from dataclasses import dataclass
from typing import Any

import msgpack


@dataclass(frozen=True)
class TrackerResultMessage:
    frame_id: int
    timestamp: int | None

    def __post_init__(self) -> None:
        _validate_integer("frame_id", self.frame_id)
        if self.timestamp is not None:
            _validate_integer("timestamp", self.timestamp)

    def encode(self) -> bytes:
        """Serialize this tracker result as a MessagePack mapping."""
        return msgpack.packb(
            {
                "frame_id": self.frame_id,
                "timestamp": self.timestamp,
            },
            use_bin_type=True,
        )

    @classmethod
    def decode(
        cls,
        payload: bytes | bytearray | memoryview,
    ) -> "TrackerResultMessage":
        """Deserialize a MessagePack tracker result payload."""
        data = msgpack.unpackb(payload, raw=False)
        if not isinstance(data, dict):
            raise ValueError(  # noqa: TRY004 - malformed wire payload
                "tracker result payload must contain a mapping"
            )
        missing = [field for field in ("frame_id", "timestamp") if field not in data]
        if missing:
            raise ValueError(
                "tracker result fields are missing: " + ", ".join(missing)
            )
        return cls(
            frame_id=_required_integer(data, "frame_id"),
            timestamp=_optional_integer(data, "timestamp"),
        )


def _validate_integer(field: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")  # noqa: TRY004


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


__all__ = ["TrackerResultMessage"]

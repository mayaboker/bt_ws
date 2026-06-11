from dataclasses import dataclass
from enum import IntEnum

import msgpack


@dataclass(frozen=True)
class LinearVelocity:
    x: float
    y: float
    z: float


class TrackerState(IntEnum):
    LOST = 0
    TRACKING = 1


@dataclass(frozen=True)
class TrackerResult:
    error_x: float
    error_y: float
    state: TrackerState = TrackerState.TRACKING
    score: int = 0
    tracker_id: str = ""


def pack_tracker_result(result: TrackerResult) -> bytes:
    return msgpack.packb(
        {
            "error_x": result.error_x,
            "error_y": result.error_y,
            "state": int(result.state),
            "score": result.score,
            "tracker_id": result.tracker_id,
        },
        use_bin_type=True,
    )


def unpack_tracker_result(payload: bytes) -> TrackerResult:
    data = msgpack.unpackb(payload, raw=False)
    return TrackerResult(
        error_x=float(data["error_x"]),
        error_y=float(data["error_y"]),
        state=TrackerState(data.get("state", TrackerState.TRACKING)),
        score=int(data.get("score", 0)),
        tracker_id=str(data.get("tracker_id", "")),
    )


@dataclass(frozen=True)
class RCChannels:
    roll: int
    pitch: int
    throttle: int
    yaw: int
    arm: int
    angle_mode: int
    aux3: int
    aux4: int

    def to_list(self) -> list[int]:
        return [
            self.roll,
            self.pitch,
            self.throttle,
            self.yaw,
            self.arm,
            self.angle_mode,
            self.aux3,
            self.aux4,
        ]

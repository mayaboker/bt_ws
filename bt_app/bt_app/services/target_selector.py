"""Own and publish the pilot's absolute image-space target selector."""

from __future__ import annotations

import time

import zmq
from loguru import logger

from bt_msgs import TargetSelectorCommandMessage, TargetSelectorState
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN

DEFAULT_TARGET_SELECTOR_ENDPOINT = "tcp://127.0.0.1:5557"
SELECTOR_SPEED_NORMALIZED_S = 360.0 / 640.0
SELECTOR_SIZE_SPEED_PX_S = 50.0
DEFAULT_SELECTOR_WIDTH = 60
DEFAULT_SELECTOR_HEIGHT = 90


class TargetSelectorPublisher:
    """Integrate stick velocity and publish an idempotent absolute position."""

    def __init__(self, endpoint: str = DEFAULT_TARGET_SELECTOR_ENDPOINT, context=None):
        self._endpoint = endpoint
        self._context = context or zmq.Context.instance()
        self._socket = None
        self.center_x = 0.5
        self.center_y = 0.5
        self.roi_width = DEFAULT_SELECTOR_WIDTH
        self.roi_height = DEFAULT_SELECTOR_HEIGHT
        self._last_update_s = None

    def start(self) -> None:
        self._socket = self._context.socket(zmq.PUB)
        self._socket.setsockopt(zmq.SNDHWM, 2)
        self._socket.bind(self._endpoint)

    def stop(self) -> None:
        if self._socket is not None:
            self._socket.close(linger=0)
            self._socket = None

    def update(
        self,
        *,
        roll_rc: int,
        pitch_rc: int,
        width_rc: int = RC_MIN,
        height_rc: int = RC_MIN,
        state: TargetSelectorState,
        now_s: float | None = None,
    ) -> TargetSelectorCommandMessage:
        now_s = time.monotonic() if now_s is None else float(now_s)
        dt_s = (
            0.0
            if self._last_update_s is None
            else min(max(now_s - self._last_update_s, 0.0), 0.1)
        )
        self._last_update_s = now_s
        if state == TargetSelectorState.DISABLED:
            self.center_x = 0.5
            self.center_y = 0.5
        elif state == TargetSelectorState.SELECTING:
            self.center_x = _clamp01(
                self.center_x
                + _normalize_rc(roll_rc) * SELECTOR_SPEED_NORMALIZED_S * dt_s
            )
            # Pulling pitch back (PWM above center) moves upward in image coordinates.
            self.center_y = _clamp01(
                self.center_y
                - _normalize_rc(pitch_rc) * SELECTOR_SPEED_NORMALIZED_S * dt_s
            )
            self.roi_width = _resize(self.roi_width, width_rc, dt_s)
            self.roi_height = _resize(self.roi_height, height_rc, dt_s)
        message = TargetSelectorCommandMessage(
            timestamp_ns=time.monotonic_ns(),
            center_x=float(self.center_x),
            center_y=float(self.center_y),
            state=state,
            roi_width=self.roi_width,
            roi_height=self.roi_height,
        )
        if self._socket is None:
            return message
        try:
            self._socket.send(message.encode(), flags=zmq.NOBLOCK)
        except zmq.Again:
            pass
        except zmq.ZMQError as exc:
            logger.warning("target selector command send failed error={}", exc)
        return message


def _normalize_rc(value: int, deadband: int = 35) -> float:
    offset = max(RC_MIN, min(RC_MAX, int(value))) - RC_MID
    if abs(offset) <= deadband:
        return 0.0
    usable = (RC_MAX - RC_MID) - deadband
    return max(-1.0, min(1.0, (abs(offset) - deadband) / usable)) * (
        1 if offset > 0 else -1
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _resize(current: int, command_rc: int, dt_s: float) -> int:
    if command_rc == RC_MIN:
        return current
    direction = -1 if command_rc == RC_MID else 1
    return max(1, round(current + direction * SELECTOR_SIZE_SPEED_PX_S * dt_s))

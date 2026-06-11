"""Optional server-side automation stages for joystick channels."""

from __future__ import annotations

from enum import Enum
import time

from loguru import logger

from bt_joy.server.config import TakeoffAutomationConfig
from bt_joy.server.state import RcChannel, ServerStateStore


class TakeoffAutomationMode(Enum):
    IDLE = "idle"
    TAKEOFF = "takeoff"
    HOLD = "hold"


class TakeoffAutomation:
    """AUX-triggered arm and altitude PID controller."""

    def __init__(self, config: TakeoffAutomationConfig) -> None:
        self.config = config
        self.mode = TakeoffAutomationMode.IDLE
        self._missing_altitude_logged = False
        self._manual_arm_wait_logged = False
        self._automatic_control_logged = False
        self._integral_error = 0.0
        self._last_error: float | None = None
        self._last_update_at: float | None = None

    def apply(self, channels: tuple[int, ...], state_store: ServerStateStore) -> tuple[int, ...]:
        
        if not self.config.enabled:
            return channels

        trigger_channel = _parse_rc_channel(self.config.trigger_channel)
        arm_channel = _parse_rc_channel(self.config.arm_channel)
        required_channel = max(RcChannel.THROTTLE, trigger_channel, arm_channel)
        if len(channels) <= int(required_channel):
            logger.warning(
                "takeoff automation skipped; channels length={} missing required channel {}",
                len(channels),
                required_channel.name.lower(),
            )
            self.mode = TakeoffAutomationMode.IDLE
            return channels

        trigger_active = channels[int(trigger_channel)] >= self.config.trigger_on
        if not trigger_active:
            if self.mode != TakeoffAutomationMode.IDLE:
                logger.info("takeoff automation stopped; trigger released")
            self._reset()
            return channels

        if self.config.require_manual_arm and channels[int(arm_channel)] < self.config.trigger_on:
            if not self._manual_arm_wait_logged:
                logger.warning("takeoff automation waiting for manual arm channel")
                self._manual_arm_wait_logged = True
            return channels

        if self.mode == TakeoffAutomationMode.IDLE:
            logger.info(
                "takeoff automation started target_altitude_m={:.2f}",
                self.config.target_altitude_m,
            )
            self.mode = TakeoffAutomationMode.TAKEOFF
            self._manual_arm_wait_logged = False
            self._reset_pid()

        snapshot = state_store.snapshot()
        altitude = snapshot.altitude
        if altitude is None:
            if not self._missing_altitude_logged:
                logger.warning("takeoff automation waiting for altitude data")
                self._missing_altitude_logged = True
            return channels

        output = list(channels)
        output[int(arm_channel)] = self.config.arm_on
        manual_throttle = output[int(RcChannel.THROTTLE)]
        pid_throttle = self._compute_pid_throttle(
            altitude_m=altitude.altitude_m,
            vertical_speed_m_s=altitude.vertical_speed_m_s,
        )
        if not self._automatic_control_logged:
            logger.warning(
                "takeoff automation entered automatic control mode altitude_m={:.2f} "
                "target_altitude_m={:.2f} manual_throttle={} pid_throttle={}",
                altitude.altitude_m,
                self.config.target_altitude_m,
                manual_throttle,
                pid_throttle,
            )
            self._automatic_control_logged = True
        output[int(RcChannel.THROTTLE)] = max(manual_throttle, pid_throttle)

        if self.mode == TakeoffAutomationMode.TAKEOFF:
            if altitude.altitude_m >= self.config.target_altitude_m - self.config.target_tolerance_m:
                logger.info(
                    "takeoff automation reached target altitude altitude_m={:.2f}",
                    altitude.altitude_m,
                )
                self.mode = TakeoffAutomationMode.HOLD

        return tuple(output)

    def _compute_pid_throttle(
        self,
        altitude_m: float,
        vertical_speed_m_s: float,
    ) -> int:
        now = time.monotonic()
        error = self.config.target_altitude_m - altitude_m
        dt = 0.0 if self._last_update_at is None else max(0.0, now - self._last_update_at)

        if dt > 0.0:
            self._integral_error += error * dt
            self._integral_error = _clamp_float(
                self._integral_error,
                -self.config.pid_integral_limit,
                self.config.pid_integral_limit,
            )

        derivative_error = -vertical_speed_m_s
        if self._last_error is not None and dt > 0.0:
            derivative_error = (error - self._last_error) / dt

        self._last_error = error
        self._last_update_at = now

        throttle = (
            self.config.throttle_base
            + self.config.pid_kp * error
            + self.config.pid_ki * self._integral_error
            + self.config.pid_kd * derivative_error
        )
        return _clamp_int(round(throttle), self.config.throttle_min, self.config.throttle_max)

    def _reset(self) -> None:
        self.mode = TakeoffAutomationMode.IDLE
        self._missing_altitude_logged = False
        self._manual_arm_wait_logged = False
        self._automatic_control_logged = False
        self._reset_pid()

    def _reset_pid(self) -> None:
        self._integral_error = 0.0
        self._last_error = None
        self._last_update_at = None


def _parse_rc_channel(name: str) -> RcChannel:
    normalized = name.lower()
    aliases = {
        "roll": RcChannel.ROLL,
        "pitch": RcChannel.PITCH,
        "throttle": RcChannel.THROTTLE,
        "yaw": RcChannel.YAW,
        "aux1": RcChannel.AUX1,
        "aux2": RcChannel.AUX2,
        "aux3": RcChannel.AUX3,
        "aux4": RcChannel.AUX4,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown RC channel: {name}") from exc


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))

from enum import Enum
import time
from typing import Any

from loguru import logger as log

from bt_app.common import NO_RC_CHANNELS
from bt_app.control.pid import PID
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MID,
    RC_MIN,
    RCChannel_alias as RCChannel,
)
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey


class FailSafePhase(Enum):
    HOLD = "hold"
    DESCEND = "descend"
    LANDED = "landed"


class FailSafeController:
    """Hold altitude, descend after timeout, and disarm after land detection."""

    def __init__(self, params: Parameters):
        self.params = params
        self._baseline = float(self.params.get(ParameterKey.HOV_BASELINE))
        self._setpoint = 0.0
        self.phase = FailSafePhase.HOLD
        self._phase_started_s = time.monotonic()
        self._last_update_s = self._phase_started_s
        self._land_candidate_since_s: float | None = None
        self._descent_started_event = False
        self._landed_event = False
        self.hold_time_s = self.params.get(ParameterKey.FS_HOLD_TIME)
        self.descent_rate_m_s = self.params.get(ParameterKey.FS_DESC_RATE)
        self.min_altitude = self.params.get(ParameterKey.FS_MIN_ALT)
        self.land_altitude_m = self.params.get(ParameterKey.FS_LAND_ALT)
        self.land_vertical_speed_m_s = self.params.get(
            ParameterKey.FS_LAND_VSPEED
        )
        self.land_confirm_s = self.params.get(ParameterKey.FS_LAND_CONFIRM)
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self._setup()
        self._banner()

    def _banner(self):
        log.info("--------- FAILSAFE CONTROLLER configuration start-----------")
        log.info(f"descend to land after: {self.hold_time_s} seconds")
        log.info("--------- FAILSAFE CONTROLLER configuration end-----------")

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get(ParameterKey.HOV_KP),
            ki=self.params.get(ParameterKey.HOV_KI),
            kd=self.params.get(ParameterKey.HOV_KD),
            output_limits=self.params.get(ParameterKey.HOV_OUT_LIMIT),
        )

    @property
    def setpoint(self) -> float:
        return self._setpoint

    @setpoint.setter
    def setpoint(self, value: float) -> None:
        log.debug(f"setpoint {value}")
        self._setpoint = max(float(value), float(self.min_altitude))

    @property
    def descent_started(self) -> bool:
        return self.phase in (FailSafePhase.DESCEND, FailSafePhase.LANDED)

    @property
    def landed(self) -> bool:
        return self.phase == FailSafePhase.LANDED

    def reset(self, current_altitude: float) -> None:
        now = time.monotonic()
        self.phase = FailSafePhase.HOLD
        self._phase_started_s = now
        self._last_update_s = now
        self._land_candidate_since_s = None
        self._descent_started_event = False
        self._landed_event = False
        self.setpoint = current_altitude

    def consume_descent_started_event(self) -> bool:
        if not self._descent_started_event:
            return False
        self._descent_started_event = False
        return True

    def consume_landed_event(self) -> bool:
        if not self._landed_event:
            return False
        self._landed_event = False
        return True

    def set_baseline(self, current_throttle: float):
        self._baseline = current_throttle

    def update(self, current_altitude: float, vertical_speed_m_s: float = 0.0):
        now = time.monotonic()
        dt_s = max(0.0, now - self._last_update_s)
        self._last_update_s = now

        if self.phase == FailSafePhase.HOLD:
            self._update_hold_phase(now)
        if self.phase == FailSafePhase.DESCEND:
            self._update_descend_phase(dt_s, current_altitude, vertical_speed_m_s, now)
        if self.phase == FailSafePhase.LANDED:
            return self.make_disarm_channels()

        throttle_output = int(self.alt_pid.update(self._setpoint, current_altitude))
        throttle_output += self._baseline
        return self.make_channels(
            throttle=throttle_output,
            yaw=RC_MID,
        )

    def _update_hold_phase(self, now: float) -> None:
        if float(self.hold_time_s) <= 0.0:
            return
        if now - self._phase_started_s < float(self.hold_time_s):
            return
        log.warning("--------- enter descend to land phase -----------")
        self.phase = FailSafePhase.DESCEND
        self._phase_started_s = now
        self._descent_started_event = True

    def _update_descend_phase(
        self,
        dt_s: float,
        current_altitude: float,
        vertical_speed_m_s: float,
        now: float,
    ) -> None:
        self.setpoint = self._setpoint - float(self.descent_rate_m_s) * dt_s
        if self._is_land_candidate(current_altitude, vertical_speed_m_s):
            if self._land_candidate_since_s is None:
                self._land_candidate_since_s = now
            if now - self._land_candidate_since_s >= float(self.land_confirm_s):
                self.phase = FailSafePhase.LANDED
                self._landed_event = True
            return
        self._land_candidate_since_s = None

    def _is_land_candidate(
        self,
        current_altitude: float,
        vertical_speed_m_s: float,
    ) -> bool:
        return (
            current_altitude <= float(self.land_altitude_m)
            and abs(vertical_speed_m_s) <= float(self.land_vertical_speed_m_s)
        )

    def make_channels(self, throttle: int = 0, yaw: int = 0) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.YAW] = max(RC_MIN, min(RC_MAX, yaw))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        return channels

    def make_disarm_channels(self) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.THROTTLE] = RC_MIN
        channels[RCChannel.ARM] = RC_MIN
        channels[RCChannel.ANGLE] = RC_MAX
        return channels

    def on_parameter_changed(self, name: str, value: Any) -> None:
        log.info("Parameter changed: {} = {}", name, value)
        if name == ParameterKey.HOV_KP:
            self.alt_pid.kp = value
        elif name == ParameterKey.HOV_KI:
            self.alt_pid.ki = value
        elif name == ParameterKey.HOV_KD:
            self.alt_pid.kd = value
        elif name == ParameterKey.HOV_OUT_LIMIT:
            self.alt_pid.set_output_limits(value)
        elif name == ParameterKey.FS_HOLD_TIME:
            self.hold_time_s = value
        elif name == ParameterKey.FS_DESC_RATE:
            self.descent_rate_m_s = value
        elif name == ParameterKey.FS_MIN_ALT:
            self.min_altitude = value
            self.setpoint = self._setpoint
        elif name == ParameterKey.FS_LAND_ALT:
            self.land_altitude_m = value
        elif name == ParameterKey.FS_LAND_VSPEED:
            self.land_vertical_speed_m_s = value
        elif name == ParameterKey.FS_LAND_CONFIRM:
            self.land_confirm_s = value
        elif name == ParameterKey.HOV_BASELINE:
            self._baseline = float(value)

from typing import Any
import time
from bt_app.parameters.generated.keys import ParameterKey
from bt_app.control import PID
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID, 
    RCChannel_alias as RCChannel)
from loguru import logger as log

ALT_REACH_DELTA = 0.5
ALT_SETTLE_VERTICAL_SPEED_MPS = 0.5

class TakeoffController:
    """
    Takeoff to request alt
    """
    def __init__(self, params):
        self.params = params
        self._baseline = float(self.params.get(ParameterKey.HOV_BASELINE))
        self._takeoff_rate_mps = float(
            self.params.get(ParameterKey.TAKEOFF_RATE)
        )
        self._vertical_speed_gain = float(self.params.get(ParameterKey.ALT_KD))
        self._output_limit = abs(float(self.params.get(ParameterKey.ALT_OUT_LIMIT)))
        self.__time_in_alt = 0
        self._last_update_s: float | None = None
        self._setpoint: float | None = None
        self._previous_altitude_m: float | None = None
        self._previous_altitude_time_s: float | None = None
        self._derived_vertical_speed_m_s = 0.0
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self._setup()

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get(ParameterKey.ALT_KP),
            ki=self.params.get(ParameterKey.ALT_KI),
            kd=0.0,
            output_limits=self.params.get(ParameterKey.ALT_OUT_LIMIT)
        )

    # region properties
    @property
    def time_in_alt(self):
        return self.__time_in_alt
    # endregion properties
    # 
    def reset(self):
        self.__time_in_alt = 0
        self._last_update_s = None
        self._setpoint = None
        self._previous_altitude_m = None
        self._previous_altitude_time_s = None
        self._derived_vertical_speed_m_s = 0.0
        self.alt_pid.reset()
        
    @property
    def setpoint(self) -> float | None:
        return self._setpoint
    
    def update(
        self,
        setpoint,
        current,
        altitude_sample_time_s: float | None = None,
    ):
        current_time = time.monotonic()
        sample_time_s = (
            current_time
            if altitude_sample_time_s is None
            else float(altitude_sample_time_s)
        )
        vertical_speed_m_s = self._derive_vertical_speed(current, sample_time_s)
        if self._last_update_s is None or self._setpoint is None:
            dt_s = 0.0
            self._setpoint = float(current)
        else:
            dt_s = max(0.0, current_time - self._last_update_s)

        final_setpoint = float(setpoint)
        maximum_step = self._takeoff_rate_mps * dt_s
        if self._setpoint < final_setpoint:
            self._setpoint = min(final_setpoint, self._setpoint + maximum_step)
        elif self._setpoint > final_setpoint:
            self._setpoint = max(final_setpoint, self._setpoint - maximum_step)

        if (
            abs(setpoint - current) < ALT_REACH_DELTA
            and abs(vertical_speed_m_s) <= ALT_SETTLE_VERTICAL_SPEED_MPS
        ):
            self.__time_in_alt += dt_s
        else:
            self.__time_in_alt = 0
            
        correction = (
            self.alt_pid.update(self._setpoint, current)
            - self._vertical_speed_gain * vertical_speed_m_s
        )
        correction = max(-self._output_limit, min(self._output_limit, correction))
        channels = self.make_channels(int(correction))
        self._last_update_s = current_time
        return channels

    def _derive_vertical_speed(self, altitude_m: float, now_s: float) -> float:
        altitude_m = float(altitude_m)
        if self._previous_altitude_m is None:
            self._previous_altitude_m = altitude_m
            self._previous_altitude_time_s = now_s
            self._derived_vertical_speed_m_s = 0.0
            return 0.0
        previous_time_s = self._previous_altitude_time_s
        if previous_time_s is not None and now_s <= previous_time_s:
            return self._derived_vertical_speed_m_s

        dt_s = 0.0 if previous_time_s is None else now_s - previous_time_s
        if dt_s > 0.0:
            self._derived_vertical_speed_m_s = (
                altitude_m - self._previous_altitude_m
            ) / dt_s
        self._previous_altitude_m = altitude_m
        self._previous_altitude_time_s = now_s
        return self._derived_vertical_speed_m_s

    def make_channels(self, correction: int = 0) -> list[int]:
        channels = [RC_MID] * len(RCChannel)
        throttle = int(self._baseline + correction)
        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        return channels
    
    def on_parameter_changed(self, name: str, value: Any) -> None:
        log.info("Parameter changed: {} = {}", name, value)
        if name == ParameterKey.ALT_KP:
            self.alt_pid.kp = value
        elif name == ParameterKey.ALT_KI:
            self.alt_pid.ki = value
        elif name == ParameterKey.ALT_KD:
            self._vertical_speed_gain = float(value)
        elif name == ParameterKey.ALT_OUT_LIMIT:
            self._output_limit = abs(float(value))
            self.alt_pid.set_output_limits(value)
        elif name == ParameterKey.TAKEOFF_RATE:
            self._takeoff_rate_mps = float(value)
        elif name == ParameterKey.HOV_BASELINE:
            self._baseline = float(value)

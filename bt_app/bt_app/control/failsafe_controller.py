from typing import Any

from loguru import logger as log
from bt_app.common import NO_RC_CHANNELS
from bt_app.control.pid import PID

# from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MID,
    RC_MIN,
)
from bt_app.msp.bt_v2 import (
    RCChannel_alias as RCChannel,
)
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey

class FailSafeController:
    """FS logic is Hold altitude the same pid like hover without yaw control."""

    def __init__(self, params: Parameters):
        self.params = params
        self._baseline = 0.0
        self._setpoint = 0.0
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self._setup()

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get(ParameterKey.HOVER_KP),
            ki=self.params.get(ParameterKey.HOVER_KI),
            kd=self.params.get(ParameterKey.HOVER_KD),
            output_limits=self.params.get(ParameterKey.HOVER_OUTPUT_LIMITS),
        )

    #region Properties
    @property
    def setpoint(self) -> float:
        return self._setpoint
    
    @setpoint.setter
    def setpoint(self, value: float) -> None:
        log.info(f"setpoint {value}")
        self._setpoint = value
    # endregion

    def set_baseline (self, current_throttle: float):
        self._baseline = current_throttle

    def update(self, setpoint, current):
        """ """
        throttle_output = int(self.alt_pid.update(setpoint, current))
        throttle_output += self._baseline
        channels = self.make_channels(
            throttle=throttle_output,
            yaw=RC_MID,
        )

        return channels

    def make_channels(self, throttle: int = 0, yaw: int = 0) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS

        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.YAW] = max(RC_MIN, min(RC_MAX, yaw))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX

        return channels

    def on_parameter_changed(self, name: str, value: Any) -> None:
        log.info("Parameter changed: {} = {}", name, value)
        if name == ParameterKey.HOVER_KP:
            self.alt_pid.kp = value
        elif name == ParameterKey.HOVER_KI:
            self.alt_pid.ki = value
        elif name == ParameterKey.HOVER_KD:
            self.alt_pid.kd = value
        elif name == ParameterKey.HOVER_OUTPUT_LIMITS:
            self.alt_pid.set_output_limits(value)
        elif name == ParameterKey.HOVER_YAW_YAW_RATE:
            self.yaw_rate = value
        elif name == ParameterKey.BETAFLIGHT_YAW_RATE_FULL_STICK_DPS:
            self.yaw_stick_range = value
            self.rc_mapper.yaw_rate_full_stick_dps = value

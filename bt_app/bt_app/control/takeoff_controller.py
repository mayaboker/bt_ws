from typing import Any

from bt_app.control import PID
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID, 
    RCChannel_alias as RCChannel)
from loguru import logger as log

class TakeoffController:
    def __init__(self):
        # self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        # self._setup()
        self.alt_pid = PID(50,10,0)

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get("altitude.kp"),
            ki=self.params.get("altitude.ki"),
            kd=self.params.get("altitude.kd"),
            output_limits=self.params.get("altitude.output_limits")
        )

    def update(self, setpoint, current):
        output = self.alt_pid.update(setpoint, current)
        channels = self.make_channels(int(output))
        return channels

    def make_channels(self, throttle: int = 0) -> list[int]:
        channels = [RC_MID] * len(RCChannel)
        throttle = RC_MID + throttle
        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.ARM] = RC_MAX
        channels[RCChannel.ANGLE] = RC_MAX
        return channels
    
    def on_parameter_changed(self, name: str, value: Any) -> None:
        log.info("Parameter changed: {} = {}", name, value)
        if name == "altitude.kp":
            self.alt_pid.kp = value
        elif name == "altitude.ki":
            self.alt_pid.ki = value
        elif name == "altitude.kd":
            self.alt_pid.kd = value
        elif name == "altitude.output_limits":
            self.alt_pid.set_output_limits(value)



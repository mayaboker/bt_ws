from typing import Any

from bt_app.control import PID
from bt_app.parameters import Parameters
from bt_app.bt_app.context_old import Context
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID, 
    RCChannel_alias as RCChannel)
from bt_app.common import State, FREQ_HZ
from loguru import logger as log

class TakeoffController:
    def __init__(self, context: Context, params: Parameters):
        self.context = context
        self.params = params
        self.enable = False
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self.context.on_state_changed += self.on_state_changed
        self.context.on_control_tick += self.tick
        self._setup()

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get("altitude.kp"),
            ki=self.params.get("altitude.ki"),
            kd=self.params.get("altitude.kd"),
            output_limits=self.params.get("altitude.output_limits")
        )

    def tick(self):
        self.update()

    def update(self):
        if self.enable is False:
            return
        altitude = self.context.msp.last_altitude
        if altitude is None:
            log.warning("No altitude data available")
            return
        current_altitude_m = float(altitude.get("altitude_m", 0.0))
        self.context.set_current_altitude(current_altitude_m)
        target_altitude_m = self.params.get("takeoff_altitude")
        output = self.alt_pid.update(target_altitude_m, current_altitude_m)
        channels = self.make_channels(int(output))
        self.context.msp.set_rc(channels, rate_hz=FREQ_HZ)

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

    def on_state_changed(self, state: State) -> None:
        self.enable = state in [State.TAKEOFF, State.LAND]

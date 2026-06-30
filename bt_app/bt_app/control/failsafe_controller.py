from typing import Any

from loguru import logger as log

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


class FailSafeController:
    """FS logic is Hold altitude ."""

    def __init__(self, params: Parameters):
        self.params = params
        self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self._setup()

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get("altitude.kp"),
            ki=self.params.get("altitude.ki"),
            kd=self.params.get("altitude.kd"),
            output_limits=self.params.get("altitude.output_limits"),
        )

    def update(self, setpoint, current):
        """ """
        throttle_output = int(self.alt_pid.update(setpoint, current))
        channels = self.make_channels(
            throttle=throttle_output,
            yaw=RC_MID,
        )

        return channels

    def make_channels(self, throttle: int = 0, yaw: int = 0) -> list[int]:
        channels = [RC_MID] * 8
        throttle = RC_MID + int(throttle)

        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.YAW] = max(RC_MIN, min(RC_MAX, yaw))
        channels[RCChannel.ARM] = RC_MAX

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

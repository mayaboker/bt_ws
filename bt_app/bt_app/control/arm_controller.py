from typing import Any

import time
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID, 
    RCChannel_alias as RCChannel)
from loguru import logger as log

DISABLED_HOLD_TIME = 1.0

class ARMController:
    def __init__(self):
        # self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self.__time = None

    def reset(self):
        self.__time = time.monotonic()
    
    def update(self, ):
        delta = time.monotonic() - self.__time
        if delta < DISABLED_HOLD_TIME:
            return self.make_channels(throttle=RC_MIN, arm=RC_MIN)
        else:
            return self.make_channels(throttle=RC_MIN, arm=RC_MAX)

    def make_channels(self, throttle: int = RC_MIN, arm: int = RC_MIN) -> list[int]:
        channels = [RC_MID] * len(RCChannel)
        channels[RCChannel.THROTTLE] = throttle
        channels[RCChannel.ARM] = arm
        channels[RCChannel.ANGLE] = RC_MAX

        return channels
        
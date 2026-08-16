"""
implement MSP arm sequence
"""
#region imports
import time
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID, 
    RCChannel_alias as RCChannel)
from loguru import logger as log
#endregion

DISABLED_HOLD_TIME = 1.0
ARM_HOLD_TIME = 2.0

class ARMController:
    """
    Run betaflight arm sequence
    - set ARM and THROTTLE to low for 1 sec
    - set ARM to RC_MAX and THROTTL to low
    """
    def __init__(self, params):
        # self.params.on_parameter_changed.subscribe(self.on_parameter_changed)
        self.__time = time.monotonic()
        self._armed_process_done = False

    @property
    def is_arm_done(self):
        return self._armed_process_done

    def reset(self):
        self.__time = time.monotonic()
        self._armed_process_done = False
    
    def update(self):
        delta = time.monotonic() - self.__time
        if delta < DISABLED_HOLD_TIME:
            return self.make_channels(throttle=RC_MIN, arm=RC_MIN)
        elif DISABLED_HOLD_TIME < delta < ARM_HOLD_TIME+DISABLED_HOLD_TIME:
            return self.make_channels(throttle=RC_MIN, arm=RC_MAX)
        else:
            self._armed_process_done = True
            return self.make_channels(throttle=RC_MIN, arm=RC_MAX)

    def make_channels(self, throttle: int = RC_MIN, arm: int = RC_MIN) -> list[int]:
        channels = [RC_MID] * len(RCChannel)
        channels[RCChannel.THROTTLE] = throttle
        channels[RCChannel.ARM] = arm
        channels[RCChannel.ANGLE] = RC_MAX

        return channels
        
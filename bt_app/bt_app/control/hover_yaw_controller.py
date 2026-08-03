from typing import Any
import time

from loguru import logger as log

from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.control.pid import PID
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN,
    RC_MID,
    RCChannel_alias as RCChannel,
)
from bt_app.common import NO_RC_CHANNELS
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey

class HoverYawController:
    """Hold altitude and command a slow constant yaw maneuver."""

    def __init__(self, params: Parameters):
        self.params = params
        self._baseline = float(self.params.get(ParameterKey.HOV_BASELINE))
        self._setpoint = 0.0
        self.altitude_rate_m_s = self.params.get(ParameterKey.HOV_ALT_RATE)
        self.throttle_deadband = self.params.get(ParameterKey.HOV_THR_DB)
        self.min_altitude = self.params.get(ParameterKey.HOV_MIN_ALT)
        self.yaw_rate = 0.0
        self.max_yaw_rate_dps = self.params.get(ParameterKey.HY_MAX_RATE)
        self.yaw_deadband = self.params.get(ParameterKey.HY_DEADBAND)
        self.yaw_expo = self.params.get(ParameterKey.HY_EXPO)
        self.yaw_stick_range = self.params.get(ParameterKey.BF_YAW_RATE)
        self._last_setpoint_update_s = time.monotonic()
        self._throttle_outside_deadband = False
        self._altitude_setpoint_request_event = False
        self.rc_mapper = BetaflightRcMapper(
            yaw_rate_full_stick_dps=self.yaw_stick_range,
        )
        self._setup()

    def _setup(self):
        self.alt_pid = PID(
            kp=self.params.get(ParameterKey.HOV_KP),
            ki=self.params.get(ParameterKey.HOV_KI),
            kd=self.params.get(ParameterKey.HOV_KD),
            output_limits=self.params.get(ParameterKey.HOV_OUT_LIMIT),
        )
        
        log.info("HoverYawController initialized with PID: \n" \
                "Kp={}, Ki={}, Kd={}, ", 
                 self.alt_pid.kp, 
                 self.alt_pid.ki, 
                 self.alt_pid.kd)

    @property
    def setpoint(self) -> float:
        return self._setpoint
    
    @setpoint.setter
    def setpoint(self, value: float) -> None:
        log.debug(f"setpoint {value}")
        self._setpoint = max(float(value), float(self.min_altitude))

    def reset_setpoint(self, current_altitude: float) -> None:
        self.setpoint = current_altitude
        self._last_setpoint_update_s = time.monotonic()
        self._throttle_outside_deadband = False
        self._altitude_setpoint_request_event = False

    def consume_altitude_setpoint_request_event(self) -> bool:
        if not self._altitude_setpoint_request_event:
            return False
        self._altitude_setpoint_request_event = False
        return True

    def update_setpoint_from_throttle(self, throttle_rc: int) -> float:
        """Adjust the altitude setpoint from a centered throttle command.

        Values inside the throttle deadband leave the setpoint unchanged. Values
        outside it are normalized to ``[-1, 1]`` and integrated over elapsed time
        at ``altitude_rate_m_s``. An event is raised once when the stick first
        leaves the deadband so consumers can react to a new altitude request.
        """

        now = time.monotonic()
        dt_s = max(0.0, now - self._last_setpoint_update_s)
        self._last_setpoint_update_s = now

        throttle = int(throttle_rc)
        center = RC_MID
        deadband = int(self.throttle_deadband)
        upper_deadband = center + deadband // 2
        lower_deadband = center - deadband // 2

        if throttle > upper_deadband:
            denominator = max(1, RC_MAX - upper_deadband)
            stick_fraction = min(1.0, (throttle - upper_deadband) / denominator)
        elif throttle < lower_deadband:
            denominator = max(1, lower_deadband - RC_MIN)
            stick_fraction = -min(1.0, (lower_deadband - throttle) / denominator)
        else:
            self._throttle_outside_deadband = False
            return self._setpoint

        if not self._throttle_outside_deadband:
            self._altitude_setpoint_request_event = True
        self._throttle_outside_deadband = True
        self.setpoint = self._setpoint + stick_fraction * float(self.altitude_rate_m_s) * dt_s
        return self._setpoint

    def update_yaw_from_joystick(self, yaw_rc: int) -> float:
        yaw = int(yaw_rc)
        deadband = int(self.yaw_deadband)
        upper_deadband = RC_MID + deadband
        lower_deadband = RC_MID - deadband

        if yaw > upper_deadband:
            denominator = max(1, RC_MAX - upper_deadband)
            linear = min(1.0, (yaw - upper_deadband) / denominator)
        elif yaw < lower_deadband:
            denominator = max(1, lower_deadband - RC_MIN)
            linear = -min(1.0, (lower_deadband - yaw) / denominator)
        else:
            self.yaw_rate = 0.0
            return self.yaw_rate

        expo = max(0.0, min(float(self.yaw_expo), 1.0))
        command = linear * (1.0 - expo) + (linear**3) * expo
        self.yaw_rate = command * float(self.max_yaw_rate_dps)
        return self.yaw_rate
    
    def update_pitch_roll(self, pitch, roll):
        self._pitch = pitch
        self._roll = roll

    def set_baseline (self, current_throttle: float):
        self._baseline = current_throttle


    def update(self, setpoint: float, current: float):
        """
        if controller is not enabled, do nothing. On first run, initialize hover altitude from current altitude.
         Then read current altitude, compute throttle output from PID, compute yaw output from yaw_rate parameter, and send RC commands to MSP.
        """
        throttle_output = int(self.alt_pid.update(setpoint, current))
        throttle_output += self._baseline
        
        rc_yaw = self.rc_mapper.yaw_rate_to_rc(self.yaw_rate)

        # keep altitude/throttle and send yaw command
        channels = self.make_channels(
            throttle=throttle_output,
            yaw=rc_yaw,
        )

        return channels

    def make_channels(self, throttle: int = 0, yaw: int = 0) -> list[int]:
        channels = [RC_MID] * NO_RC_CHANNELS
        channels[RCChannel.ROLL] = self._roll
        channels[RCChannel.PITCH] = self._pitch
        channels[RCChannel.THROTTLE] = max(RC_MIN, min(RC_MAX, throttle))
        channels[RCChannel.YAW] = max(RC_MIN, min(RC_MAX, yaw))
        channels[RCChannel.ARM] = RC_MAX
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
        elif name == ParameterKey.HOV_ALT_RATE:
            self.altitude_rate_m_s = value
        elif name == ParameterKey.HOV_THR_DB:
            self.throttle_deadband = value
        elif name == ParameterKey.HOV_MIN_ALT:
            self.min_altitude = value
            self.setpoint = self._setpoint
        elif name == ParameterKey.HY_MAX_RATE:
            self.max_yaw_rate_dps = value
        elif name == ParameterKey.HY_DEADBAND:
            self.yaw_deadband = value
        elif name == ParameterKey.HY_EXPO:
            self.yaw_expo = value
        elif name == ParameterKey.BF_YAW_RATE:
            self.yaw_stick_range = value
            self.rc_mapper.yaw_rate_full_stick_dps = value
        elif name == ParameterKey.HOV_BASELINE:
            self._baseline = float(value)

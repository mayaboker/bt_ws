"""
Hold drone state
The context is a singleton class that holds the current state of the drone. It is used by the state machine to determine the next state based on the current state and the events that occur.
"""
from bt_app.common import RobotState
from dataclasses import dataclass, field
from typing import ClassVar
from bt_app.common import AutoModeType, InternalJoy, AETR1234, InternalJoystick
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MID,
    RC_MIN,
)
DEFAULT_RC_CHANNELS = [RC_MIN] * len(AETR1234)
INPUT_RC_CHANNELS = [RC_MIN] * len(InternalJoy)

@dataclass(init=False)
class Context:
    # current state machine state update when state changed
    state: RobotState = field(default=RobotState.IDLE)
    # true: if joy request arm combination, reset when disarmed or arm failed
    joy_arm_requested: bool = field(default=False)
    joy_glide_request: bool = field(default=False)
    # drone state arm disabled update at 1hz
    arming_disable_flags: list = field(default_factory=list)
    # drone state - if drone can armed update at 1hz
    armable: bool = field(default=False)
    # is drone armed update 1hz
    armed: bool = field(default=False)

    # joystick network connection lost, if true enter failsafe
    joy_fail_safe: bool = field(default=False)
    take_control: bool = field(default=False)
    # allow automatic arm without joy AUX1 set to high
    auto_arm: bool = field(default=False)
    # is takeoff reach alt and wait (stabilize)
    takeoff_reach: bool = field(default=False)
    takeoff_setpoint: float = field(default=0)
    manual_land_confirmed: bool = field(default=False)
    glide_landed: bool = field(default=False)
    # Current altitude and vertical speed, updated from MSP at 20 Hz.
    drone_alt: float = 0.0
    drone_vertical_speed: float = 0.0
    drone_alt_received_at_s: float = 0.0
    drone_roll_deg: float = 0.0
    drone_pitch_deg: float = 0.0
    drone_heading_deg: float = 0.0
    #current rc read from drone (use to switch between external and internal pilot and controller switch)
    drone_rc: list = field(default_factory=lambda: DEFAULT_RC_CHANNELS.copy())
    # last joystick rc state (input)
    request_rc: InternalJoystick
    sent_rc: list = field(default_factory=lambda: DEFAULT_RC_CHANNELS.copy())
    battery_voltage: float = 0.0
    # auto mode state 
    auto_mode_type: AutoModeType = field(default=AutoModeType.DISABLED)
    # altitude request setpoint use (takeoff, alt_hold)
    alt_setpoint: float = 0.0
    glide_velocity_setpoint: float = 0.0
    target_distance_m: float | None = None
    glide_phase: str = "idle"
    glide_abort_reason: str | None = None
    glide_ready: bool = False
    glide_control_result: object | None = None

    # auto mode enable
    auto_mode_enable: bool = field(default=False)

    def is_low_throttle(self):
        return self.request_rc[InternalJoy.THROTTLE] < 1050

    # region singleton
    _instance: ClassVar["Context | None"] = None
    _initialized: ClassVar[bool] = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.state = RobotState.IDLE
        self.joy_arm_requested = False
        self.joy_glide_request = False
        self.arming_disable_flags = []
        self.armable = False
        self.armed = False
        self.joy_fail_safe = False
        self.take_control = False
        self.auto_arm = False
        self.takeoff_reach = False
        self.manual_land_confirmed = False
        self.glide_landed = False
        self.drone_alt = 0.0
        self.drone_vertical_speed = 0.0
        self.drone_alt_received_at_s = 0.0
        self.drone_roll_deg = 0.0
        self.drone_pitch_deg = 0.0
        self.drone_heading_deg = 0.0
        self.drone_rc = DEFAULT_RC_CHANNELS.copy()
        self.request_rc = InternalJoystick()
        self.sent_rc = DEFAULT_RC_CHANNELS.copy()
        self.battery_voltage = 0.0
        self.auto_mode_type = AutoModeType.DISABLED
        self.auto_mode_enable = False
        self._initialized = True
        self.takeoff_setpoint = 0.0
        self.alt_setpoint = 0.0
        self.glide_velocity_setpoint = 0.0
        self.target_distance_m = None
        self.glide_phase = "idle"
        self.glide_abort_reason = None
        self.glide_ready = False
        self.glide_control_result = None
    # endregion

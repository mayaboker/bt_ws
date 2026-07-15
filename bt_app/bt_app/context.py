"""
Hold drone state
The context is a singleton class that holds the current state of the drone. It is used by the state machine to determine the next state based on the current state and the events that occur.
"""
from bt_app.common import RobotState
from dataclasses import dataclass, field
from typing import ClassVar
from bt_app.common import AutoModeType

DEFAULT_RC_CHANNELS = [1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000]

@dataclass(init=False)
class Context:
    # current state machine state update when state changed
    state: RobotState = field(default=RobotState.IDLE)
    joy_takeoff_request: bool = field(default=False)
    joy_manual_request: bool = field(default=False)
    # true: if joy request arm combination, reset when disarmed or arm failed
    joy_arm_requested: bool = field(default=False)
    # drone state arm disabled update at 1hz
    arming_disable_flags: list = field(default_factory=list)
    # drone state - if drone can armed update at 1hz
    armable: bool = field(default=False)
    # is drone armed update 1hz
    armed: bool = field(default=False)
    # flag true: if we make the arm sequence
    armed_allowed: bool = field(default=False)
    # joystick network connection lost, if true enter failsafe
    joy_fail_safe: bool = field(default=False)
    take_control: bool = field(default=False)
    # allow automatic arm without joy AUX1 set to high
    auto_arm: bool = field(default=False)
    # is takeoff reach alt and wait (stabilize)
    takeoff_reach: bool = field(default=False)
    # current drone alt , update from drone at 10hz
    drone_alt: float = 0.0
    #current rc read from drone (use to switch between external and internal pilot and controller switch)
    drone_rc: list = field(default_factory=list)
    request_rc: list = field(default_factory=list)
    sent_rc: list = field(default_factory=list)
    battery_voltage: float = 0.0
    # auto mode state 
    auto_mode_type: AutoModeType = field(default=AutoModeType.DISABLED)



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
        self.joy_takeoff_request = False
        self.joy_manual_request = False
        self.joy_arm_requested = False
        self.arming_disable_flags = []
        self.armable = False
        self.armed = False
        self.armed_allowed = False
        self.joy_fail_safe = False
        self.take_control = False
        self.auto_arm = False
        self.takeoff_reach = False
        self.drone_alt = 0.0
        self.drone_rc = DEFAULT_RC_CHANNELS
        self.request_rc = DEFAULT_RC_CHANNELS
        self.sent_rc = DEFAULT_RC_CHANNELS
        self.battery_voltage = 0.0
        self.auto_mode_type = AutoModeType.DISABLED
        self._initialized = True
    # endregion

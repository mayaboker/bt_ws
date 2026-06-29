"""
Hold drone state
The context is a singleton class that holds the current state of the drone. It is used by the state machine to determine the next state based on the current state and the events that occur.
"""
from bt_app.common import RobotState
from dataclasses import dataclass, field


@dataclass(init=False)
class Context:
    # current state machine state update when state changed
    state: RobotState = field(default=RobotState.IDLE.value)
    force_manual_mode: bool = field(default=False)
    # drone state arm disabled update at 1hz
    arming_disable_flags: list = field(default_factory=list)
    # drone state arm state update at 1hz
    armable: bool = field(default=False)
    joy_fail_safe: bool = field(default=False)
    takeoff_interrupt: bool = field(default=False)
    force_manual_interrupt: bool = field(default=False)
    
    # current drone alt , update from drone at 10hz
    drone_alt: float = 0.0
    #current rc read from drone (use to switch between external and internal pilot and controller switch)
    drone_rc: list = field(default_factory=list)



    # region singleton
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
    # endregion
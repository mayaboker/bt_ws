"""
Hold drone state
The context is a singleton class that holds the current state of the drone. It is used by the state machine to determine the next state based on the current state and the events that occur.
"""
from bt_app.common import RobotState
from dataclasses import dataclass, field


@dataclass(init=False)
class Context:
    state: RobotState = field(default=RobotState.MANUAL)
    force_manual_mode: bool = field(default=True)

    # region singleton
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self.state = RobotState.MANUAL
            self._initialized = True
    # endregion
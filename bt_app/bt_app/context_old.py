import time

from bt_app.msp.command_dispatcher import MspCommandDispatcher
from bt_app.common import Event
from bt_app.common import State
from bt_app.msgs import TrackerResult, TrackerState


class Context:
    def __init__(self, msp: MspCommandDispatcher) -> None:
        self.msp: MspCommandDispatcher = msp
        self.state = State.DISARMED
        self.on_state_changed = Event()
        self.on_lidar_range_changed = Event()
        self.on_tracker_result_changed = Event()
        self.on_tracker_state_changed = Event()
        self.on_control_tick = Event()

        self.current_altitude_m = 0.0
        self.front_lidar_range_m = None
        self.last_lidar_range_time = None
        self.tracker_results: dict[str, TrackerResult] = {}
        self.tracker_states: dict[str, TrackerState] = {}
        self.last_tracker_result_time: dict[str, float] = {}

    def tick_control(self) -> None:
        self.on_control_tick.emit()

    def set_current_altitude(self, altitude_m: float) -> None:
        self.current_altitude_m = altitude_m

    def set_lidar_range(self, range_m: float | None, metadata: dict | None = None) -> None:
        self.front_lidar_range_m = range_m
        self.last_lidar_range_time = time.monotonic()
        self.on_lidar_range_changed.emit(range_m, metadata)

    def set_tracker_result(self, result: TrackerResult) -> None:
        tracker_id = result.tracker_id or "default"
        previous_state = self.tracker_states.get(tracker_id)

        self.tracker_results[tracker_id] = result
        self.tracker_states[tracker_id] = result.state
        self.last_tracker_result_time[tracker_id] = time.monotonic()
        self.on_tracker_result_changed.emit(result)

        if previous_state != result.state:
            self.on_tracker_state_changed.emit(result, previous_state)
        
    def set_state(self, state: State) -> None:
        if self.state != state:
            self.state = state
            self.on_state_changed.emit(state)

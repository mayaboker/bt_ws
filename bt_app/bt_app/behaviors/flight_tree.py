from __future__ import annotations

import time

import py_trees
from loguru import logger

from bt_app.msgs import TrackerState
from bt_app.parameters.parameters import Parameters
from bt_app.msp.command_dispatcher import MspCommandDispatcher

from bt_app.context import Context
from bt_app import FREQ_HZ
from bt_app.common import State

DISARMED_RC = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)
ARMED_LOW_THROTTLE_RC = (1500, 1500, 1000, 1500, 1900, 1000, 1000, 1000)
TAKEOFF_RC = (1500, 1500, 1300, 1500, 1900, 1000, 1000, 1000)
HOVER_BASE_RC = (1500, 1500, 1200, 1500, 1900, 1000, 1000, 1000)
BB_TARGET_ALTITUDE_KEY = "/flight/target_altitude_m"
BB_CURRENT_ALTITUDE_KEY = "/flight/current_altitude_m"
BB_FRONT_LIDAR_RANGE_KEY = "/sensors/front_lidar_range_m"
BB_IS_RUNNING_KEY = "application/running"


class WaitArmable(py_trees.behaviour.Behaviour):
    def __init__(self, dispatcher: MspCommandDispatcher) -> None:
        super().__init__(name="Wait Armable")
        self.dispatcher = dispatcher

    def update(self) -> py_trees.common.Status:
        state = self.dispatcher.last_state
        if state is None:
            self.feedback_message = "waiting for state"
            return py_trees.common.Status.RUNNING

        if state.get("calibrating"):
            self.feedback_message = "calibrating"
            return py_trees.common.Status.RUNNING

        blocking_flags = set(state.get("arming_disable_flags", []))
        allowed_before_arm = {
            "THROTTLE",
            "ARM_SWITCH",
            "ARMING_DISABLED_ARM_SWITCH",
            "NOT_DISARMED",
        }
        hard_blocks = blocking_flags - allowed_before_arm
        if hard_blocks:
            self.feedback_message = f"blocked: {sorted(hard_blocks)}"
            return py_trees.common.Status.RUNNING

        return py_trees.common.Status.SUCCESS


class TimedRcCommand(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        name: str,
        dispatcher: MspCommandDispatcher,
        channels: tuple[int, int, int, int, int, int, int, int],
        duration_s: float,
        rate_hz: float = 50.0,
    ) -> None:
        super().__init__(name=name)
        self.dispatcher = dispatcher
        self.channels = channels
        self.duration_s = duration_s
        self.rate_hz = rate_hz
        self._end_time: float | None = None

    def initialise(self) -> None:
        self._end_time = time.monotonic() + self.duration_s
        self.dispatcher.set_rc(self.channels, rate_hz=self.rate_hz)
        logger.info("{} started", self.name)

    def update(self) -> py_trees.common.Status:
        if self._end_time is None:
            return py_trees.common.Status.FAILURE

        if time.monotonic() < self._end_time:
            return py_trees.common.Status.RUNNING

        logger.info("{} complete", self.name)
        return py_trees.common.Status.SUCCESS


class TakeoffUntilAltitude(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        context: Context,
        params: Parameters
    ) -> None:
        super().__init__(name="Takeoff To Target Altitude")
        self.bb = self.attach_blackboard_client(name="reader")
        self.bb.register_key(BB_TARGET_ALTITUDE_KEY, access=py_trees.common.Access.READ)
        self.bb.register_key(BB_CURRENT_ALTITUDE_KEY, access=py_trees.common.Access.READ)
        self.ctx = context
        self.params = params

    def initialise(self) -> None:
        self.ctx.set_state(State.TAKEOFF)
        logger.info("Takeoff command started")

    def update(self) -> py_trees.common.Status:
        # self.feedback_message = f"{altitude_m:.2f}m, {error_m:.2f}m error, throttle {channels[RCChannel.THROTTLE]}"
        # if altitude_m >= target_altitude_m:
        #     logger.info("Reached takeoff altitude: {:.2f}m", altitude_m)
        #     return py_trees.common.Status.SUCCESS
        current_alt = self.bb.get(BB_CURRENT_ALTITUDE_KEY)
        target_alt = self.bb.get(BB_TARGET_ALTITUDE_KEY)
        self.feedback_message = f"{current_alt:.2f}m / {target_alt:.2f}m"
        if current_alt >= target_alt:
            logger.info("Reached takeoff altitude: {:.2f}m", current_alt)
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING

class FinalTrack(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        context: Context,
        params: Parameters
    ) -> None:
        super().__init__(name="Final Track")
        self.ctx = context
        self.params = params


    def initialise(self) -> None:
        self.ctx.set_state(State.FINAL)
        logger.info("Final track command started")

    def update(self) -> py_trees.common.Status:
        return py_trees.common.Status.RUNNING

class Land(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        context: Context,
        params: Parameters
    ) -> None:
        super().__init__(name="Land At Target Altitude")
        self.ctx = context
        self.params = params


    def initialise(self) -> None:
        self.ctx.set_state(State.LAND)
        self.params.set("takeoff_altitude", 0.0) # TODO this is a bit hacky, should have a separate landing altitude parameter
        logger.info("Land command started")

    
    def update(self) -> py_trees.common.Status:
        return py_trees.common.Status.RUNNING

class Search(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        context: Context,
        params: Parameters
    ) -> None:
        super().__init__(name="Search")
        self.ctx = context
        self.params = params


    def initialise(self) -> None:
        self.ctx.set_state(State.SEARCH)
        logger.info("Search command started")

    def update(self) -> py_trees.common.Status:
        # TODO: set ATR tracking name from params
        if self.ctx.tracker_results["red_box"].state == TrackerState.TRACKING:
            logger.info("Target acquired, switching to visual track")
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class VisualTrack(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        context: Context,
        params: Parameters
    ) -> None:
        super().__init__(name="Visual Track")
        self.bb = self.attach_blackboard_client(name="visual_track_reader")
        self.bb.register_key(BB_FRONT_LIDAR_RANGE_KEY, access=py_trees.common.Access.READ)
        self.ctx = context
        self.params = params
        self.timeout_param = "visual.tracking_timeout_s"
        if self.timeout_param not in self.params.list():
            self.params.declare(self.timeout_param, 30.0, {"min": 0.0}, float)
        self._end_time: float | None = None


    def initialise(self) -> None:
        self.ctx.set_state(State.VISUAL_TRACK)
        self._end_time = time.monotonic() + float(self.params.get(self.timeout_param))
        logger.info("Visual track command started")

    
    def update(self) -> py_trees.common.Status:
        front_lidar_range_m = self.bb.get(BB_FRONT_LIDAR_RANGE_KEY)
        final_tracking_distance_m = self.params.get("visual.final_tracking_distance")

        if front_lidar_range_m is not None and front_lidar_range_m <= final_tracking_distance_m:
            logger.info(
                "Reached final tracking distance: {:.2f}m <= {:.2f}m",
                front_lidar_range_m,
                final_tracking_distance_m,
            )
            return py_trees.common.Status.SUCCESS

        if self._end_time is not None and time.monotonic() >= self._end_time:
            self.feedback_message = "visual tracking timed out"
            logger.warning("Visual tracking timed out")
            return py_trees.common.Status.FAILURE

        if front_lidar_range_m is None:
            self.feedback_message = "waiting for front lidar"
        else:
            self.feedback_message = f"{front_lidar_range_m:.2f}m / {final_tracking_distance_m:.2f}m"
        return py_trees.common.Status.RUNNING
    

def create_app_tree(
    context: Context,
    params: Parameters
) -> py_trees.trees.BehaviourTree:
    root = py_trees.composites.Sequence(name="Arm Takeoff Hover", memory=True)
    root.add_children(
        [
            TimedRcCommand(
                name="Disarmed Neutral",
                dispatcher=context.msp,
                channels=DISARMED_RC,
                duration_s=2.0,
            ),
            TimedRcCommand(
                name="Arm Low Throttle",
                dispatcher=context.msp,
                channels=ARMED_LOW_THROTTLE_RC,
                duration_s=2.0,
            ),
            TakeoffUntilAltitude(
                context=context,
                params=params
            ),
            Search(
                context=context,
                params=params
            ),
            VisualTrack(
                context=context,
                params=params
            ),
            FinalTrack(
                context=context,
                params=params
            )
        ]
    )
    return py_trees.trees.BehaviourTree(root)

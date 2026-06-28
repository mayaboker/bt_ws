from __future__ import annotations

import argparse
import time

import py_trees

from bt_app.behaviors import create_app_tree
from bt_app.behaviors.flight_tree import (BB_CURRENT_ALTITUDE_KEY, BB_FRONT_LIDAR_RANGE_KEY,
                                          BB_TARGET_ALTITUDE_KEY, 
                                          BB_IS_RUNNING_KEY)
from bt_app.common import FREQ_HZ, TREE_TICK_INTERVAL_S
from bt_app.msp import BetaflightMspClient, TcpMspTransport
from bt_app.msp.command_dispatcher import MspCommandDispatcher
from bt_app.parameters import Parameters
from loguru import logger as log
from bt_app.bt_app.context_old import Context
from bt_app.control import TakeoffController, HoverYawController
from bt_app.control.visual_controller import VisualTrackerManager
from bt_app.sensors.sim_senors import SimSensors
from bt_app.telemetry import Telemetry

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BT application")
    parser.add_argument(
        "--params-yaml",
        required=False,
        default="/workspace/bt_app/config/parameter_storage_example.yaml",
        help="Path to the application parameter YAML file.",
    )
    parser.add_argument(
        "--param-endpoint",
        default="tcp://127.0.0.1:5555",
        help="ZMQ REP endpoint for parameter commands.",
    )
    parser.add_argument(
        "--msp-host",
        default="127.0.0.1",
        help="Betaflight MSP TCP host.",
    )
    parser.add_argument(
        "--msp-port",
        type=int,
        default=5761,
        help="Betaflight MSP TCP port.",
    )
    parser.add_argument(
        "--target-altitude",
        type=float,
        default=5.0,
        help="Target hover altitude in meters.",
    )
    return parser



class App():
    def __init__(self):
        args = build_parser().parse_args()
        log.info("Starting BT application")
        self.dispatcher = None
        self.msp = None
        self.sim_sensors = None
        self.telemetry = None
        self.parameters = Parameters(
            yaml_path=args.params_yaml,
            endpoint=args.param_endpoint,
        )

        transport = TcpMspTransport(args.msp_host, args.msp_port)
        self.msp = BetaflightMspClient(transport)
        self.msp.open()

        self.dispatcher = MspCommandDispatcher(
            self.msp,
            on_error=lambda exc: log.error("MSP dispatcher error: {}", exc),
        )
        self.dispatcher.schedule_state(interval_s=1.0)
        self.dispatcher.schedule_altitude(interval_s=0.1)

        self.context = Context(self.dispatcher)
        self.sim_sensors = SimSensors()
        self.sim_sensors.on_lidar_range += self.context.set_lidar_range
        self.telemetry = Telemetry(
            context=self.context,
        )
        self.telemetry.start()
        self.dispatcher.start()
        self.sim_sensors.start()

        self.bb = init_blackboard()
        self.tree = create_app_tree(context=self.context, params=self.parameters)
        self.tree.pre_tick_handlers.append(self.pre_tick_handler)

        self.takeoff_controller = TakeoffController(self.context, self.parameters)
        self.hover_yaw_controller = HoverYawController(self.context, self.parameters)
        self.hover_yaw_controller.start()
        self.visual_track_controller = VisualTrackerManager(self.context, self.parameters)
        self.visual_track_controller.start()

    def pre_tick_handler(self, tree):
        """
        update blackboard values before each tick of the behavior tree. This ensures that the latest sensor data and parameters are available to the behaviors when they execute.
        """
        # Update blackboard values from context or dispatcher
        self.bb.set(BB_TARGET_ALTITUDE_KEY, self.parameters.get("takeoff_altitude"))
        self.bb.set(BB_CURRENT_ALTITUDE_KEY, self.context.current_altitude_m)
        self.bb.set(BB_FRONT_LIDAR_RANGE_KEY, self.context.front_lidar_range_m)


    def run(self) -> None:
        try:
            log.info("BT application state machine started successfully")
            while True:
                
                self.context.tick_control()
                self.tree.tick()
                # log.debug(py_trees.display.unicode_tree(self.tree.root, show_status=True))
                time.sleep(1/FREQ_HZ)
        except KeyboardInterrupt:
            log.info("Stopping BT application")
        finally:
            if self.sim_sensors is not None:
                self.sim_sensors.stop()
            if self.telemetry is not None:
                self.telemetry.stop()
            if self.dispatcher is not None:
                self.dispatcher.stop()
            if self.msp is not None:
                self.msp.close()
            self.parameters.stop()

def init_blackboard():
    writer = py_trees.blackboard.Client(name="pre_tick_writer")
    writer.register_key(BB_CURRENT_ALTITUDE_KEY, access=py_trees.common.Access.WRITE)
    writer.register_key(BB_TARGET_ALTITUDE_KEY, access=py_trees.common.Access.WRITE)
    writer.register_key(BB_FRONT_LIDAR_RANGE_KEY, access=py_trees.common.Access.WRITE)
    writer.register_key(BB_IS_RUNNING_KEY, access=py_trees.common.Access.WRITE)

    return writer



if __name__ == "__main__":
    app = App()
    app.run()

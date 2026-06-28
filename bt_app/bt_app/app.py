from bt_app.control import joy_zmq_adapter
from bt_app.sm import Robot_StateMachine
from bt_app.context import Context
from bt_app.rc_utils import matching
from bt_app.vehicle_config import VehicleConfig
from bt_app.msp_adapter import MSPAdapter
from bt_app.common import RobotState
from bt_app.common import (
    FREQ_HZ
)
from loguru import logger as log
import time

class App:
    def __init__(self):
        """
        init vehicle context and state machine
        load controllers
        """
        self.ctx = Context()
        self.robot_sm = Robot_StateMachine(self.ctx)
        self.drone_adapter = None
        self.config = self.__handle_config()
        self.controllers = {}
        

        

    def __load_drone_interface(self):
        self.drone_adapter = MSPAdapter(self.config)
        self.drone_adapter.start()

    def __handle_config(self):
        """
        merge cli with yaml file and return config object
        """
        config = VehicleConfig()
        # handle config
        return config
    
    def __load_controllers(self):
        joy_adapter = joy_zmq_adapter.JoyZmqAdapter()
        joy_adapter.start()
        self.controllers[RobotState.MANUAL] = joy_adapter

    def __update_state(self):
        vehicle_state =self.drone_adapter.get_state()
        if vehicle_state:
            #TODO: move to consts
            self.ctx.armable = vehicle_state.get("armable", False)
            self.ctx.arming_disable_flags = vehicle_state.get("arming_disable_flags", [])

    def __resolve_rc(self):
        if self.ctx.state == RobotState.MANUAL.value:
            return self.controllers[RobotState.MANUAL].pull_rc_channels()
        else:
            log.error(f"RC selector not implemented for state {self.ctx.state}")
            raise NotImplementedError(f"RC selector not implemented for state {self.ctx.state}")

    def run(self):
        self.__load_drone_interface()
        self.__load_controllers()
        try:
            while True:
                self.__update_state()
                self.robot_sm.resolve()
                rc_channels = self.__resolve_rc()
                rc_channels = matching(self.ctx, rc_channels)
                self.drone_adapter.dispatcher.set_rc(rc_channels)
                # print(f"RC Channels: {self.__resolve_rc()}")
                time.sleep(1/FREQ_HZ)
        except KeyboardInterrupt:
            log.warning("Stopping...")

def main():
    app = App()
    app.run()
   

if __name__ == "__main__":
    main()
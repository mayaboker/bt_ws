from bt_app.control import (
    joy_zmq_adapter
)

from bt_app.control import (
    FailSafeController,
    TakeoffController,
    ARMController
)
from bt_app.sm import Robot_StateMachine
from bt_app.context import Context
from bt_app.rc_utils import matching
from bt_app.vehicle_config import VehicleConfig
from bt_app.msp_adapter import MSPAdapter
from bt_app.common import RobotState
from bt_app.common import (
    FREQ_HZ
)
from bt_app.msp.bt_v2 import (
    RC_MAX
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
        self.robot_sm.on_before_state_changed += self.__handle_before_state_changed
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
    
    def __handle_before_state_changed(self, prev, next):
        if prev == RobotState.IDLE and next == RobotState.ARM:
            log.warning("reset arm controller ")
            self.controllers[RobotState.ARM].reset()

    def __handle_joy_interrupt(self, name, value):
        """
        handle interrupt that register as joy action
        """
        # TODO: create interrupt action list
        if name == "takeoff":
            self.ctx.takeoff_interrupt = value == RC_MAX
            log.warning(f"--------takeoff interrupt {value}")

        if name == "force_manual":
            log.warning(f"--------force manual interrupt {value}")
            self.ctx.force_manual_interrupt = value == RC_MAX

    def __load_controllers(self):
        joy_adapter = joy_zmq_adapter.JoyZmqAdapter()
        joy_adapter.start()
        joy_adapter.on_failsafe_enter += self.__joystick_fs_enter
        joy_adapter.on_failsafe_exit += self.__joystick_fs_exit
        joy_adapter.on_interrupt += self.__handle_joy_interrupt
        # TODO: convert to const and mapping
        joy_adapter.register_interrupt(6, "takeoff")
        joy_adapter.register_interrupt(7, "force_manual")
        self.controllers[RobotState.MANUAL] = joy_adapter

        fs_controller = FailSafeController()
        self.controllers[RobotState.FAILSAFE] = fs_controller

        takeoff_controller = TakeoffController()
        self.controllers[RobotState.TAKEOFF] = takeoff_controller

        self.controllers[RobotState.ARM] = ARMController()

    def __joystick_fs_enter(self):
        log.warning("Joystick Failsafe Entered")
        self.ctx.joy_fail_safe = True

    def __joystick_fs_exit(self):
        log.warning("Joystick Failsafe Exited")
        self.ctx.joy_fail_safe = False

    def __update_state(self):
        """
        update the context / blackborad from drone and other sensors
        the context contain variable for state machine condition
        """

        # region read drone state
        vehicle_state =self.drone_adapter.get_state()
        if vehicle_state:
            #TODO: move to consts
            self.ctx.armable = vehicle_state.get("armable", False)
            self.ctx.arming_disable_flags = vehicle_state.get("arming_disable_flags", [])
            
        # end region 

        self.ctx.drone_alt = self.drone_adapter.get_altitude()
        ## read last drone rc
        self.ctx.drone_rc = self.drone_adapter.get_rc()

        # log.info(self.ctx.state, self.ctx.armable, self.ctx.takeoff_interrupt)

    def __resolve_rc(self):
        if self.ctx.state == RobotState.MANUAL.value:
            return self.controllers[RobotState.MANUAL].update()
        elif self.ctx.state == RobotState.FAILSAFE.value:
            return self.controllers[RobotState.FAILSAFE].update(10, self.ctx.drone_alt)
        elif self.ctx.state == RobotState.TAKEOFF.value:
            return self.controllers[RobotState.TAKEOFF].update(10, self.ctx.drone_alt)
        elif self.ctx.state == RobotState.IDLE.value:
            return [1000]*8
        elif self.ctx.state == RobotState.ARM.value:
            print(self.ctx.arming_disable_flags)
            return self.controllers[RobotState.ARM].update()
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
                if not rc_channels:
                    log.error(f"rc not valid: {rc_channels} in state {self.ctx.state}")
                    continue
                self.drone_adapter.dispatcher.set_rc(rc_channels)
                time.sleep(1/FREQ_HZ)
        except KeyboardInterrupt:
            log.warning("Stopping...")

def main():
    app = App()
    app.run()
   

if __name__ == "__main__":
    main()
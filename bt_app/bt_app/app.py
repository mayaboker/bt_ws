import pathlib

from bt_app.control import (
    joy_zmq_adapter
)

from bt_app.control import (
    FailSafeController,
    TakeoffController,
    ARMController,
    HoverYawController
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
from bt_app.common import AETR1234
from bt_app.parameters import Parameters
from loguru import logger as log
import time


class App:
    def __init__(self):
        """
        init vehicle context and state machine
        load controllers
        """
        # application configuration
        self.config = self.__handle_config()
        # hold application state
        self.ctx = Context()
        # state macine
        self.robot_sm = Robot_StateMachine(self.ctx, self.config)
        self.robot_sm.on_before_state_changed += self.__handle_before_state_changed
        # drone iterface (msp)
        self.drone_adapter = None
        
        # loaded controllers
        self.controllers = {}
        self.__params = self.__load_parameters()
        
        self.__load_drone_interface()
        self.__load_controllers()
        
        log.info("Application Start")


    def __load_parameters(self):
        """
        init parametrs
        """

        p_path = pathlib.Path(__file__).parent.parent.joinpath("config").joinpath(self.config.config_name)
        log.info("load parameters from: {}", p_path)
        return Parameters(yaml_path=p_path)

    def __load_drone_interface(self):
        """Create and start betaflight msp adapter"""
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

        elif prev == RobotState.TAKEOFF and next == RobotState.MANUAL:
            log.warning("Reset take control")
            self.ctx.take_control = False
            self.ctx.auto_arm = True

        elif next == RobotState.TAKEOFF:
            self.controllers[RobotState.TAKEOFF].reset()



    def __handle_joy_interrupt(self, name, value):
        """
        handle interrupt that register as joy action
        """
        print(name)
        # TODO: create interrupt action list
        # if name == "takeoff":
        #     self.ctx.takeoff_interrupt = value == RC_MAX
        #     log.warning(f"--------takeoff interrupt {value}")

        # if name == "force_manual":
        #     log.warning(f"--------force manual interrupt {value}")
        #     self.ctx.force_manual_interrupt = value == RC_MAX

    def __load_controllers(self):
        """
        load controllers
        each controller implement update method (signature don't force)
        - joystick zmq adapter
        - failsafe
        - arm
        - takeoff
        """
        #region joy adapter
        joy_adapter = joy_zmq_adapter.JoyZmqAdapter(self.__params)
        joy_adapter.start()
        joy_adapter.on_failsafe_enter += self.__joystick_fs_enter
        joy_adapter.on_failsafe_exit += self.__joystick_fs_exit
        joy_adapter.on_interrupt += self.__handle_joy_interrupt
        # TODO: convert to const and mapping
        print("44444444", AETR1234.AUX5)
        exit()
        joy_adapter.register_interrupt(AETR1234.AUX4, "takeoff")
        joy_adapter.register_interrupt(AETR1234.AUX5, "force_manual")
        self.controllers[RobotState.MANUAL] = joy_adapter
        log.info("load joy adapter")
        #endregion

        # fail safe controller
        self.controllers[RobotState.FAILSAFE] = FailSafeController(self.__params)

        # Takeoff
        self.controllers[RobotState.TAKEOFF] = TakeoffController(self.__params)

        # arm controller
        self.controllers[RobotState.ARM] = ARMController(self.__params)

        # search controller
        self.controllers[RobotState.SEARCH] = HoverYawController(self.__params)

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
            # TODO read more about armed mask the code is just for test
            self.ctx.armed = vehicle_state.get("box_mode_flags") == 3
            self.ctx.armable = vehicle_state.get("armable", False)
            self.ctx.arming_disable_flags = vehicle_state.get("arming_disable_flags", [])

        # end region

        self.ctx.drone_alt = self.drone_adapter.get_altitude()
        ## read last drone rc
        self.ctx.drone_rc = self.drone_adapter.get_rc()

        # log.info(self.ctx.state, self.ctx.armable, self.ctx.takeoff_interrupt)
    def __get_takeoff_rc(self):
        TEST_ALT_SP = 2 
        rc = self.controllers[RobotState.TAKEOFF].update(TEST_ALT_SP, self.ctx.drone_alt)
        
        self.ctx.takeoff_reach = self.controllers[RobotState.TAKEOFF].time_in_alt > 4
        return rc

    def __resolve_rc(self):
        if self.ctx.state == RobotState.MANUAL.value:
            channels = self.controllers[RobotState.MANUAL].update()
            if self.ctx.auto_arm:
                channels[4] = RC_MAX
            return channels
        elif self.ctx.state == RobotState.FAILSAFE.value:
            fs_alt = self.__params.get("fail_safe.alt")
            return self.controllers[RobotState.FAILSAFE].update(fs_alt, self.ctx.drone_alt)
        elif self.ctx.state == RobotState.TAKEOFF.value:
            return self.__get_takeoff_rc() 
        elif self.ctx.state == RobotState.IDLE.value:
            return [1000]*8
        elif self.ctx.state == RobotState.ARM.value:
            return self.controllers[RobotState.ARM].update()
        elif self.ctx.state == RobotState.SEARCH.value:
            return self.controllers[RobotState.SEARCH].update()
        else:
            log.error(f"RC selector not implemented for state {self.ctx.state}")
            raise NotImplementedError(f"RC selector not implemented for state {self.ctx.state}")

    def run(self):
        """
        Application entry and running loop

        loop
            - update state from drone and other sources
            - run the active state controller
            - validate and inforce rc output before send to drone
            - send via dispather
        """

        try:
            while True:
                self.__update_state()
                self.robot_sm.resolve()
                rc_channels = self.__resolve_rc()
                rc_channels = matching(self.ctx, rc_channels, self.config)
                if not rc_channels:
                    log.error(f"rc not valid: {rc_channels} in state {self.ctx.state}")
                    continue
                self.drone_adapter.dispatcher.set_rc(rc_channels[:8])
                time.sleep(1/FREQ_HZ)
        except KeyboardInterrupt:
            log.warning("Stopping...")

def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()

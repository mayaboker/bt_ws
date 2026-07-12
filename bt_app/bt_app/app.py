"""
Application entry point
"""
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
from bt_app.mavlink_wrapper import MavlinkService
from bt_app.common import NO_RC_CHANNELS, RobotState, JoyInterrupt, MavSeverity
from bt_app.parameters.generated import ParameterKey
from bt_app.common import (
    FREQ_HZ
)
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MIN
)
from bt_app.common import AETR1234
from bt_app.parameters import Parameters
from loguru import logger as log
import time
from bt_app.common.helper import format_channels


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
        self.robot_sm.on_state_changed += self._state_changed_handler
        # drone iterface (msp)
        self.drone_adapter = None
        
        # loaded controllers
        self.controllers = {}
        self.__params = self.__load_parameters()
        
        self.__load_drone_interface()
        self.__load_controllers()
        self.mavlink_service = MavlinkService(context=self.ctx)
        self.mavlink_service.start()
        self.mavlink_service.send_text_to_gcs("Application started", MavSeverity.INFO)
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


    def _state_changed_handler(self, previous_state, new_state):
        self.mavlink_service.send_text_to_gcs(
            f"State changed: {previous_state} -> {new_state}",
            MavSeverity.INFO,
        )
        
    def __handle_before_state_changed(self, prev, next):
        if prev == RobotState.IDLE and next == RobotState.ARM:
            log.warning("reset arm controller ")
            self.controllers[RobotState.ARM].reset()

        elif next == RobotState.TAKEOFF:
            self.controllers[RobotState.TAKEOFF].reset()

        elif next == RobotState.IDLE:
            log.warning("reset all controllers")
            self.controllers[RobotState.ARM].reset()
            self.controllers[RobotState.TAKEOFF].reset()
            self.ctx.armed_allowed = False
            self.ctx.joy_arm_requested = False
            self.ctx.joy_takeoff_request = False
            self.ctx.armed = False

        elif next == RobotState.HOVER:
            # self.controllers[RobotState.HOVER].set_baseline(self.ctx.drone_rc[AETR1234.THROTTLE])
            self.controllers[RobotState.HOVER].setpoint = self.ctx.drone_alt

        elif next == RobotState.FAILSAFE:
            # set the failsafe controller setpoint to the current altitude
            self.controllers[RobotState.FAILSAFE].setpoint = self.ctx.drone_alt

    def __handle_joy_interrupt(self, name, value):
        """
        handle interrupt that register as joy action
        """
        # TODO: create interrupt action list
        
        if name == JoyInterrupt.TAKEOFF_REQUEST:
            self.ctx.joy_takeoff_request = value == RC_MAX
            log.warning(f"--------takeoff interrupt {value}")

        if name == JoyInterrupt.MANUAL_REQUEST:
            self.ctx.joy_manual_request = value == RC_MAX
            log.warning(f"manual request {self.ctx.joy_manual_request}")

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
        joy_adapter.on_failsafe_enter += self._joystick_fs_enter
        joy_adapter.on_failsafe_exit += self.__joystick_fs_exit
        joy_adapter.on_interrupt += self.__handle_joy_interrupt
        # TODO: convert to const and mapping
        joy_adapter.register_interrupt(AETR1234.AUX4, JoyInterrupt.TAKEOFF_REQUEST)
        joy_adapter.register_interrupt(AETR1234.AUX1, JoyInterrupt.MANUAL_REQUEST)
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
        self.controllers[RobotState.HOVER] = HoverYawController(self.__params)

    def _joystick_fs_enter(self):
        log.warning("Joystick Failsafe Entered")
        self.ctx.joy_fail_safe = True

    def __joystick_fs_exit(self):
        log.warning("Joystick Failsafe Exited")
        self.ctx.joy_fail_safe = False

    def _update_state_from_joystick(self):
        """
        update the context / blackboard from joystick zmq adapter
        the context contain variable for state machine condition
        """
        # region read joystick state for arm request
        current = self.controllers[RobotState.MANUAL].last_rc_channels
        if not current:
            return
        self.ctx.request_rc = current.copy()
        throttle_for_arm = current[AETR1234.THROTTLE] < 1050
        yaw_for_arm = 1450 < current[AETR1234.YAW] < 1550
        # one time manover
        roll_for_arm = current[AETR1234.ROLL] < 1050
        pitch_for_arm = current[AETR1234.PITCH] < 1050
        if all([roll_for_arm, pitch_for_arm]):#, roll_for_arm, pitch_for_arm]):
            log.warning("Joystick arm request detected")
            self.ctx.armed_allowed = True

        self.ctx.joy_arm_requested = all([throttle_for_arm, yaw_for_arm, self.ctx.armed_allowed])#, roll_for_arm, pitch_for_arm])
        # end region

    def __update_state(self):
        """
        update the context / blackborad from drone and other sensors
        the context contain variable for state machine condition
        """
        # region read drone state
        self._update_state_from_joystick()

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

        battery = self.drone_adapter.dispatcher.last_battery
        if battery and "voltage_v" in battery:
            self.ctx.battery_voltage = battery["voltage_v"] + 20.0 #TODO: remove this hack, the voltage is not correct in betaflight 4.4.1

    
    def _takeoff_handler(self):
        """
        take off logic
        - get rc from takeoff controller
        - triggrt takeoff_reach flag
        """
        
        setpoint = self.__params.get(ParameterKey.TAKEOFF_ALTITUDE)
        rc = self.controllers[RobotState.TAKEOFF].update(setpoint, self.ctx.drone_alt)
        # time 
        self.ctx.takeoff_reach = self.controllers[RobotState.TAKEOFF].time_in_alt >= 1
        return rc

    def hover_handler(self):
        """
        TODO: TBD
        search logic
        - get rc from search controller
        """
        
        setpoint = self.controllers[RobotState.HOVER].setpoint
        rc = self.controllers[RobotState.HOVER].update(setpoint, self.ctx.drone_alt)
        
        return rc
    
    def failsafe_handler(self):
        """
        TODO: decide if we need a separate failsafe controller or just use hover controller
        TODO: what the altitude setpoint for failsafe? should we use the last known altitude or a predefined altitude?
        """
        
        setpoint = self.controllers[RobotState.FAILSAFE].setpoint
        rc = self.controllers[RobotState.FAILSAFE].update(setpoint, self.ctx.drone_alt)
        
        return rc

    def _update_controllers(self):
        if self.ctx.drone_rc is not None:
            #TODO: to understand why base 3
            # AETR - roll, pitch, throttle, yaw, aux1, aux2, aux3, aux4
            # AERT - roll, pitch, yaw, throttle, aux1, aux2, aux3, aux4
            # print(format_channels(self.ctx.drone_rc, formatter=tuple(AETR1234)))
            # log.info(f"Drone RC: {self.ctx.drone_rc[3]}")
            if self.ctx.state != RobotState.HOVER: 
                self.controllers[RobotState.HOVER].set_baseline(self.ctx.drone_rc[3])# AETR1234.THROTTLE
            if self.ctx.state != RobotState.FAILSAFE: 
                self.controllers[RobotState.FAILSAFE].set_baseline(self.ctx.drone_rc[3])# AETR1234.THROTTLE 

    def _resolve_rc(self):
        """
        rc loop
        ------
        resolve rc channels from the active state controller"""
        if self.ctx.state == RobotState.MANUAL:
            channels = self.controllers[RobotState.MANUAL].update()
            if self.ctx.armed:
                channels[AETR1234.AUX1] = RC_MAX
                channels[AETR1234.AUX2] = RC_MAX
            return channels
        elif self.ctx.state == RobotState.FAILSAFE:
            return self.failsafe_handler()
        elif self.ctx.state == RobotState.TAKEOFF:
            return self._takeoff_handler() 
        elif self.ctx.state == RobotState.IDLE:
            return [RC_MIN] * NO_RC_CHANNELS
        elif self.ctx.state == RobotState.ARM:
            return self.controllers[RobotState.ARM].update()
        elif self.ctx.state == RobotState.HOVER:
            return self.hover_handler()
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
                self._update_controllers()
                self.robot_sm.resolve()
                rc_channels = self._resolve_rc()
                rc_channels = matching(self.ctx, rc_channels, self.config)
                if not rc_channels:
                    log.error(f"rc not valid: {rc_channels} in state {self.ctx.state}")
                    continue
                self.drone_adapter.dispatcher.set_rc(rc_channels[:8])
                time.sleep(1/FREQ_HZ)
        except KeyboardInterrupt:
            log.warning("Stopping...")
        finally:
            self.mavlink_service.stop()

def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()

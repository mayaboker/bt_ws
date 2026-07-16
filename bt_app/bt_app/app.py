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
from bt_app.context import Context, DEFAULT_RC_CHANNELS
from bt_app.vehicle_config import DroneSink, VehicleConfig
from bt_app.errors import AppExitCode, AppStartupError
from bt_app.msp_adapter import MSPAdapter
from bt_app.mavlink_wrapper import MavlinkService
from bt_app.rc_state_recorder import NullRcStateRecorder, RcStateRecorder
from bt_app.control.land_detector import LandDetector
from bt_app.common import (
    AutoModeType,
    NO_RC_CHANNELS, 
    RobotState,
    JoyInterrupt,
    MavSeverity)
from bt_app.parameters.generated import ParameterKey
from bt_app.common import (
    FREQ_HZ
)
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MID,
    RC_MIN,
    RCChannel_alias as RCChannel,
)
from bt_app.common import AETR1234
from bt_app.parameters import Parameters
from loguru import logger as log
import time
from bt_app.common.helper import format_channels
from bt_app.common.mavlink import NamedValue

class App:
    def __init__(self, config: VehicleConfig):
        """
        init vehicle context and state machine
        load controllers
        """
        # application configuration
        self.config = config
        # hold application state
        self.ctx = Context()
        
        # state macine
        self.robot_sm = Robot_StateMachine(self.ctx, self.config)
        self.robot_sm.on_before_state_changed += self._handle_before_state_changed
        self.robot_sm.on_state_changed += self._state_changed_handler
        # drone iterface (msp)
        self.drone_adapter = None
        
        # loaded controllers
        self.controllers = {}
        self.__validate_startup_config()
        self.__params = self.__load_parameters()
        self.manual_land_detector = self.__load_manual_land_detector()
        self._manual_land_detection_started_notified = False
        self._manual_land_confirmed_notified = False
        
        self.__load_drone_interface()
        self.__load_controllers()
        self.mavlink_service = MavlinkService(
            context=self.ctx,
            qopenhd_addr=(self.config.gcs_ip, self.config.gcs_port),
        )
        self.mavlink_service.start()
        self.rc_recorder = self.__load_rc_recorder()
        self.mavlink_service.send_text_to_gcs("Application started", MavSeverity.INFO)
        log.info("Application Start")


    def __validate_startup_config(self):
        if self.config.drone_sink != DroneSink.SERIAL.value:
            return

        serial_path = pathlib.Path(self.config.drone_serial_port)
        if not serial_path.exists():
            raise AppStartupError(
                f"Serial port not found: {serial_path}",
                exit_code=AppExitCode.SERIAL_PORT_NOT_FOUND,
            )


    def __load_parameters(self):
        """
        init parametrs
        """
        p_path = pathlib.Path(self.config.config_name)
        if not p_path.is_absolute():
            p_path = pathlib.Path.cwd().joinpath(p_path)
        if not p_path.exists():
            raise AppStartupError(f"Parameters config not found: {p_path}")
        log.info("load parameters from: {}", p_path)
        try:
            return Parameters(yaml_path=p_path)
        except Exception as exc:
            raise AppStartupError(
                f"Failed to load parameters from {p_path}: {exc}"
            ) from exc

    def __load_manual_land_detector(self):
        return LandDetector(
            confirm_s=self.__params.get(ParameterKey.MANUAL_IDLE_LAND_CONFIRM_S),
            land_altitude_m=self.__params.get(ParameterKey.FAILSAFE_LAND_ALTITUDE_M),
            land_vertical_speed_m_s=self.__params.get(
                ParameterKey.FAILSAFE_LAND_VERTICAL_SPEED_M_S
            ),
        )

    def __load_drone_interface(self):
        """Create and start betaflight msp adapter"""
        self.drone_adapter = MSPAdapter(self.config)
        self.drone_adapter.start()

    def __load_rc_recorder(self):
        if not self.config.rc_record_enabled:
            return NullRcStateRecorder()

        recorder = RcStateRecorder(
            self.config.rc_record_path,
            flush_interval_s=self.config.rc_record_flush_interval_s,
            queue_size=self.config.rc_record_queue_size,
        )
        recorder.start()
        return recorder

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
        self.register_joy_interrupt(joy_adapter)
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

    def register_joy_interrupt(self, joy_adapter):
        joy_adapter.register_interrupt(AETR1234.AUX4, JoyInterrupt.TAKEOFF_REQUEST)
        joy_adapter.register_interrupt(AETR1234.AUX1, JoyInterrupt.MANUAL_REQUEST)
        joy_adapter.register_interrupt(AETR1234.AUX2, JoyInterrupt.AUTO_REQUEST)

    def _state_changed_handler(self, previous_state, new_state):
        """
        Run one time when the state change
        """
        self.mavlink_service.send_text_to_gcs(
            f"State changed: {previous_state} -> {new_state}",
            MavSeverity.INFO,
        )

        if all([previous_state == RobotState.MANUAL,
                new_state == RobotState.FAILSAFE]):
            # set manual_request to false, fail safe return to hold
            # we need  toggle return to manual
            self.ctx.joy_manual_request = False
        
    def _handle_before_state_changed(self, prev, next):
        
        """
        run before the state change, one time on change
        """
        if prev == RobotState.IDLE and next == RobotState.ARM:
            log.warning("reset arm controller ")
            self.controllers[RobotState.ARM].reset()

        # only next condition
        match next:
            case RobotState.MANUAL:
                self._reset_manual_land_detector()

            case RobotState.TAKEOFF:
                self.controllers[RobotState.TAKEOFF].reset()

            case RobotState.IDLE:
                log.warning("reset all controllers")
                self.controllers[RobotState.ARM].reset()
                self.controllers[RobotState.TAKEOFF].reset()
                self.ctx.armed_allowed = False
                self.ctx.joy_arm_requested = False
                self.ctx.joy_takeoff_request = False
                self.ctx.armed = False
                self._reset_manual_land_detector()

            case RobotState.HOVER:
                # self.controllers[RobotState.HOVER].set_baseline(self.ctx.drone_rc[AETR1234.THROTTLE])
                base_line = RC_MID# self.ctx.drone_rc[3]
                self.controllers[RobotState.HOVER].reset_setpoint(self.ctx.drone_alt)
                self.controllers[RobotState.HOVER].set_baseline(base_line)# AETR1234.THROTTLE
                self.mavlink_service.send_named_value_to_gcs(
                    NamedValue.ALT_SP,
                    self.ctx.drone_alt
                )
                log.info(f"switch to alt hold at altitude {self.ctx.drone_alt} with baseline {base_line}")

            case RobotState.FAILSAFE:
                # set the failsafe controller setpoint to the current altitude
                base_line = RC_MID# self.ctx.drone_rc[3]
                self.controllers[RobotState.FAILSAFE].reset(self.ctx.drone_alt)
                self.controllers[RobotState.FAILSAFE].set_baseline(base_line)# AETR1234.THROTTLE 
                self.mavlink_service.send_named_value_to_gcs(
                    NamedValue.ALT_SP,
                    self.ctx.drone_alt
                )
                log.info(f"switch to alt hold at altitude {self.ctx.drone_alt} with baseline {base_line}")

        if prev == RobotState.MANUAL and next != RobotState.IDLE:
            self._reset_manual_land_detector()

    #region joystick handlers
    def __handle_joy_interrupt(self, name, value):
        """
        handle interrupt that register as joy action
        """
        # TODO: create interrupt action list
        
        if name == JoyInterrupt.TAKEOFF_REQUEST:
            self.ctx.joy_takeoff_request = value == RC_MAX
            log.warning(f"--------takeoff interrupt {value}")

        elif name == JoyInterrupt.MANUAL_REQUEST:
            self.ctx.joy_manual_request = value == RC_MAX
            self.ctx.armed_allowed = False
            log.warning(f"manual request {self.ctx.joy_manual_request}")

        elif name == JoyInterrupt.AUTO_REQUEST:
            self.ctx.auto_mode_type = AutoModeType(value)
            log.warning(f"auto request {self.ctx.auto_mode_type}")

        

    
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
        # one time 
        # roll_for_arm = current[AETR1234.ROLL] < 1050
        # pitch_for_arm = current[AETR1234.PITCH] < 1050
        yaw_for_arm = current[AETR1234.YAW] > 1950
        throttle_for_arm = current[AETR1234.THROTTLE] < 1050
        # if all([roll_for_arm, pitch_for_arm]):#, roll_for_arm, pitch_for_arm]):
        if all([yaw_for_arm, throttle_for_arm]):
            log.warning("Joystick arm request detected")
            self.ctx.armed_allowed = True

        self.ctx.joy_arm_requested = all([throttle_for_arm, yaw_for_arm, self.ctx.armed_allowed])#, roll_for_arm, pitch_for_arm])
        # end region

    #endregion

    def __update_state(self):
        """
        update the context / blackboard from drone and other sensors
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
        altitude = self.drone_adapter.dispatcher.last_altitude
        if altitude and "vertical_speed_m_s" in altitude:
            self.ctx.drone_vertical_speed = altitude["vertical_speed_m_s"]
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

        if setpoint != self.ctx.alt_setpoint:
            self.mavlink_service.send_named_value_to_gcs(
                    NamedValue.ALT_SP,
                    setpoint
                )
            self.ctx.alt_setpoint = setpoint
        
        return rc

    def hover_handler(self):
        """
        ALT Hold handler
        """
        controller = self.controllers[RobotState.HOVER]
        # read last joystick state
        controller.update_setpoint_from_throttle(
            self.ctx.request_rc[AETR1234.THROTTLE]
        )
        controller.update_yaw_from_joystick(
            self.ctx.request_rc[AETR1234.YAW]
        )


        if controller.consume_altitude_setpoint_request_event():
            self.mavlink_service.send_text_to_gcs(
                "Hover altitude setpoint change requested",
                MavSeverity.DEBUG,
            )
            
            
        setpoint = controller.setpoint
        # update gcs setpoint
        if controller.setpoint != self.ctx.alt_setpoint:
            self.mavlink_service.send_named_value_to_gcs(
                    NamedValue.ALT_SP,
                    setpoint
                )
            self.ctx.alt_setpoint = setpoint
        
        rc = controller.update(setpoint, self.ctx.drone_alt)
        return rc
    
    def failsafe_handler(self):
        """
        TODO: decide if we need a separate failsafe controller or just use hover controller
        TODO: what the altitude setpoint for failsafe? should we use the last known altitude or a predefined altitude?
        """
        
        controller = self.controllers[RobotState.FAILSAFE]
        rc = controller.update(self.ctx.drone_alt, self.ctx.drone_vertical_speed)
        if controller.consume_descent_started_event():
            self.mavlink_service.send_text_to_gcs(
                "Failsafe landing started",
                MavSeverity.WARNING,
            )
        if controller.consume_landed_event():
            self.mavlink_service.send_text_to_gcs(
                "Failsafe land detected, disarming",
                MavSeverity.WARNING,
            )
        
        return rc

    def _manual_handler(self):
        channels = self.controllers[RobotState.MANUAL].update()
        if self.ctx.armed:
            channels[AETR1234.AUX1] = RC_MAX
            channels[AETR1234.AUX2] = RC_MAX
        return channels

    def _notification_center(self):
        """
        TODO: think about queue and other service handle it, for know we  only user scheduler submit it like queue"""
        self._update_manual_land_detector()
        if self.ctx.state == RobotState.ARM:
            if self.ctx.arming_disable_flags:
                pass
                # print(self.ctx.arming_disable_flags)

        # log.info(self.ctx)

    def _manual_land_detection_requested(self) -> bool:
        return (
            self.ctx.state == RobotState.MANUAL
            and not self.ctx.joy_manual_request
            and self.ctx.request_rc[AETR1234.THROTTLE] < 1050
        )

    def _reset_manual_land_detector(self) -> None:
        self.manual_land_detector.reset()
        self.ctx.manual_land_confirmed = False
        self._manual_land_detection_started_notified = False
        self._manual_land_confirmed_notified = False

    def _update_manual_land_detector(self) -> None:
        if not self._manual_land_detection_requested():
            self._reset_manual_land_detector()
            return

        if not self._manual_land_detection_started_notified:
            self.mavlink_service.send_text_to_gcs(
                "Manual land detection started",
                MavSeverity.INFO,
            )
            self._manual_land_detection_started_notified = True

        self.ctx.manual_land_confirmed = self.manual_land_detector.update(
            self.ctx.drone_alt,
            self.ctx.drone_vertical_speed,
        )
        if (
            self.ctx.manual_land_confirmed
            and not self._manual_land_confirmed_notified
        ):
            self.mavlink_service.send_text_to_gcs(
                "Manual land confirmed, disarming",
                MavSeverity.INFO,
            )
            self._manual_land_confirmed_notified = True

    def _update_controllers(self):
        """
        update/keep the controllers with the current context
        """
        if self.ctx.drone_rc is not None:
            pass
            #TODO: to understand why base 3
            # AETR - roll, pitch, throttle, yaw, aux1, aux2, aux3, aux4
            # AERT - roll, pitch, yaw, throttle, aux1, aux2, aux3, aux4
            # print(format_channels(self.ctx.drone_rc, formatter=tuple(AETR1234)))
            # log.info(f"Drone RC: {self.ctx.drone_rc[3]}")
            # if self.ctx.state != RobotState.HOVER:
            #     self.controllers[RobotState.HOVER].set_baseline(self.ctx.drone_rc[3])# AETR1234.THROTTLE
            # if self.ctx.state != RobotState.FAILSAFE: 
            #     self.controllers[RobotState.FAILSAFE].set_baseline(self.ctx.drone_rc[3])# AETR1234.THROTTLE 

    def _resolve_rc(self):
        """
        rc loop
        ------
        resolve rc channels from the active state controller"""
        
        if self.ctx.state == RobotState.MANUAL:
            return self._manual_handler()
        elif self.ctx.state == RobotState.FAILSAFE:
            return self.failsafe_handler()
        elif self.ctx.state == RobotState.TAKEOFF:
            return self._takeoff_handler() 
        elif self.ctx.state == RobotState.IDLE:
            return self._make_disarm_channels()
        elif self.ctx.state == RobotState.ARM:
            return self.controllers[RobotState.ARM].update()
        elif self.ctx.state == RobotState.HOVER:
            return self.hover_handler()
        else:
            log.error(f"RC selector not implemented for state {self.ctx.state}")
            raise NotImplementedError(f"RC selector not implemented for state {self.ctx.state}")

    def _sanitize_rc_channels(self, channels: list[int]) -> list[int]:
        sanitized = DEFAULT_RC_CHANNELS.copy()
        for index, channel in enumerate(channels[:NO_RC_CHANNELS]):
            channel = int(channel)
            if RC_MIN <= channel <= RC_MAX:
                sanitized[index] = channel
            else:
                log.debug(
                    "Invalid RC channel {} value {}, using default {}",
                    index + 1,
                    channel,
                    sanitized[index],
                )
        return sanitized

    #TODO: move to arm controller 
    def _make_disarm_channels(self) -> list[int]:
        channels = [RC_MIN] * NO_RC_CHANNELS
        channels[RCChannel.ROLL] = RC_MID
        channels[RCChannel.PITCH] = RC_MID
        channels[RCChannel.THROTTLE] = RC_MIN
        channels[RCChannel.YAW] = RC_MID
        channels[RCChannel.ARM] = RC_MIN
        channels[RCChannel.ANGLE] = RC_MAX
        return channels

    def run(self):
        """
        Application entry and running loop

        loop
            - update state from drone and other sources
            - run the active state controller
            - validate and inforce rc output before send to drone
            - send via dispatcher
        """

        try:
            while True:
                self.__update_state()
                self._update_controllers()
                self._notification_center()
                self.robot_sm.resolve()
                rc_channels = self._resolve_rc()
                if not rc_channels:
                    log.error(f"rc not valid: {rc_channels} in state {self.ctx.state}")
                    continue
                self.ctx.sent_rc = self._sanitize_rc_channels(rc_channels)
                self.rc_recorder.record(self.ctx.state, self.ctx.sent_rc)
                self.drone_adapter.dispatcher.set_rc(self.ctx.sent_rc)
                time.sleep(1/FREQ_HZ)
        except KeyboardInterrupt:
            log.warning("Stopping...")
        finally:
            self.mavlink_service.stop()
            try:
                self.rc_recorder.stop()
            except Exception as exc:
                log.exception("Failed to stop RC state recorder: {}", exc)

def main(config: VehicleConfig):
    app = App(config=config)
    app.run()


if __name__ == "__main__":
    raise SystemExit("Use bt-app run")

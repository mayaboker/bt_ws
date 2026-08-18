"""
Application entry point
"""

#region
import pathlib
import signal
import threading

from bt_app.control import (
    FailSafeController,
    TakeoffController,
    ARMController,
    HoverYawController,
    MavlinkListenerError,
    MavlinkListenerService
)
from bt_app.sm import Robot_StateMachine
from bt_app.context import Context, DEFAULT_RC_CHANNELS
from bt_app.vehicle_config import DroneSink, VehicleConfig
from bt_app.errors import AppExitCode, AppStartupError
from bt_app.msp_adapter import MSPAdapter
from bt_app.msp import MspTransportDependencyError
from bt_app.mavlink_wrapper import MavlinkService
from bt_app.rc_state_recorder import NullRcStateRecorder, RcStateRecorder
from bt_app.control.land_detector import LandDetector
from bt_app.visual_bridge import VisualBridgeManager
from bt_app.common import (
    NO_RC_CHANNELS, 
    RobotState,
    MavSeverity)
from bt_app.parameters.generated import ParameterKey
from bt_app._version import __version__
from bt_app.common import (
    FREQ_HZ
)
from bt_app.msp.bt_v2 import (
    RC_MAX,
    RC_MID,
    RC_MIN,
    RCChannel_alias as RCChannel,
)
from bt_app.common import (
    AETR1234,
    InternalJoy)
from bt_app.parameters import Parameters
from loguru import logger as log
import time
from bt_app.common.mavlink import NamedValue
#TODO: remove when rc_channel_control implement adapter
from bt_joy.server.mavlink import (
    RcChannelsOverrideEvent,
    MavlinkServerConfig,
    NoCommunicationEvent,
    CommunicationResumedEvent
)
#endregion

FCU_CONNECT_ATTEMPTS = 3
FCU_CONNECT_RETRY_DELAY_S = 1.0


class App:
    def __init__(self, config: VehicleConfig):
        """
        init vehicle context and state machine
        load controllers
        """
        # application configuration
        self.config = config
        self._stop_event = threading.Event()
        self._shutdown_signal: int | None = None
        self._last_logged_armable: bool | None = None
        # hold application state
        self.ctx = Context()

        # state machine
        self.robot_sm = Robot_StateMachine(self.ctx, self.config)
        self.robot_sm.on_before_state_changed += self._handle_before_state_changed
        self.robot_sm.on_state_changed += self._state_changed_handler
        # drone interface (msp)
        self.drone_adapter = None
        
        # loaded controllers
        self.controllers = {}
        self.visual_bridge_manager = None
        self.__validate_startup_config()
        try:
            self.__params = self.__load_parameters()
            self.visual_bridge_manager = self.__load_visual_bridge_manager()
            self.ctx.alt_setpoint = self.__params.get(ParameterKey.TAKEOFF_ALT)
            self.manual_land_detector = self.__load_manual_land_detector()
            parameter_event = getattr(self.__params, "on_parameter_changed", None)
            if parameter_event is not None:
                parameter_event.subscribe(self._on_application_parameter_changed)
            self._manual_land_detection_started_notified = False
            self._manual_land_confirmed_notified = False
            self._last_rc_channel = DEFAULT_RC_CHANNELS.copy()
            self.__load_drone_interface()
            self.__load_controllers()
            self.mavlink_service = MavlinkService(
                context=self.ctx,
                parameter_service=getattr(self.__params, "service", None),
                qopenhd_addr=(self.config.gcs_ip, self.config.gcs_port),
            )
            self.mavlink_service.start()
            self.rc_recorder = self.__load_rc_recorder()
            self.mavlink_service.send_text_to_gcs(
                "Application started",
                MavSeverity.INFO,
            )
            self.__banner()
        except BaseException:
            self._shutdown()
            raise

    def __banner(self):
        log.info("Application Start v{}", __version__)
        log.debug("Application log level : DEBUG")

    def __validate_startup_config(self):
        if not self.config.visual_zmq_endpoint:
            raise AppStartupError("Visual ZMQ endpoint must not be empty")

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

    def __load_visual_bridge_manager(self):
        manager = VisualBridgeManager(self.config.visual_zmq_endpoint)
        try:
            manager.start()
        except RuntimeError as exc:
            raise AppStartupError(
                f"Unable to start visual bridge: {exc}"
            ) from exc
        return manager

    def __load_manual_land_detector(self):
        return LandDetector(
            confirm_s=self.__params.get(ParameterKey.MI_LAND_CONFIRM),
            land_altitude_m=self.__params.get(ParameterKey.FS_LAND_ALT),
            land_vertical_speed_m_s=self.__params.get(
                ParameterKey.FS_LAND_VSPEED
            ),
        )

    def _on_application_parameter_changed(self, name: str, value) -> None:
        if name == ParameterKey.MI_LAND_CONFIRM:
            self.manual_land_detector.confirm_s = float(value)
        elif name == ParameterKey.FS_LAND_ALT:
            self.manual_land_detector.land_altitude_m = float(value)
        elif name == ParameterKey.FS_LAND_VSPEED:
            self.manual_land_detector.land_vertical_speed_m_s = float(value)

    def __load_drone_interface(self):
        """Create and start betaflight msp adapter"""
        self.drone_adapter = MSPAdapter(self.config)
        transport_name, endpoint = self._fcu_connection_description()

        for attempt in range(1, FCU_CONNECT_ATTEMPTS + 1):
            try:
                self.drone_adapter.start()
                return
            except OSError as exc:
                self.drone_adapter.msp.close()
                reason = self._connection_failure_reason(exc)
                if attempt == FCU_CONNECT_ATTEMPTS:
                    raise AppStartupError(
                        f"Unable to connect to FCU over {transport_name} at "
                        f"{endpoint} after {FCU_CONNECT_ATTEMPTS} attempts: "
                        f"{reason}",
                        exit_code=AppExitCode.FCU_CONNECTION_FAILED,
                    ) from exc
                log.warning(
                    "FCU connection failed transport={} endpoint={} "
                    "attempt={}/{} reason={}",
                    transport_name,
                    endpoint,
                    attempt,
                    FCU_CONNECT_ATTEMPTS,
                    reason,
                )
                time.sleep(FCU_CONNECT_RETRY_DELAY_S)
            except MspTransportDependencyError as exc:
                raise AppStartupError(
                    f"Unable to initialize FCU {transport_name} transport at "
                    f"{endpoint}: {exc}",
                    exit_code=AppExitCode.FCU_CONNECTION_FAILED,
                ) from exc

    def _fcu_connection_description(self) -> tuple[str, str]:
        if self.config.drone_sink == DroneSink.SERIAL.value:
            return "serial", f"{self.config.drone_serial_port}@115200"
        return "TCP", f"{self.config.drone_eth_host}:{self.config.drone_eth_port}"

    @staticmethod
    def _connection_failure_reason(exc: OSError) -> str:
        if isinstance(exc, ConnectionRefusedError):
            return "connection refused"
        if isinstance(exc, TimeoutError):
            return "connection timed out"
        if isinstance(exc, PermissionError):
            return "permission denied"
        return str(exc) or exc.__class__.__name__

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
        config = MavlinkServerConfig(
            connection="udpin:0.0.0.0:14560",
            source_system=254,
            source_component=0,
            heartbeat_rate_hz=1.0,
            communication_timeout_stage1_s=1.0,
            communication_timeout_stage2_s=5.0,
            receive_timeout_s=0.05,
            channel_count=18,
        )
        joy_adapter = MavlinkListenerService(
            config=config,
            on_rc=self.__handle_joy_rc,
            on_timeout=self._joystick_fs_enter,
            on_resume=self.__joystick_fs_exit,
            on_failure=self._joystick_listener_failed,
        )
        self.controllers[RobotState.MANUAL] = joy_adapter
        try:
            joy_adapter.start()
        except MavlinkListenerError as exc:
            raise AppStartupError(
                f"Unable to start joystick MAVLink listener: {exc}"
            ) from exc
        log.info(f"------------------------- {config}")
        # joy_adapter = joy_zmq_adapter.JoyZmqAdapter(self.__params)
        # joy_adapter.start()
        # joy_adapter.on_failsafe_enter += self._joystick_fs_enter
        # joy_adapter.on_failsafe_exit += self.__joystick_fs_exit
        # joy_adapter.on_interrupt += self.__handle_joy_interrupt
        # TODO: convert to const and mapping
        # self.register_joy_interrupt(joy_adapter)
        log.info("load joy adapter")
        #endregion

        # fail safe controller
        self.controllers[RobotState.FAILSAFE] = FailSafeController(self.__params)

        # Takeoff
        self.controllers[RobotState.TAKEOFF] = TakeoffController(self.__params)

        # arm controller
        self.controllers[RobotState.ARM] = ARMController(self.__params)

        # search controller
        self.controllers[RobotState.ALT_HOLD] = HoverYawController(self.__params)

    # def register_joy_interrupt(self, joy_adapter):
    #     joy_adapter.register_interrupt(AETR1234.AUX4, JoyInterrupt.TAKEOFF_REQUEST)
    #     joy_adapter.register_interrupt(AETR1234.AUX1, JoyInterrupt.MANUAL_REQUEST)
        

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

            case RobotState.ALT_HOLD:
                base_line = self.__params.get(ParameterKey.HOV_BASELINE)
                from_takeoff = prev == RobotState.TAKEOFF
                hold_setpoint = (
                    self.__params.get(ParameterKey.TAKEOFF_ALT)
                    if from_takeoff
                    else self.ctx.drone_alt
                )
                controller = self.controllers[RobotState.ALT_HOLD]
                controller.reset_setpoint(
                    self.ctx.drone_alt,
                    setpoint=hold_setpoint,
                    altitude_sample_time_s=self.ctx.drone_alt_received_at_s,
                    vertical_speed_m_s=self.ctx.drone_vertical_speed,
                    require_throttle_center=from_takeoff,
                )
                controller.set_baseline(base_line)# AETR1234.THROTTLE
                self.ctx.alt_setpoint = hold_setpoint
                self.mavlink_service.send_named_value_to_gcs(
                    NamedValue.ALT_SP,
                    hold_setpoint
                )
                previous_throttle = self.ctx.sent_rc[AETR1234.THROTTLE]
                log.info(
                    "switch to alt hold target={} altitude={} vertical_speed={} "
                    "baseline={} previous_throttle={} require_throttle_center={}",
                    hold_setpoint,
                    self.ctx.drone_alt,
                    self.ctx.drone_vertical_speed,
                    base_line,
                    previous_throttle,
                    from_takeoff,
                )

            case RobotState.FAILSAFE:
                # set the failsafe controller setpoint to the current altitude
                base_line = self.__params.get(ParameterKey.HOV_BASELINE)
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
    def __handle_joy_rc(self, event: RcChannelsOverrideEvent):
        """
        handle interrupt that register as joy action
        """
        channels = list(event.channels)
        self._last_rc_channel = channels
        self.ctx.request_rc = self._last_rc_channel
        # if name == JoyInterrupt.TAKEOFF_REQUEST:
        self.ctx.joy_takeoff_request = self._last_rc_channel[InternalJoy.AUTO_TAKE_OFF] == RC_MAX
        self.ctx.joy_manual_request = self._last_rc_channel[InternalJoy.MANUAL] == RC_MIN
        self.ctx.arm_switch = self._last_rc_channel[InternalJoy.ARM] == RC_MAX
        throttle_for_arm = self._last_rc_channel[InternalJoy.THROTTLE] < 1050
        # if all([roll_for_arm, pitch_for_arm]):#, roll_for_arm, pitch_for_arm]):
        if all([throttle_for_arm, self.ctx.arm_switch]):
            # log.warning("Joystick arm request detected")
            self.ctx.armed_allowed = True
        elif all([not self.ctx.arm_switch, throttle_for_arm]):
            # log.warning("Joystick disarm request detected")
            self.ctx.armed_allowed = False

        self.ctx.joy_arm_requested = all([throttle_for_arm, self.ctx.armed_allowed])#, roll_for_arm, pitch_for_arm])
        # end region

        

    
    def _enter_joystick_failsafe(self) -> None:
        """Clear stale joystick intent and request application failsafe."""
        safe_channels = DEFAULT_RC_CHANNELS.copy()
        self._last_rc_channel = safe_channels.copy()
        self.ctx.request_rc = safe_channels
        self.ctx.joy_fail_safe = True
        self.ctx.joy_takeoff_request = False
        self.ctx.joy_manual_request = False
        self.ctx.joy_arm_requested = False
        self.ctx.armed_allowed = False
        self.ctx.arm_switch = False

    def _joystick_fs_enter(self, event: NoCommunicationEvent):
        log.warning(
            "Joystick failsafe entered stage={} timeout_s={}",
            event.stage,
            event.timeout_s,
        )
        self._enter_joystick_failsafe()

    def _joystick_listener_failed(self, error: MavlinkListenerError) -> None:
        log.error("Joystick MAVLink listener failed: {}", error)
        self._enter_joystick_failsafe()

    def __joystick_fs_exit(self, event: CommunicationResumedEvent):
        log.info(
            "Joystick communication resumed previous_stage={}",
            event.previous_stage,
        )
        self.ctx.joy_fail_safe = False

    def _dispatch_pending_joystick_events(self) -> None:
        """Apply listener events on the application control-loop thread."""
        listener = getattr(self, "controllers", {}).get(RobotState.MANUAL)
        dispatch_pending = getattr(listener, "dispatch_pending", None)
        if dispatch_pending is not None:
            dispatch_pending()

    def _update_state_from_joystick(self):
        """
        update the context / blackboard from joystick zmq adapter
        the context contain variable for state machine condition
        """
        # region read joystick state for arm request
        

    #endregion

    def _log_armability_transition(self) -> None:
        """Log arm readiness once whenever the readiness state changes."""
        armable = bool(self.ctx.armable)
        if armable == getattr(self, "_last_logged_armable", None):
            return

        if armable:
            log.success("Vehicle is ready to arm")
        else:
            flags = self.ctx.arming_disable_flags
            reason = ", ".join(map(str, flags)) if flags else "reason unavailable"
            log.warning("Vehicle is not ready to arm: {}", reason)

        self._last_logged_armable = armable

    def __update_state(self):
        """
        update the context / blackboard from drone and other sensors
        the context contain variable for state machine condition
        """

        vehicle_state =self.drone_adapter.get_state()
        if vehicle_state:
            #TODO: move to consts
            # TODO read more about armed mask the code is just for test
            # self.ctx.armed = vehicle_state.get("box_mode_flags") == 3
            self.ctx.armable = vehicle_state.get("armable", False)
            self.ctx.arming_disable_flags = vehicle_state.get("arming_disable_flags", [])
            self._log_armability_transition()

            log.debug(vehicle_state)

        # end region
        # the zero point is where the drone power on, if i land in lower surface the alt will be negative
        self.ctx.drone_alt = self.drone_adapter.get_altitude() # in meter
        altitude = self.drone_adapter.dispatcher.last_altitude
        if altitude and "vertical_speed_m_s" in altitude:
            self.ctx.drone_vertical_speed = altitude["vertical_speed_m_s"]
            self.ctx.drone_alt_received_at_s = altitude.get("received_at_s", 0.0)
        attitude = self.drone_adapter.dispatcher.last_attitude
        if attitude:
            self.ctx.drone_roll_deg = float(attitude.get("roll_deg", 0.0))
            self.ctx.drone_pitch_deg = float(attitude.get("pitch_deg", 0.0))
            self.ctx.drone_heading_deg = float(attitude.get("heading_deg", 0.0))
        ## read last drone rc
        rc = self.drone_adapter.get_rc()
        if rc:
            self.ctx.drone_rc = rc
            # read the aux1/armed value , the idea is to update ARM/AUX1 value when the system run with external pilot
            # TODO : check with real drone
            # armed = self.ctx.drone_rc[BTRCChannels.ARM] == RC_MAX
            # if armed != self.ctx.armed:
            #     log.info(f"arming change : {armed}")
            #     log.info(f"drone rc: {self.ctx.drone_rc}")
            #     self.ctx.armed = armed


        battery = self.drone_adapter.dispatcher.last_battery
        if battery and "voltage_v" in battery:
            self.ctx.battery_voltage = battery["voltage_v"] + 20.0 #TODO: remove this hack, the voltage is not correct in betaflight 4.4.1

        
    
    def _takeoff_handler(self):
        """
        take off logic
        - get rc from takeoff controller
        - triggrt takeoff_reach flag
        """
        
        setpoint = self.__params.get(ParameterKey.TAKEOFF_ALT)
        #TODO: setpoint is alt_ref + setpoint validate again the start alt is zero
        rc = self.controllers[RobotState.TAKEOFF].update(
            setpoint,
            self.ctx.drone_alt,
            self.ctx.drone_alt_received_at_s,
        )
        # time 
        self.ctx.takeoff_reach = self.controllers[RobotState.TAKEOFF].time_in_alt >= 1

        if setpoint != self.ctx.alt_setpoint:
            self.mavlink_service.send_named_value_to_gcs(
                    NamedValue.ALT_SP,
                    setpoint
                )
            self.ctx.alt_setpoint = setpoint
        
        return rc

    def alt_hold_handler(self):
        """
        ALT Hold handler
        """
        controller = self.controllers[RobotState.ALT_HOLD]
        # read last joystick state
        
        # update alt setpoint
        controller.update_setpoint_from_throttle(
            self.ctx.request_rc[InternalJoy.THROTTLE]
        )

        # control yaw
        controller.update_yaw_from_joystick(
            self.ctx.request_rc[InternalJoy.YAW]
        )

        # TODO: add deadband ???
        # control pitch and yaw
        pitch = self.ctx.request_rc[InternalJoy.PITCH]
        roll = self.ctx.request_rc[InternalJoy.ROLL]

        controller.update_pitch_roll(pitch, roll)

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
        
        rc = controller.update(
            setpoint,
            self.ctx.drone_alt,
            self.ctx.drone_alt_received_at_s,
        )
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
        channels = self._last_rc_channel
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
        match self.ctx.state:
            case RobotState.MANUAL:
                return self._manual_handler()
            case RobotState.FAILSAFE:
                return self.failsafe_handler()
            case RobotState.TAKEOFF:
                return self._takeoff_handler() 
            case RobotState.IDLE:
                return self._make_disarm_channels()
            case RobotState.ARM:
                return self._arm_handler()
            case RobotState.ALT_HOLD:
                return self.alt_hold_handler()
            case _:
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

    def _arm_handler(self):
        from typing import cast
        arm_controller: ARMController = cast(ARMController, self.controllers[RobotState.ARM])
        self.ctx.armed = arm_controller.is_arm_done
        return self.controllers[RobotState.ARM].update()
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

    def request_stop(self, signum: int | None = None) -> None:
        """Request a graceful stop from a signal handler or another thread."""
        if signum is not None and self._shutdown_signal is None:
            self._shutdown_signal = signum
        self._stop_event.set()

    def _shutdown(self) -> None:
        """Stop all application services, keeping MSP shutdown first."""
        resources = (
            ("MSP adapter", getattr(self, "drone_adapter", None)),
            (
                "visual bridge manager",
                getattr(self, "visual_bridge_manager", None),
            ),
            (
                "joystick listener",
                getattr(self, "controllers", {}).get(RobotState.MANUAL),
            ),
            ("MAVLink service", getattr(self, "mavlink_service", None)),
            ("RC state recorder", getattr(self, "rc_recorder", None)),
            ("parameter service", getattr(self, "_App__params", None)),
        )
        for resource_name, resource in resources:
            stop = getattr(resource, "stop", None)
            if stop is None:
                continue
            try:
                stop()
            except Exception as exc:
                log.exception("Failed to stop {}: {}", resource_name, exc)

    def _raise_if_msp_failed(self) -> None:
        """Surface fatal errors reported by the MSP worker thread."""
        adapter = getattr(self, "drone_adapter", None)
        raise_if_failed = getattr(adapter, "raise_if_failed", None)
        if raise_if_failed is not None:
            raise_if_failed()

    def _log_control_loop_failure(self, exc: Exception) -> None:
        """Log an unexpected loop failure with flight-state context."""
        ctx = getattr(self, "ctx", None)
        log.opt(exception=exc).critical(
            "Control loop terminated unexpectedly: state={} armed={} "
            "requested_rc={} sent_rc={} altitude_m={} vertical_speed_m_s={} "
            "arming_disable_flags={}",
            getattr(ctx, "state", None),
            getattr(ctx, "armed", None),
            getattr(ctx, "request_rc", None),
            getattr(ctx, "sent_rc", None),
            getattr(ctx, "drone_alt", None),
            getattr(ctx, "drone_vertical_speed", None),
            getattr(ctx, "arming_disable_flags", None),
        )

    def run(self):
        """Run the RC control loop until a stop is requested.

        Each iteration updates application state and controllers, resolves and
        sanitizes the active controller's RC channels, records them, and sends
        them to the flight controller.  A stop request is checked again before
        recording and dispatch so shutdown cannot emit one final RC command.

        Exceptions from the loop are allowed to propagate, but all initialized
        services are given a chance to stop before this method returns or
        raises.
        """

        period_s = 1.0 / FREQ_HZ
        next_deadline_s = time.monotonic()

        try:
            while not self._stop_event.is_set():
                self._raise_if_msp_failed()
                self._dispatch_pending_joystick_events()
                self.__update_state()
                self._update_controllers()
                self._notification_center()
                # resolve state machine state
                self.robot_sm.resolve()
                # get rc data from the right controller
                rc_channels = self._resolve_rc()
                # validate rc channel
                self.ctx.sent_rc = self._sanitize_rc_channels(rc_channels)
                if self._stop_event.is_set():
                    break
                # log for diagnostic
                self.rc_recorder.record(self.ctx.state, self.ctx.sent_rc)
                # send to FCU
                self.drone_adapter.dispatcher.set_rc(self.ctx.sent_rc)
                next_deadline_s += period_s
                now_s = time.monotonic()
                if next_deadline_s <= now_s:
                    missed_periods = int((now_s - next_deadline_s) // period_s) + 1
                    next_deadline_s += missed_periods * period_s
                self._stop_event.wait(next_deadline_s - now_s)

            self._raise_if_msp_failed()
        except Exception as exc:
            self._log_control_loop_failure(exc)
            raise
        finally:
            if self._shutdown_signal is None:
                log.info("Application shutdown requested")
            else:
                signal_name = signal.Signals(self._shutdown_signal).name
                log.info("Application shutdown requested by {}", signal_name)
            self._shutdown()

def main(config: VehicleConfig):
    app = App(config=config)
    app.run()


if __name__ == "__main__":
    raise SystemExit("Use bt-app run")

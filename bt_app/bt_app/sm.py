from loguru import logger as log
from bt_app.common import RobotState
from transitions import Machine
from bt_app.common import Event
from bt_app.vehicle_config import VehicleConfig
from bt_app.context import Context

def _coerce_robot_state(state) -> RobotState:
    if isinstance(state, RobotState):
        return state
    if isinstance(state, str):
        if state in RobotState.__members__:
            return RobotState[state]
        member_name = state.rsplit(".", 1)[-1]
        if member_name in RobotState.__members__:
            return RobotState[member_name]
        return RobotState(int(state))
    return RobotState(state)




class Robot_StateMachine:
    states = list(RobotState)

    def __init__(self, ctx: Context, config: VehicleConfig):
        self.ctx: Context = ctx
        self.config: VehicleConfig = config
        self.on_before_state_changed = Event()
        self.on_state_changed = Event()
        self.machine = Machine(
            model=self,
            states=self.states,
            initial=RobotState.IDLE,
            ignore_invalid_triggers=True,
            send_event=True,
            after_state_change=self.on_state_changed_handler,
        )

        # region from IDLE
        # from idle to arm
        self.machine.add_transition(
            "resolve",
            RobotState.IDLE,
            RobotState.ARM,
            before=lambda x: self.on_before_state_changed.emit(RobotState.IDLE, RobotState.ARM),
            conditions=[self.enter_arm]
        )

        # from idle to manual
        # self.machine.add_transition(
        #     "resolve",
        #     RobotState.IDLE,
        #     RobotState.MANUAL,
        #     before=lambda x: self.on_before_state_changed.emit(RobotState.IDLE, RobotState.MANUAL),
        #     conditions=[self.enter_manual_from_idle]
        # )

       

        # region from ARM
        # from arm to manual
        self.machine.add_transition(
            "resolve",
            RobotState.ARM,
            RobotState.MANUAL,
            before=lambda x: self.on_before_state_changed.emit(RobotState.ARM, RobotState.MANUAL),
            conditions=[self.enter_manual_mode_from_arm],
        )

        # from manual to take off
        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.TAKEOFF,
            before=lambda x: self.on_before_state_changed.emit(RobotState.MANUAL, RobotState.TAKEOFF),
            conditions=[self.enter_takeoff_from_manual]
        )
        # endregion

        # region to FAILSAFE
        # manual to failsafe
        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.FAILSAFE,
            before=lambda x: self.on_before_state_changed.emit(RobotState.MANUAL, RobotState.FAILSAFE),
            conditions=[self.enter_failsafe]
        )

        self.machine.add_transition(
            "resolve",
            RobotState.ALT_HOLD,
            RobotState.FAILSAFE,
            before=lambda x: self.on_before_state_changed.emit(RobotState.ALT_HOLD, RobotState.FAILSAFE),
            conditions=[self.enter_failsafe]
        )
        # endregion to FAILSAFE

        # region from FAILSAFE
        self.machine.add_transition(
            "resolve",
            RobotState.FAILSAFE,
            RobotState.ALT_HOLD,
            before=lambda x: self.on_before_state_changed.emit(RobotState.FAILSAFE, RobotState.ALT_HOLD),
            conditions=[self.exit_failsafe],
        )

        self.machine.add_transition(
            "resolve",
            RobotState.FAILSAFE,
            RobotState.IDLE,
            before=lambda x: self.on_before_state_changed.emit(RobotState.FAILSAFE, RobotState.IDLE),
            conditions=[self.exit_failsafe_to_idle],
        )
        # endregion to FAILSAFE

        #region from manual
        # TODO: add ToF ground
        # TODO: not safe to exit manual and close throttle, check if may be accelerometer can help if we are on ground
        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.IDLE,
            before=lambda x: self.on_before_state_changed.emit(RobotState.MANUAL, RobotState.IDLE),
            conditions=[self.enter_idle_from_manual],
        )

        # manual to alt_hold
        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.ALT_HOLD,
            before=lambda x: self.on_before_state_changed.emit(RobotState.MANUAL, RobotState.ALT_HOLD),
            conditions=[self.enter_hover_from_manual],
        )
        #endregion from manual

        # region from TAKEOFF
        self.machine.add_transition(
            "resolve",
            RobotState.TAKEOFF,
            RobotState.ALT_HOLD,
            before=lambda x: self.on_before_state_changed.emit(RobotState.TAKEOFF, RobotState.ALT_HOLD),
            conditions=[self.enter_hover_from_takeoff]
        )
        self.machine.add_transition(
            "resolve",
            RobotState.TAKEOFF,
            RobotState.MANUAL,
            before=lambda x: self.on_before_state_changed.emit(RobotState.TAKEOFF, RobotState.MANUAL),
            conditions=[self.enter_manual_from_takeoff]
        )
        # endregion from TAKEOFF

        # region from HOVER
        self.machine.add_transition(
            "resolve",
            RobotState.ALT_HOLD,
            RobotState.MANUAL,
            before=lambda x: self.on_before_state_changed.emit(RobotState.ALT_HOLD, RobotState.MANUAL),
            conditions=[self.enter_manual_mode_from_hover],
        )
        # endregion from HOVER


    def on_state_changed_handler(self, event):
        """
        """
        # TODO: move to app logic
        new_state = _coerce_robot_state(event.transition.dest)
        self.ctx.state = new_state
        log.info(f"State changed: {event.transition.source} -> {event.transition.dest}")
        self.on_state_changed.emit(event.transition.source, event.transition.dest)

        

    # ------------------
    def enter_idle_from_manual(self, event):
        """
        close manual request, throttle low, without ---- confirmed landed to enter idle
        """
        ok = all([
            self.ctx.request_rc.is_manual(),
            not self.ctx.request_rc.is_armed(),
            self.ctx.request_rc.is_throttle_low(),
            # TODO: is it more safety
            # self.ctx.manual_land_confirmed,
        ])
        return ok

    def enter_hover_from_takeoff(self, event) :
        """
        
        """
        ok = all([
            self.ctx.takeoff_reach
            
        ])

        return ok
    
    # def enter_manual_from_takeoff(self, event):
    #     ok = all([
    #         self.ctx.armed,
    #         self.ctx.force_manual_interrupt
    #     ])
    #     return ok
    
   
    def enter_manual_from_alt_hold(self, event):
        ok = all([
            self.ctx.armed,
            self.ctx.request_rc.is_manual(),
        ])
        return  ok
    
    def enter_arm(self, event):
        """
        Require an active arm switch, low throttle, a selected flight mode,
        and an armable disarmed vehicle.
        """
        manual_or_takeoff = any([
            self.ctx.request_rc.is_manual(),
            self.ctx.request_rc.is_auto_takeoff(),
        ])
        ok = all([
            manual_or_takeoff,
            self.ctx.armable,
            not self.ctx.armed,
            self.ctx.request_rc.is_armed(),
            self.ctx.request_rc.is_throttle_low(),
        ])
        return  ok
    
    def enter_takeoff_from_manual(self, event):
        """
        allow only if current alt < takeoff alt setpoint
        """
        ok = all([
            self.ctx.armed,
            self.ctx.request_rc.is_auto_takeoff(),
            self.ctx.drone_alt < self.ctx.alt_setpoint
        ])
        return  ok

    def enter_failsafe(self, event):
        """
        joystick enter fail
        vehicle armed
        active only from manual and takeoff
        # TODO: Must add on AIR or land detector

        """
        ok = all([
            self.ctx.armed,
            self.ctx.joy_fail_safe
        ])

        return ok
    
    def exit_failsafe(self, event):
        # TODO: Add on air
        ok = all([
            self.ctx.armed,
            not self.ctx.joy_fail_safe
        ])

        return ok
    
    def exit_failsafe_to_idle(self, event):
        # TODO: Add on air
        ok = all([
            not self.ctx.joy_fail_safe,
            not self.ctx.request_rc.is_manual(),
            not self.ctx.request_rc.is_auto_takeoff(),
        ])

        return ok
    
    # region manual mode
    def enter_manual_from_takeoff(self, event):
        """
        
        """
        ok = all([
            self.ctx.armed,
            self.ctx.request_rc.is_manual(),
            not self.ctx.request_rc.is_auto_takeoff(),
        ])
        return ok
    
    def enter_manual_mode_from_arm(self, event):
        ok = all([
            self.ctx.armed,
            self.ctx.request_rc.is_manual(),
        ])
        return ok

    def enter_hover_from_manual(self, event):
        ok = all([
            self.ctx.request_rc.throttle > 1050,
            not self.ctx.request_rc.is_manual(),
            self.ctx.armed
        ])
        return ok
    
    def enter_manual_mode_from_hover(self, event):
        ok = all([
            self.ctx.request_rc.is_manual(),
            self.ctx.armed
        ])
        return ok
    
    #endregion manual mode

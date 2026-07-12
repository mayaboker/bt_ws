from loguru import logger as log
from bt_app.common import RobotState
from transitions import Machine
from bt_app.common import Event
from bt_app.vehicle_config import VehicleConfig
from bt_app.context import Context
from bt_app.common import AETR1234

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
        self.machine.add_transition(
            "resolve",
            RobotState.IDLE,
            RobotState.ARM,
            before=lambda x: self.on_before_state_changed.emit(RobotState.IDLE, RobotState.ARM),
            conditions=[self.enter_arm]
        )
        # endregion from IDLE

        # region from ARM
        self.machine.add_transition(
            "resolve",
            RobotState.ARM,
            RobotState.MANUAL,
            conditions=[self.enter_manual_mode_from_arm],
        )

        self.machine.add_transition(
            "resolve",
            RobotState.ARM,
            RobotState.TAKEOFF,
            conditions=[self.enter_takeoff_from_arm]
        )
        # endregion

        # region to FAILSAFE
        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.FAILSAFE,
            conditions=[self.enter_failsafe],
        )
        # endregion to FAILSAFE

        # region from FAILSAFE
        self.machine.add_transition(
            "resolve",
            RobotState.FAILSAFE,
            RobotState.HOVER,
            conditions=[self.exit_failsafe],
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

        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.HOVER,
            before=lambda x: self.on_before_state_changed.emit(RobotState.MANUAL, RobotState.HOVER),
            conditions=[self.enter_hover_from_manual],
        )
        #endregion from manual

        # region from TAKEOFF
        self.machine.add_transition(
            "resolve",
            RobotState.TAKEOFF,
            RobotState.HOVER,
            before=lambda x: self.on_before_state_changed.emit(RobotState.TAKEOFF, RobotState.HOVER),
            conditions=[self.enter_hover_from_takeoff]
        )
        # endregion from TAKEOFF

        # region from HOVER
        self.machine.add_transition(
            "resolve",
            RobotState.HOVER,
            RobotState.MANUAL,
            conditions=[self.enter_manual_mode_from_hover],
        )
        # endregion from HOVER



    def on_state_changed_handler(self, event):
        """
        """
        # TODO: move to app logic
        previous_state = _coerce_robot_state(event.transition.source)
        new_state = _coerce_robot_state(event.transition.dest)
        self.ctx.state = new_state
        log.info(f"State changed: {event.transition.source} -> {event.transition.dest}")
        self.on_state_changed.emit(event.transition.source, event.transition.dest)

        

    # ------------------
    def enter_idle_from_manual(self, event):
        """
        close manual request and throttle low to enter idle
        """
        ok = all([
            not self.ctx.joy_manual_request,
            self.ctx.request_rc[AETR1234.THROTTLE] < 1050,
            self.ctx.request_rc[AETR1234.YAW] > 1950,
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
    
   
    # def enter_idle_from_manual(self, event):
    #     return not self.ctx.joy_manual_request and not self.ctx.takeoff_interrupt and not self.ctx.armable

    
    def enter_arm(self, event):
        """
        joy_arm_requested: true if joy request arm combination, reset when disarmed or arm failed
        self.ctx.armable: true if drone can be armed
        """
        s1_or_s4 = self.ctx.joy_takeoff_request != self.ctx.joy_manual_request
        ok = all([
            s1_or_s4,
            self.ctx.armable,
            not self.ctx.armed,
            self.ctx.joy_arm_requested
        ])
        return  ok
    
    def enter_takeoff_from_arm(self, event):
        s1_or_s4 = self.ctx.joy_takeoff_request != self.ctx.joy_manual_request
        ok = all([
            s1_or_s4,
            self.ctx.armed,
            self.ctx.joy_takeoff_request,
        ])
        return  ok

    def enter_failsafe(self, event):
        # TODO: decide when active failsafe, manual -> fs, hover, takeoff -> ??
        # TODO: Must to Add on air
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
    
    # region manual mode
    def enter_manual_mode_from_arm(self, event):
        s1_or_s4 = self.ctx.joy_takeoff_request != self.ctx.joy_manual_request
        ok = all([
            s1_or_s4,
            self.ctx.armed,
            self.ctx.joy_manual_request
        ])
        return ok

    def enter_hover_from_manual(self, event):
        ok = all([
            self.ctx.request_rc[AETR1234.THROTTLE] > 1050,
            not self.ctx.joy_manual_request,
            self.ctx.armed
        ])
        return ok
    
    def enter_manual_mode_from_hover(self, event):
        ok = all([
            self.ctx.joy_manual_request,
            self.ctx.armed
        ])
        return ok
    #endregion manual mode
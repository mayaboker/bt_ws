from loguru import logger as log
from bt_app.common import RobotState
from transitions import Machine
from bt_app.common import Event

from bt_app.context import Context




class Robot_StateMachine:
    states = list(RobotState)

    def __init__(self, ctx: Context):
        self.ctx: Context = ctx
        self.on_before_state_changed = Event()
        self.machine = Machine(
            model=self,
            states=self.states,
            initial=RobotState.IDLE,
            ignore_invalid_triggers=True,
            send_event=True,
            after_state_change=self.on_state_changed,
        )

        self.machine.add_transition(
            "resolve",
            RobotState.IDLE,
            RobotState.MANUAL,
            conditions=[self.enter_manual_mode],
        )

        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.FAILSAFE,
            conditions=[self.enter_failsafe],
        )

        # self.machine.add_transition(
        #     "resolve",
        #     RobotState.IDLE,
        #     RobotState.TAKEOFF,
        #     conditions=[self.enter_takeoff]
        # )

        self.machine.add_transition(
            "resolve",
            RobotState.IDLE,
            RobotState.ARM,
            before=lambda x: self.on_before_state_changed.emit(RobotState.IDLE, RobotState.ARM),
            conditions=[self.enter_arm]
        )

        self.machine.add_transition(
            "resolve",
            RobotState.ARM,
            RobotState.TAKEOFF,
            conditions=[self.enter_takeoff_from_arm]
        )

        self.machine.add_transition(
            "resolve",
            RobotState.IDLE,
            RobotState.MANUAL,
            conditions=[self.enter_manual_from_idle]
        )

        self.machine.add_transition(
            "resolve",
            RobotState.MANUAL,
            RobotState.IDLE,
            conditions=[self.enter_idle_from_manual]
        )

        self.machine.add_transition(
            "resolve",
            RobotState.TAKEOFF,
            RobotState.MANUAL,
            before=lambda x: self.on_before_state_changed.emit(RobotState.TAKEOFF, RobotState.MANUAL),
            conditions=[self.enter_manual_from_takeoff]
        )

        # self.machine.add_transition(
        #     "resolve",
        #     RobotState.TRACKING,
        #     RobotState.RECOVERY,
        #     conditions=[self.target_lost_but_can_retry],
        # )

        # self.machine.add_transition(
        #     "resolve",
        #     "*",
        #     RobotState.ERROR,
        #     conditions=[self.critical_error],
        # )

    def on_state_changed(self, event):
        """
        """
        # TODO: move to app logic
        previous_state = event.transition.source
        new_state = event.transition.dest
        self.ctx.state = new_state
        log.info(f"State changed: {previous_state} -> {new_state}")

        if new_state == RobotState.IDLE:
            self.ctx.auto_arm = True


    # ------------------
    def enter_manual_from_takeoff(self, event):
        ok = all([
            self.ctx.armed,
            self.ctx.force_manual_interrupt
        ])
        return ok
    
    def enter_takeoff_from_arm(self, event):
        ok = all([
            self.ctx.armed
        ])
        return ok
    
    def enter_idle_from_manual(self, event):
        return not self.ctx.force_manual_interrupt and not self.ctx.takeoff_interrupt and not self.ctx.armable

    def enter_manual_from_idle(self, event):
        return self.ctx.force_manual_interrupt and not self.ctx.takeoff_interrupt

    def enter_arm(self, event):
        ok = all([
            self.ctx.takeoff_interrupt,
            not self.ctx.force_manual_interrupt
        ])
        return  ok
    
    def enter_takeoff(self, event):
        # print(event)
        ok = all([
            self.ctx.takeoff_interrupt,
            not self.ctx.force_manual_interrupt
        ])
        return  ok

    def enter_manual_mode(self, event):
        return (
            self.ctx.force_manual_mode
        )

    def enter_failsafe(self, event):
        # TODO: Add on air
        return (
            self.ctx.armable
            and self.ctx.joy_fail_safe
        )

    



from loguru import logger as log
from bt_app.common import RobotState
from transitions import Machine


from bt_app.context import Context




class Robot_StateMachine:
    states = list(RobotState)

    def __init__(self, ctx: Context):
        self.ctx = ctx

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
            conditions=[self.entry_manual_mode],
        )

        # self.machine.add_transition(
        #     "resolve",
        #     RobotState.SEARCH,
        #     RobotState.TRACKING,
        #     conditions=[self.good_target],
        # )

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
        previous_state = event.transition.source
        new_state = event.transition.dest
        self.ctx.state = new_state
        log.info(f"State changed: {previous_state} -> {new_state}")


    def entry_manual_mode(self, event):
        return (
            self.ctx.force_manual_mode
        )

    def good_target(self, event):
        return (
            self.ctx.target_found
            and self.ctx.target_confidence > 0.75
        )

    def target_lost_but_can_retry(self, event):
        return (
            not self.ctx.target_found
            and self.ctx.retry_count < 3
        )

    def critical_error(self, event):
        return (
            self.ctx.error
            or self.ctx.battery_voltage < 9.5
            or self.ctx.retry_count >= 3
        )


# robot = Robot()

# robot.ctx.camera_connected = True
# robot.ctx.battery_voltage = 11.8
# robot.resolve()
# print(robot.state)  # RobotState.SEARCH

# robot.ctx.target_found = True
# robot.ctx.target_confidence = 0.9
# robot.resolve()
# print(robot.state)  # RobotState.TRACKING

# robot.ctx.target_found = False
# robot.ctx.retry_count = 1
# robot.resolve()
# print(robot.state)  # RobotState.RECOVERY
from bt_app.control import joy_zmq_adapter
from bt_app.sm import Robot_StateMachine
from bt_app.context import Context
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
        
        # load controllers
        self.__load_controllers()

    def __load_controllers(self):
        self.adapter = joy_zmq_adapter.JoyZmqAdapter()
        self.adapter.start()

    def __update_state(self):
        # update state based on context
        pass

    def __resolve_rc(self):
        if self.ctx.state == "MANUAL":
            return self.adapter.pull_rc_channels()
        else:
            log.error(f"RC selector not implemented for state {self.ctx.state}")
            raise NotImplementedError(f"RC selector not implemented for state {self.ctx.state}")

    def run(self):
        try:
            while True:
                time.sleep(1)
                self.__update_state()
                self.robot_sm.resolve()
                print(f"RC Channels: {self.__resolve_rc()}")
        except KeyboardInterrupt:
            print("Stopping...")
            self.adapter.stop()

def main():
    app = App()
    app.run()
   

if __name__ == "__main__":
    main()
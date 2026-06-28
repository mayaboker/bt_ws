from bt_app.control import joy_zmq_adapter
import time

def main():
    adapter = joy_zmq_adapter.JoyZmqAdapter()
    adapter.start()
    try:
        while True:
            time.sleep(1)
            print(f"RC Channels: {adapter.pull_rc_channels()}")
    except KeyboardInterrupt:
        print("Stopping...")
        adapter.stop()

if __name__ == "__main__":
    main()
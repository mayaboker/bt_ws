import socket
import time

import zmq
from bt_msgs import TargetSelectorCommandMessage, TargetSelectorState

from bt_gst.selector_subscriber import ZmqSelectorSubscriber


def tcp_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
        tcp_socket.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{tcp_socket.getsockname()[1]}"


def test_subscriber_receives_latest_valid_command_and_disables_stale_command():
    endpoint = tcp_endpoint()
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.bind(endpoint)
    subscriber = ZmqSelectorSubscriber(endpoint)
    subscriber.start()
    command = TargetSelectorCommandMessage(
        timestamp_ns=1,
        center_x=0.2,
        center_y=0.7,
        state=TargetSelectorState.SELECTING,
    )
    try:
        time.sleep(0.1)
        deadline = time.monotonic() + 1.0
        received = None
        while received is None and time.monotonic() < deadline:
            publisher.send(command.encode())
            time.sleep(0.02)
            received = subscriber.latest(max_age_s=1.0)
        assert received == command
        stale = subscriber.latest(max_age_s=0.01, now_s=time.monotonic() + 1.0)
        assert stale.state == TargetSelectorState.DISABLED
        assert (stale.center_x, stale.center_y) == (0.2, 0.7)
    finally:
        subscriber.stop()
        publisher.close(linger=0)
        context.term()


def test_subscriber_drops_malformed_command_and_keeps_running():
    endpoint = tcp_endpoint()
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.bind(endpoint)
    subscriber = ZmqSelectorSubscriber(endpoint)
    subscriber.start()
    try:
        time.sleep(0.1)
        publisher.send(b"not-msgpack")
        time.sleep(0.05)
        assert subscriber.latest(max_age_s=1.0) is None
        assert subscriber._thread is not None and subscriber._thread.is_alive()
    finally:
        subscriber.stop()
        publisher.close(linger=0)
        context.term()

import socket
import time

import pytest
import zmq
from bt_msgs import TrackerResultMessage

from bt_gst.zmq_publisher import ZmqFramePublisher, ZmqPublisherError


def tcp_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
        tcp_socket.bind(("127.0.0.1", 0))
        _, port = tcp_socket.getsockname()
    return f"tcp://127.0.0.1:{port}"


def receive_with_timeout(receiver: zmq.Socket, timeout: float = 1.0) -> bytes:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return receiver.recv(flags=zmq.NOBLOCK)
        except zmq.Again:
            time.sleep(0.01)
    raise AssertionError("timed out waiting for tracker-result packet")


def test_publishes_tracker_result_message() -> None:
    endpoint = tcp_endpoint()
    publisher = ZmqFramePublisher(endpoint)
    context = zmq.Context()
    receiver = context.socket(zmq.SUB)
    receiver.setsockopt(zmq.LINGER, 0)
    receiver.setsockopt(zmq.SUBSCRIBE, b"")
    receiver.connect(endpoint)
    publisher.start()
    try:
        # Allow the PUB/SUB subscription to propagate, then publish frames until
        # one tracker result reaches the subscriber.
        time.sleep(0.1)
        for frame_id in range(1, 5):
            publisher.publish(
                TrackerResultMessage(frame_id=frame_id, timestamp=frame_id * 10)
            )
            time.sleep(0.04)
        payload = receive_with_timeout(receiver)
        message = TrackerResultMessage.decode(payload)
        assert 1 <= message.frame_id <= 4
        assert message.timestamp == message.frame_id * 10
    finally:
        publisher.stop()
        receiver.close(linger=0)
        context.term()


def test_reports_bind_failure_during_startup() -> None:
    endpoint = tcp_endpoint()
    context = zmq.Context()
    occupied = context.socket(zmq.PUB)
    occupied.setsockopt(zmq.LINGER, 0)
    occupied.bind(endpoint)
    publisher = ZmqFramePublisher(endpoint)
    try:
        with pytest.raises(ZmqPublisherError, match="could not start"):
            publisher.start()
    finally:
        publisher.stop()
        occupied.close(linger=0)
        context.term()


def test_frame_bursts_are_rate_limited() -> None:
    endpoint = tcp_endpoint()
    publisher = ZmqFramePublisher(endpoint, max_rate_hz=10)
    context = zmq.Context()
    receiver = context.socket(zmq.SUB)
    receiver.setsockopt(zmq.LINGER, 0)
    receiver.setsockopt(zmq.SUBSCRIBE, b"")
    receiver.connect(endpoint)
    publisher.start()
    try:
        time.sleep(0.1)
        start = time.monotonic()
        submitted = 0
        while time.monotonic() - start < 0.25:
            submitted += 1
            publisher.publish(
                TrackerResultMessage(frame_id=submitted, timestamp=submitted)
            )
            time.sleep(0.001)
        time.sleep(0.15)

        received = []
        while True:
            try:
                received.append(
                    TrackerResultMessage.decode(receiver.recv(flags=zmq.NOBLOCK))
                )
            except zmq.Again:
                break
        assert 1 <= len(received) <= 4
        assert received[-1].frame_id == submitted
    finally:
        publisher.stop()
        receiver.close(linger=0)
        context.term()

import socket
import time

import pytest

from bt_gst.zmq_io import ZmqTrackerIoAdapter
from bt_gst.zmq_models import (
    TrackerDataMessage,
    TrackerDebugMessage,
    TrackResizeRequest,
    TrackStartRequest,
    decode_tracker_message,
    encode_message,
)

zmq = pytest.importorskip("zmq")


def tcp_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
    return f"tcp://127.0.0.1:{port}"


def wait_for_message(receiver: object, timeout: float = 1.0) -> bytes:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return receiver.recv(flags=zmq.NOBLOCK)
        except zmq.Again:
            time.sleep(0.01)
    raise AssertionError("timed out waiting for ZMQ message")


def test_zmq_adapter_receives_latest_request_only() -> None:
    context = zmq.Context()
    request_endpoint = tcp_endpoint()
    telemetry_endpoint = tcp_endpoint()
    adapter = ZmqTrackerIoAdapter(
        request_endpoint=request_endpoint,
        telemetry_endpoint=telemetry_endpoint,
        context=context,
    )
    publisher = context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.connect(request_endpoint)
    time.sleep(0.1)
    assert adapter.poll_latest_request() is None

    try:
        for _ in range(10):
            publisher.send(encode_message(TrackStartRequest(x=1, y=2)))
            publisher.send(encode_message(TrackResizeRequest(width=30, height=40)))
            time.sleep(0.02)

        assert adapter.poll_latest_request() == TrackResizeRequest(
            width=30,
            height=40,
        )
    finally:
        publisher.close(linger=0)
        adapter.close()
        context.term()


def test_zmq_adapter_publishes_tracker_data() -> None:
    context = zmq.Context()
    request_endpoint = tcp_endpoint()
    telemetry_endpoint = tcp_endpoint()
    adapter = ZmqTrackerIoAdapter(
        request_endpoint=request_endpoint,
        telemetry_endpoint=telemetry_endpoint,
        context=context,
    )
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt(zmq.LINGER, 0)
    subscriber.setsockopt(zmq.SUBSCRIBE, b"")
    subscriber.connect(telemetry_endpoint)
    time.sleep(0.1)

    try:
        message = TrackerDataMessage(
            frame_id=1,
            timestamp=123.5,
            dx=2,
            dy=-3,
            score=0.5,
            status=1,
        )
        adapter.publish_tracker_data(message)

        assert decode_tracker_message(wait_for_message(subscriber)) == message
    finally:
        subscriber.close(linger=0)
        adapter.close()
        context.term()


def test_zmq_adapter_publishes_tracker_debug() -> None:
    context = zmq.Context()
    request_endpoint = tcp_endpoint()
    telemetry_endpoint = tcp_endpoint()
    adapter = ZmqTrackerIoAdapter(
        request_endpoint=request_endpoint,
        telemetry_endpoint=telemetry_endpoint,
        context=context,
    )
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt(zmq.LINGER, 0)
    subscriber.setsockopt(zmq.SUBSCRIBE, b"")
    subscriber.connect(telemetry_endpoint)
    time.sleep(0.1)

    try:
        message = TrackerDebugMessage(
            frame_number=2,
            status=1,
            active_feature_count=3,
            features_json="[]",
        )
        adapter.publish_tracker_debug(message)

        assert decode_tracker_message(wait_for_message(subscriber)) == message
    finally:
        subscriber.close(linger=0)
        adapter.close()
        context.term()


def test_zmq_adapter_ignores_invalid_payload() -> None:
    context = zmq.Context()
    request_endpoint = tcp_endpoint()
    telemetry_endpoint = tcp_endpoint()
    adapter = ZmqTrackerIoAdapter(
        request_endpoint=request_endpoint,
        telemetry_endpoint=telemetry_endpoint,
        context=context,
    )
    publisher = context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.connect(request_endpoint)
    time.sleep(0.1)

    try:
        publisher.send(b"not-messagepack")
        time.sleep(0.05)

        assert adapter.poll_latest_request() is None
    finally:
        publisher.close(linger=0)
        adapter.close()
        context.term()

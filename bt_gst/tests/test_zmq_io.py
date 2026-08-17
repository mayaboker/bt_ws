import socket
import time

import pytest

from bt_gst.bridge.zmq_io import ZmqDetectionIoAdapter, ZmqTelemetryPublisher
from bt_gst.bridge.zmq_models import (
    RedDetectionMessage,
    decode_telemetry_message,
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


def test_zmq_adapter_receives_requests_in_order() -> None:
    context = zmq.Context()
    request_endpoint = tcp_endpoint()
    telemetry_endpoint = tcp_endpoint()
    adapter = ZmqDetectionIoAdapter(
        request_endpoint=request_endpoint,
        telemetry_endpoint=telemetry_endpoint,
        context=context,
    )
    publisher = context.socket(zmq.PUB)
    publisher.setsockopt(zmq.LINGER, 0)
    publisher.connect(request_endpoint)
    try:
        expected = [
            {"type": "start", "x": 1, "y": 2},
            {"type": "resize", "width": 30, "height": 40},
        ]
        requests = []
        deadline = time.time() + 2.0
        while time.time() < deadline:
            for request in expected:
                publisher.send(encode_message(request))
            time.sleep(0.05)
            requests.extend(adapter.poll_requests())
            if any(
                requests[index : index + 2] == expected
                for index in range(len(requests) - 1)
            ):
                break

        assert any(
            requests[index : index + 2] == expected
            for index in range(len(requests) - 1)
        )
    finally:
        publisher.close(linger=0)
        adapter.close()
        context.term()


def test_zmq_telemetry_publisher_publishes_red_detection() -> None:
    context = zmq.Context()
    telemetry_endpoint = tcp_endpoint()
    publisher = ZmqTelemetryPublisher(
        telemetry_endpoint=telemetry_endpoint,
        context=context,
    )
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt(zmq.LINGER, 0)
    subscriber.setsockopt(zmq.SUBSCRIBE, b"")
    subscriber.connect(telemetry_endpoint)
    time.sleep(0.1)
    message = RedDetectionMessage(1, 123, True, 10, 20, 30, 40)

    try:
        publisher.publish_red_detection(message)
        assert decode_telemetry_message(wait_for_message(subscriber)) == message
    finally:
        subscriber.close(linger=0)
        publisher.close()
        context.term()


def test_zmq_adapter_ignores_invalid_payload() -> None:
    context = zmq.Context()
    request_endpoint = tcp_endpoint()
    telemetry_endpoint = tcp_endpoint()
    adapter = ZmqDetectionIoAdapter(
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

        assert adapter.poll_requests() == []
    finally:
        publisher.close(linger=0)
        adapter.close()
        context.term()

import threading
import time

import zmq
from bt_msgs import TrackerResultMessage

from bt_app.visual_bridge import VisualTargetComm
from bt_app.visual_bridge import VisualBridgeManager
import bt_app.visual_bridge.manager as manager_module


def _publish_until_received(publisher, payload, received, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not received.wait(0.02):
        publisher.send(payload)
    assert received.is_set()


def test_visual_target_comm_delivers_tracker_result():
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    port = publisher.bind_to_random_port("tcp://127.0.0.1")
    received = threading.Event()
    results = []
    comm = VisualTargetComm(
        endpoint=f"tcp://127.0.0.1:{port}",
        context=context,
        on_result=lambda result: (results.append(result), received.set()),
    )
    try:
        comm.start()
        assert comm.is_running
        message = TrackerResultMessage(frame_id=7, timestamp_ns=123)
        _publish_until_received(publisher, message.encode(), received)
        assert results[-1] == message
    finally:
        comm.stop()
        comm.stop()
        publisher.close(linger=0)
        context.term()
    assert not comm.is_running


def test_visual_target_comm_survives_bad_payload_and_callback_error():
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    port = publisher.bind_to_random_port("tcp://127.0.0.1")
    received = threading.Event()
    calls = []

    def callback(result):
        calls.append(result.frame_id)
        if len(calls) == 1:
            raise RuntimeError("consumer failed")
        received.set()

    comm = VisualTargetComm(
        endpoint=f"tcp://127.0.0.1:{port}", context=context, on_result=callback
    )
    try:
        comm.start()
        publisher.send(b"not-messagepack")
        first = TrackerResultMessage(frame_id=1, timestamp_ns=None).encode()
        deadline = time.monotonic() + 2.0
        while not calls and time.monotonic() < deadline:
            publisher.send(first)
            time.sleep(0.02)
        assert calls
        _publish_until_received(
            publisher,
            TrackerResultMessage(frame_id=2, timestamp_ns=456).encode(),
            received,
        )
        assert calls[-1] == 2
    finally:
        comm.stop()
        publisher.close(linger=0)
        context.term()


def test_visual_target_comm_surfaces_startup_failure():
    comm = VisualTargetComm(endpoint="invalid://endpoint")
    try:
        try:
            comm.start()
        except RuntimeError as exc:
            assert "unable to start" in str(exc)
        else:
            raise AssertionError("invalid endpoint unexpectedly started")
    finally:
        comm.stop()


def test_visual_bridge_manager_owns_comm_and_logs_result(monkeypatch):
    calls = []

    class FakeComm:
        def __init__(self, *, endpoint, on_result):
            calls.append(("init", endpoint))
            self.on_result = on_result
            self.is_running = False

        def start(self):
            self.is_running = True
            calls.append(("start",))

        def stop(self):
            self.is_running = False
            calls.append(("stop",))

    class FakeLog:
        def info(self, message, *args):
            calls.append(("log", message, args))

    monkeypatch.setattr(manager_module, "VisualTargetComm", FakeComm)
    monkeypatch.setattr(manager_module, "log", FakeLog())

    manager = VisualBridgeManager("tcp://127.0.0.1:6000")
    manager.start()
    manager._comm.on_result(TrackerResultMessage(frame_id=8, timestamp_ns=900))

    assert manager.is_running
    assert calls == [
        ("init", "tcp://127.0.0.1:6000"),
        ("start",),
        (
            "log",
            "Incoming tracker result frame_id={} timestamp_ns={}",
            (8, 900),
        ),
    ]

    manager.stop()
    assert not manager.is_running
    assert calls[-1] == ("stop",)

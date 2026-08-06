import socket
import time
from types import SimpleNamespace

import msgpack
import zmq

from bt_app.app import App
import bt_app.control.visual_controller as visual_controller_module
from bt_app.control.visual_controller import (
    VisualDetectionMessage,
    VisualTargetComm,
    VisualTrackerObserver,
    decode_visual_detection,
    normalized_target_error,
)
from bt_app.parameters.generated import ParameterKey


class ParameterChanges:
    def __init__(self):
        self.callbacks = []

    def subscribe(self, callback):
        self.callbacks.append(callback)


class FakeParameters:
    def __init__(self):
        self.on_parameter_changed = ParameterChanges()
        self.values = {
            ParameterKey.VIS_HOV_THR: 0.55,
            ParameterKey.VIS_FWD_PITCH: -20.0,
            ParameterKey.VIS_MAX_PITCH: 60.0,
            ParameterKey.VIS_MAX_THR: 0.85,
            ParameterKey.VIS_KP_YAW: 1.0,
            ParameterKey.VIS_MAX_YAW: 15.0,
            ParameterKey.VIS_KP_PITCH: 1.0,
            ParameterKey.VIS_KP_THR: 0.06,
            ParameterKey.BF_YAW_RATE: 67.0,
        }

    def get(self, name):
        return self.values[name]


def detection_payload(**overrides) -> bytes:
    data = {
        "type": "red-detection",
        "frame_id": 7,
        "timestamp_ns": 123,
        "found": True,
        "x": 240,
        "y": 180,
        "width": 160,
        "height": 120,
    }
    data.update(overrides)
    return msgpack.packb(data, use_bin_type=True)


def tcp_endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{sock.getsockname()[1]}"


def test_decode_visual_detection() -> None:
    assert decode_visual_detection(detection_payload()) == VisualDetectionMessage(
        frame_id=7,
        timestamp_ns=123,
        found=True,
        x=240,
        y=180,
        width=160,
        height=120,
    )


def test_decode_visual_detection_reads_lock_state() -> None:
    detection = decode_visual_detection(
        detection_payload(
            locked=True,
            lock_found_frames=10,
            lock_missing_frames=2,
        )
    )

    assert detection is not None
    assert detection.locked
    assert detection.lock_found_frames == 10
    assert detection.lock_missing_frames == 2


def test_visual_command_is_fixed_forward_pitch_with_bounded_yaw() -> None:
    observer = VisualTrackerObserver(FakeParameters())

    observation = observer.resolve(
        VisualDetectionMessage(1, 0, True, 560, 0, 80, 80, locked=True)
    )

    # Negative semantic pitch is mapped to this vehicle's forward RC direction.
    assert observation.command.pitch > 1500
    assert observation.command.roll == 1500
    assert observation.error_x > 0
    assert observation.command.yaw > 1500
    assert abs(observation.command.yaw - 1500) <= round(500 * 15.0 / 67.0)


def test_decode_visual_detection_ignores_other_telemetry() -> None:
    payload = msgpack.packb({"type": "tracker-data"}, use_bin_type=True)
    assert decode_visual_detection(payload) is None


def test_normalized_target_error() -> None:
    centered = VisualDetectionMessage(1, 0, True, 240, 180, 160, 120)
    top_right = VisualDetectionMessage(2, 1, True, 639, -20, 20, 20)
    lost = VisualDetectionMessage(3, 2, False, 100, 100, 20, 20)

    assert normalized_target_error(centered, image_width=640, image_height=480) == (
        0.0,
        0.0,
    )
    assert normalized_target_error(top_right, image_width=640, image_height=480) == (
        1.0,
        1.0,
    )
    assert normalized_target_error(lost, image_width=640, image_height=480) == (
        0.0,
        0.0,
    )


def test_observer_prints_at_rate_and_on_state_changes(monkeypatch) -> None:
    times = iter([0.0, 0.1, 0.2, 0.3, 0.71])
    observer = VisualTrackerObserver(
        FakeParameters(),
        print_rate_hz=2.0,
        clock=lambda: next(times),
    )
    printed = []
    monkeypatch.setattr(observer, "_print_observation", printed.append)
    found = VisualDetectionMessage(1, 0, True, 240, 180, 160, 120)
    lost = VisualDetectionMessage(2, 1, False, 0, 0, 0, 0)

    first = observer.resolve(found)
    observer.resolve(found)
    lost_first = observer.resolve(lost)
    observer.resolve(lost)
    periodic = observer.resolve(lost)

    assert printed == [first, lost_first, periodic]
    assert first.command.to_list()


def test_observer_requires_post_enable_fresh_result() -> None:
    now = [10.0]
    observer = VisualTrackerObserver(FakeParameters(), clock=lambda: now[0])
    detection = VisualDetectionMessage(1, 0, True, 240, 180, 160, 120)

    observer.resolve(detection)
    assert observer.is_healthy(1.0, now=10.5)
    assert (
        observer.fresh_observation(
            received_after=10.0,
            max_age_s=0.25,
            now=10.1,
        )
        is None
    )

    now[0] = 10.1
    fresh = observer.resolve(detection)
    assert observer.fresh_observation(
        received_after=10.0,
        max_age_s=0.25,
        now=10.2,
    ) == fresh
    assert (
        observer.fresh_observation(
            received_after=10.0,
            max_age_s=0.25,
            now=10.36,
        )
        is None
    )


def test_visual_target_comm_receives_single_frame_detection() -> None:
    endpoint = tcp_endpoint()
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind(endpoint)
    received = []
    comm = VisualTargetComm(
        endpoint=endpoint,
        context=context,
        on_result=received.append,
        poll_timeout_ms=10,
    )
    comm.start()
    time.sleep(0.1)

    try:
        deadline = time.monotonic() + 1.0
        while not received and time.monotonic() < deadline:
            publisher.send(detection_payload())
            time.sleep(0.02)
        assert received
        assert received[-1].frame_id == 7
    finally:
        comm.stop()
        publisher.close(linger=0)
        context.term()


def test_app_loads_and_starts_visual_observer(monkeypatch) -> None:
    created = []

    class FakeObserver:
        def __init__(self, params, **kwargs):
            self.params = params
            self.kwargs = kwargs
            self.started = False
            created.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(
        visual_controller_module,
        "VisualTrackerObserver",
        FakeObserver,
    )
    app = App.__new__(App)
    app._App__params = object()
    app.config = SimpleNamespace(
        visual_observer_enabled=True,
        visual_zmq_endpoint="tcp://127.0.0.1:6000",
        visual_image_width=800,
        visual_image_height=600,
        visual_print_rate_hz=4.0,
    )

    observer = app._App__load_visual_observer()

    assert observer is created[0]
    assert observer.started
    assert observer.params is app._App__params
    assert observer.kwargs == {
        "endpoint": "tcp://127.0.0.1:6000",
        "image_width": 800,
        "image_height": 600,
        "print_rate_hz": 4.0,
    }

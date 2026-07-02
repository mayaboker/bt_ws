import time

import pytest
from pymavlink import mavutil

import bt_app.app as app_module
from bt_app.app import App
from bt_app.common import RobotState
from bt_app.context import Context
from bt_app.mavlink_wrapper import MavlinkService, make_base_mode
from bt_app.vehicle_config import VehicleConfig


@pytest.fixture(autouse=True)
def reset_singletons():
    Context._instance = None
    Context._initialized = False
    VehicleConfig._instance = None
    VehicleConfig._initialized = False
    yield
    Context._instance = None
    Context._initialized = False
    VehicleConfig._instance = None
    VehicleConfig._initialized = False


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    def sendto(self, payload, addr):
        self.sent.append((payload, addr))

    def close(self):
        self.closed = True


class FakeMavlinkService:
    instances = []

    def __init__(self, *, context):
        self.context = context
        self.started = False
        self.stopped = False
        FakeMavlinkService.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def decode_mavlink(payload):
    parser = mavutil.mavlink.MAVLink(None)
    msg = None
    for byte in payload:
        parsed = parser.parse_char(bytes([byte]))
        if parsed is not None:
            msg = parsed
    return msg


def test_make_base_mode_sets_custom_mode_flag_only_when_disarmed():
    base_mode = make_base_mode(False)

    assert base_mode & mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    assert not base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED


def test_make_base_mode_sets_armed_flag_when_armed():
    base_mode = make_base_mode(True)

    assert base_mode & mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    assert base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED


def test_heartbeat_reads_context_state_and_armed_flag():
    ctx = Context()
    ctx.state = RobotState.SEARCH
    ctx.armed = True
    service = MavlinkService(context=ctx)
    socket = FakeSocket()
    service._socket = socket

    service._send_heartbeat()

    assert socket.sent
    payload, addr = socket.sent[0]
    msg = decode_mavlink(payload)
    assert addr == service.qopenhd_addr
    assert msg.get_type() == "HEARTBEAT"
    assert msg.custom_mode == int(RobotState.SEARCH)
    assert msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED


def test_start_is_idempotent_and_uses_named_daemon_thread():
    class WaitingService(MavlinkService):
        def __init__(self, *, context):
            super().__init__(context=context)
            self.run_count = 0

        def _run(self):
            self.run_count += 1
            self._stop_event.wait(1.0)

    service = WaitingService(context=Context())

    service.start()
    service.start()
    time.sleep(0.05)

    assert service.run_count == 1
    assert service._thread is not None
    assert service._thread.name == "mavlink-service"
    assert service._thread.daemon

    service.stop()


def test_stop_closes_existing_socket():
    service = MavlinkService(context=Context())
    socket = FakeSocket()
    service._socket = socket

    service.stop()

    assert socket.closed
    assert service._socket is None


def test_app_starts_mavlink_service_with_shared_context(monkeypatch):
    FakeMavlinkService.instances = []
    monkeypatch.setattr(app_module, "MavlinkService", FakeMavlinkService)
    monkeypatch.setattr(App, "_App__load_parameters", lambda self: object())
    monkeypatch.setattr(App, "_App__load_drone_interface", lambda self: None)
    monkeypatch.setattr(App, "_App__load_controllers", lambda self: None)

    app = App()

    assert isinstance(app.mavlink_service, FakeMavlinkService)
    assert app.mavlink_service.context is app.ctx
    assert app.mavlink_service.started


def test_app_run_stops_mavlink_service_on_shutdown(monkeypatch):
    service = FakeMavlinkService(context=Context())
    app = App.__new__(App)
    app.mavlink_service = service

    def raise_keyboard_interrupt(_self):
        raise KeyboardInterrupt

    monkeypatch.setattr(App, "_App__update_state", raise_keyboard_interrupt)

    app.run()

    assert service.stopped

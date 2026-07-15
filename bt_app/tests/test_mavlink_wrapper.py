import struct

import pytest
from pymavlink import mavutil

import bt_app.app as app_module
import bt_app.mavlink_wrapper as mavlink_module
from bt_app.app import App
from bt_app.common import RobotState
from bt_app.context import Context
from bt_app.mavlink_wrapper import (
    GlobalPositionIntCommand,
    HeartbeatCommand,
    MavlinkService,
    ReceivePendingCommand,
    SendChannelStatusV2ExtensionCommand,
    SendRcChannelsCommand,
    SysStatusCommand,
    V2_EXTENSION_CHANNEL_STATUS_MESSAGE_TYPE,
    V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT,
    make_base_mode,
)
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

    def __init__(self, *, context, qopenhd_addr=None):
        self.context = context
        self.qopenhd_addr = qopenhd_addr
        self.started = False
        self.stopped = False
        FakeMavlinkService.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send_text_to_gcs(self, text, severity=mavutil.mavlink.MAV_SEVERITY_INFO):
        self.text = text
        self.severity = severity


class FakeRcRecorder:
    def __init__(self):
        self.records = []
        self.stopped = False

    def record(self, state, channels):
        self.records.append((state, list(channels)))

    def stop(self):
        self.stopped = True


class FakeScheduler:
    instances = []

    def __init__(self, *, context, on_error=None):
        self.context = context
        self.on_error = on_error
        self.started = False
        self.stopped = False
        self.scheduled = []
        FakeScheduler.instances.append(self)

    def start(self):
        self.started = True

    def stop(self, timeout=2.0):
        self.stopped = True

    def schedule(self, command, interval_s, delay_s=0.0, key=None):
        self.scheduled.append((command, interval_s, delay_s, key))


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
    ctx.state = RobotState.HOVER
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
    assert msg.custom_mode == int(RobotState.HOVER)
    assert msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED


def test_start_is_idempotent_and_starts_scheduler_once(monkeypatch):
    FakeScheduler.instances = []
    monkeypatch.setattr(mavlink_module, "CommandScheduler", FakeScheduler)

    class WaitingService(MavlinkService):
        def __init__(self, *, context):
            super().__init__(context=context)
            self.open_count = 0

        def _open_socket(self):
            self.open_count += 1
            self._socket = FakeSocket()

    service = WaitingService(context=Context())

    service.start()
    service.start()

    scheduler = FakeScheduler.instances[0]
    assert service.open_count == 1
    assert scheduler.started
    assert len(scheduler.scheduled) == 6
    assert isinstance(scheduler.scheduled[0][0], HeartbeatCommand)
    assert scheduler.scheduled[0][1] == service.heartbeat_interval_s
    assert scheduler.scheduled[0][3] == HeartbeatCommand.key
    assert isinstance(scheduler.scheduled[1][0], GlobalPositionIntCommand)
    assert scheduler.scheduled[1][1] == 0.5
    assert scheduler.scheduled[1][3] == GlobalPositionIntCommand.key
    assert isinstance(scheduler.scheduled[2][0], SysStatusCommand)
    assert scheduler.scheduled[2][1] == 2.0
    assert scheduler.scheduled[2][3] == SysStatusCommand.key
    assert isinstance(scheduler.scheduled[3][0], SendRcChannelsCommand)
    assert scheduler.scheduled[3][1] == service.rc_channels_interval_s
    assert scheduler.scheduled[3][3] == SendRcChannelsCommand.key
    assert isinstance(scheduler.scheduled[4][0], SendChannelStatusV2ExtensionCommand)
    assert scheduler.scheduled[4][1] == 0.1
    assert scheduler.scheduled[4][3] == SendChannelStatusV2ExtensionCommand.key
    assert isinstance(scheduler.scheduled[5][0], ReceivePendingCommand)
    assert scheduler.scheduled[5][1] == service.poll_interval_s
    assert scheduler.scheduled[5][3] == ReceivePendingCommand.key

    service.stop()
    assert not service._started


def test_stop_closes_existing_socket_and_stops_scheduler(monkeypatch):
    FakeScheduler.instances = []
    monkeypatch.setattr(mavlink_module, "CommandScheduler", FakeScheduler)
    service = MavlinkService(context=Context())
    socket = FakeSocket()
    service._socket = socket

    service.stop()

    assert FakeScheduler.instances[0].stopped
    assert socket.closed
    assert service._socket is None
    assert not service._started


def test_heartbeat_command_sends_heartbeat():
    service = MavlinkService(context=Context())
    socket = FakeSocket()
    service._socket = socket

    HeartbeatCommand(service).execute(service.context)

    assert socket.sent


def test_global_position_int_reads_context_altitude():
    ctx = Context()
    ctx.drone_alt = 12.5
    service = MavlinkService(context=ctx)
    socket = FakeSocket()
    service._socket = socket

    service._send_global_position_int()

    assert socket.sent
    payload, addr = socket.sent[0]
    msg = decode_mavlink(payload)
    assert addr == service.qopenhd_addr
    assert msg.get_type() == "GLOBAL_POSITION_INT"
    assert msg.lat == 0
    assert msg.lon == 0
    assert msg.alt == 12500
    assert msg.relative_alt == 12500
    assert msg.vx == 0
    assert msg.vy == 0
    assert msg.vz == 0
    assert msg.hdg == 65535


def test_global_position_int_command_sends_global_position():
    service = MavlinkService(context=Context())
    socket = FakeSocket()
    service._socket = socket

    GlobalPositionIntCommand(service).execute(service.context)

    assert socket.sent


def test_sys_status_reads_context_battery_voltage():
    ctx = Context()
    ctx.battery_voltage = 16.1
    service = MavlinkService(context=ctx)
    socket = FakeSocket()
    service._socket = socket

    service._send_sys_status()

    assert socket.sent
    payload, addr = socket.sent[0]
    msg = decode_mavlink(payload)
    assert addr == service.qopenhd_addr
    assert msg.get_type() == "SYS_STATUS"
    assert msg.voltage_battery == 16100
    assert msg.current_battery == -1
    assert msg.battery_remaining == -1
    assert msg.drop_rate_comm == 0
    assert msg.errors_comm == 0


def test_sys_status_clamps_voltage_to_uint16():
    ctx = Context()
    ctx.battery_voltage = 2016.1
    service = MavlinkService(context=ctx)
    socket = FakeSocket()
    service._socket = socket

    service._send_sys_status()

    payload, _addr = socket.sent[0]
    msg = decode_mavlink(payload)
    assert msg.voltage_battery == 65535


def test_sys_status_command_sends_sys_status():
    service = MavlinkService(context=Context())
    socket = FakeSocket()
    service._socket = socket

    SysStatusCommand(service).execute(service.context)

    assert socket.sent


def test_receive_pending_command_calls_receive_pending():
    class WaitingService(MavlinkService):
        def __init__(self, *, context):
            super().__init__(context=context)
            self.receive_count = 0

        def _receive_pending(self):
            self.receive_count += 1

    service = WaitingService(context=Context())

    ReceivePendingCommand(service).execute(service.context)

    assert service.receive_count == 1


def test_channel_status_v2_extension_reads_sent_rc_and_state():
    ctx = Context()
    ctx.state = RobotState.HOVER
    ctx.sent_rc = [1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800]
    service = MavlinkService(context=ctx)
    socket = FakeSocket()
    service._socket = socket

    service._send_channel_status_v2_extension()

    assert socket.sent
    payload, addr = socket.sent[0]
    msg = decode_mavlink(payload)
    assert addr == service.qopenhd_addr
    assert msg.get_type() == "V2_EXTENSION"
    assert msg.message_type == V2_EXTENSION_CHANNEL_STATUS_MESSAGE_TYPE
    unpacked = struct.unpack(
        V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT,
        bytes(msg.payload[: struct.calcsize(V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT)]),
    )
    assert unpacked == (
        1,
        1,
        int(RobotState.HOVER),
        0,
        1100,
        1200,
        1300,
        1400,
        1500,
        1600,
        1700,
        1800,
    )


def test_channel_status_v2_extension_uses_safe_defaults_without_sent_rc():
    ctx = Context()
    service = MavlinkService(context=ctx)
    socket = FakeSocket()
    service._socket = socket

    service._send_channel_status_v2_extension()

    payload, _addr = socket.sent[0]
    msg = decode_mavlink(payload)
    unpacked = struct.unpack(
        V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT,
        bytes(msg.payload[: struct.calcsize(V2_EXTENSION_CHANNEL_STATUS_PAYLOAD_FORMAT)]),
    )
    assert unpacked[4:] == (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)


def test_app_starts_mavlink_service_with_shared_context(monkeypatch):
    FakeMavlinkService.instances = []
    monkeypatch.setattr(app_module, "MavlinkService", FakeMavlinkService)
    monkeypatch.setattr(App, "_App__load_parameters", lambda self: object())
    monkeypatch.setattr(App, "_App__load_manual_land_detector", lambda self: object())
    monkeypatch.setattr(App, "_App__load_drone_interface", lambda self: None)
    monkeypatch.setattr(App, "_App__load_controllers", lambda self: None)

    app = App(VehicleConfig())

    assert isinstance(app.mavlink_service, FakeMavlinkService)
    assert app.mavlink_service.context is app.ctx
    assert app.mavlink_service.qopenhd_addr == ("127.0.0.1", 14550)
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


def test_app_run_updates_sent_rc_before_dispatch(monkeypatch):
    service = FakeMavlinkService(context=Context())
    app = App.__new__(App)
    app.ctx = Context()
    app.config = VehicleConfig()
    app.robot_sm = type("RobotSm", (), {"resolve": lambda self: None})()
    app.mavlink_service = service
    app.rc_recorder = FakeRcRecorder()
    dispatched = []

    class FakeDispatcher:
        def set_rc(self, channels):
            dispatched.append(list(channels))
            raise KeyboardInterrupt

    app.drone_adapter = type(
        "DroneAdapter",
        (),
        {"dispatcher": FakeDispatcher()},
    )()

    monkeypatch.setattr(App, "_App__update_state", lambda self: None)
    monkeypatch.setattr(App, "_update_controllers", lambda self: None)
    monkeypatch.setattr(App, "_notification_center", lambda self: None)
    monkeypatch.setattr(
        App,
        "_resolve_rc",
        lambda self: [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700],
    )
    app.run()

    assert app.ctx.sent_rc == [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700]
    assert app.rc_recorder.records == [
        (RobotState.IDLE, [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700])
    ]
    assert dispatched == [[1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700]]
    assert service.stopped
    assert app.rc_recorder.stopped


def test_app_run_replaces_invalid_rc_channel_before_dispatch(monkeypatch):
    service = FakeMavlinkService(context=Context())
    app = App.__new__(App)
    app.ctx = Context()
    app.config = VehicleConfig()
    app.robot_sm = type("RobotSm", (), {"resolve": lambda self: None})()
    app.mavlink_service = service
    app.rc_recorder = FakeRcRecorder()
    dispatched = []

    class FakeDispatcher:
        def set_rc(self, channels):
            dispatched.append(list(channels))
            raise KeyboardInterrupt

    app.drone_adapter = type(
        "DroneAdapter",
        (),
        {"dispatcher": FakeDispatcher()},
    )()

    monkeypatch.setattr(App, "_App__update_state", lambda self: None)
    monkeypatch.setattr(App, "_update_controllers", lambda self: None)
    monkeypatch.setattr(App, "_notification_center", lambda self: None)
    monkeypatch.setattr(
        App,
        "_resolve_rc",
        lambda self: [1500, 1500, 1000, 1500, 2000, 2000, 0, 1000],
    )
    app.run()

    assert app.ctx.sent_rc == [1500, 1500, 1000, 1500, 2000, 2000, 1000, 1000]
    assert dispatched == [[1500, 1500, 1000, 1500, 2000, 2000, 1000, 1000]]
    assert service.stopped
    assert app.rc_recorder.stopped

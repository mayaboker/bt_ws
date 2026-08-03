import threading

import pytest

import bt_app.app as app_module
import bt_app.control.rc_channel_override as override_module
from bt_app.app import App
from bt_app.common import RobotState
from bt_app.context import Context, DEFAULT_RC_CHANNELS
from bt_app.control.rc_channel_override import (
    MavlinkListenerError,
    MavlinkListenerService,
    MavlinkListenerShutdownError,
)
from bt_app.errors import AppStartupError
from bt_app.sm import Robot_StateMachine
from bt_app.vehicle_config import VehicleConfig
from bt_joy.server.mavlink import (
    CommunicationTimeoutStage,
    MavlinkServerConfig,
    NoCommunicationEvent,
    RcChannelsOverrideEvent,
)


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


def make_service(**kwargs):
    return MavlinkListenerService(
        config=MavlinkServerConfig(receive_timeout_s=0.01),
        on_rc=kwargs.get("on_rc", lambda _event: None),
        on_timeout=kwargs.get("on_timeout", lambda _event: None),
        on_resume=kwargs.get("on_resume", lambda _event: None),
        on_failure=kwargs.get("on_failure"),
    )


def test_start_reports_connection_failure(monkeypatch):
    class FailingListener:
        def __init__(self, **_kwargs):
            self.closed = False

        def open(self):
            raise OSError("address already in use")

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", FailingListener
    )
    service = make_service()

    with pytest.raises(MavlinkListenerError, match="address already in use"):
        service.start(timeout=0.2)

    assert service.failure is not None
    assert isinstance(service.failure.cause, OSError)
    assert service.listener.closed


def test_start_timeout_closes_listener_and_stops_thread(monkeypatch):
    open_started = threading.Event()
    release_open = threading.Event()

    class BlockingOpenListener:
        def __init__(self, **_kwargs):
            self.closed = False

        def open(self):
            open_started.set()
            release_open.wait()

        def process_once(self):
            return None

        def close(self):
            self.closed = True
            release_open.set()

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", BlockingOpenListener
    )
    service = make_service()

    with pytest.raises(MavlinkListenerError, match="did not start"):
        service.start(timeout=0.02)

    assert open_started.is_set()
    assert not service.thread.is_alive()
    assert service.listener.closed


def test_runtime_failure_is_dispatched_once_on_calling_thread(monkeypatch):
    release_failure = threading.Event()
    failed = threading.Event()
    callbacks = []

    class FailingListener:
        def __init__(self, **_kwargs):
            self.closed = False

        def open(self):
            return None

        def process_once(self):
            release_failure.wait()
            failed.set()
            raise ConnectionError("receive failed")

        def close(self):
            self.closed = True

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", FailingListener
    )
    service = make_service(
        on_failure=lambda error: callbacks.append(
            (threading.get_ident(), error)
        )
    )
    caller_thread = threading.get_ident()

    service.start(timeout=0.2)
    release_failure.set()
    assert failed.wait(0.2)
    service.thread.join(0.2)
    assert callbacks == []

    service.dispatch_pending()
    service.dispatch_pending()

    assert len(callbacks) == 1
    assert callbacks[0][0] == caller_thread
    assert callbacks[0][1] is service.failure
    assert isinstance(callbacks[0][1].cause, ConnectionError)
    assert service.listener.closed


def test_pending_events_are_coalesced_and_ordered(monkeypatch):
    release_receive = threading.Event()
    received = []

    class WaitingListener:
        def __init__(
            self,
            *,
            on_rc_channels_override,
            on_no_communication,
            on_communication_resumed,
            **_kwargs,
        ):
            self.on_rc = on_rc_channels_override
            self.on_timeout = on_no_communication
            self.on_resume = on_communication_resumed

        def open(self):
            return None

        def process_once(self):
            release_receive.wait(0.01)

        def close(self):
            release_receive.set()

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", WaitingListener
    )
    service = make_service(
        on_rc=lambda event: received.append(("rc", event.channels[0])),
        on_timeout=lambda event: received.append(("timeout", event.stage)),
    )
    first_rc = RcChannelsOverrideEvent(
        channels=(1100,) * 8,
        target_system=1,
        target_component=1,
        source_system=2,
        source_component=2,
        received_at=1.0,
    )
    latest_rc = RcChannelsOverrideEvent(
        channels=(1700,) * 8,
        target_system=1,
        target_component=1,
        source_system=2,
        source_component=2,
        received_at=2.0,
    )
    timeout = NoCommunicationEvent(
        last_seen_at=1.0,
        timeout_s=1.0,
        detected_at=2.0,
        stage=CommunicationTimeoutStage.STAGE1,
    )

    service.start(timeout=0.2)
    service.listener.on_rc(first_rc)
    service.listener.on_timeout(timeout)
    service.listener.on_rc(latest_rc)
    service.dispatch_pending()
    service.stop(timeout=0.2)

    assert received == [
        ("timeout", CommunicationTimeoutStage.STAGE1),
        ("rc", 1700),
    ]


def test_callback_exception_is_raised_by_dispatch_pending(monkeypatch):
    release_receive = threading.Event()

    class WaitingListener:
        def __init__(self, *, on_rc_channels_override, **_kwargs):
            self.on_rc = on_rc_channels_override

        def open(self):
            return None

        def process_once(self):
            release_receive.wait(0.01)

        def close(self):
            release_receive.set()

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", WaitingListener
    )
    service = make_service(
        on_rc=lambda _event: (_ for _ in ()).throw(
            ValueError("invalid RC callback")
        )
    )
    event = RcChannelsOverrideEvent(
        channels=(1500,) * 8,
        target_system=1,
        target_component=1,
        source_system=2,
        source_component=2,
        received_at=1.0,
    )
    service.start(timeout=0.2)
    service.listener.on_rc(event)

    with pytest.raises(ValueError, match="invalid RC callback"):
        service.dispatch_pending()

    service.stop(timeout=0.2)


def test_stop_closes_listener_to_unblock_receive(monkeypatch):
    receiving = threading.Event()
    release_receive = threading.Event()

    class BlockingListener:
        def __init__(self, **_kwargs):
            self.closed = False

        def open(self):
            return None

        def process_once(self):
            receiving.set()
            release_receive.wait()

        def close(self):
            self.closed = True
            release_receive.set()

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", BlockingListener
    )
    service = make_service()
    service.start(timeout=0.2)
    assert receiving.wait(0.2)

    service.stop(timeout=0.02)

    assert not service.thread.is_alive()
    assert service.listener.closed


def test_stop_is_idempotent_and_explicit_restart_recreates_listener(monkeypatch):
    instances = []

    class WaitingListener:
        def __init__(self, **_kwargs):
            self.release = threading.Event()
            instances.append(self)

        def open(self):
            return None

        def process_once(self):
            self.release.wait(0.01)

        def close(self):
            self.release.set()

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", WaitingListener
    )
    service = make_service()

    service.stop()
    service.start(timeout=0.2)
    first_thread = service.thread
    service.stop(timeout=0.2)
    service.stop(timeout=0.2)
    service.start(timeout=0.2)
    second_thread = service.thread
    service.stop(timeout=0.2)

    assert len(instances) == 2
    assert second_thread is not first_thread


def test_stop_reports_permanently_blocked_listener(monkeypatch):
    receiving = threading.Event()
    release_receive = threading.Event()

    class StuckListener:
        def __init__(self, **_kwargs):
            pass

        def open(self):
            return None

        def process_once(self):
            receiving.set()
            release_receive.wait()

        def close(self):
            return None

    monkeypatch.setattr(override_module, "MavlinkServerListener", StuckListener)
    service = make_service()
    service.start(timeout=0.2)
    assert receiving.wait(0.2)

    with pytest.raises(MavlinkListenerShutdownError):
        service.stop(timeout=0.01)

    assert service.thread.daemon
    release_receive.set()
    service.thread.join(0.2)


def test_stop_reports_listener_close_failure(monkeypatch):
    class CloseFailingListener:
        def __init__(self, **_kwargs):
            self.processed = threading.Event()

        def open(self):
            return None

        def process_once(self):
            self.processed.wait(0.01)

        def close(self):
            raise OSError("close failed")

    monkeypatch.setattr(
        override_module, "MavlinkServerListener", CloseFailingListener
    )
    service = make_service()
    service.start(timeout=0.2)

    with pytest.raises(MavlinkListenerShutdownError, match="close failed"):
        service.stop(timeout=0.2)


def test_joystick_timeout_clears_stale_requests_and_enters_failsafe():
    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.armed = True
    app.ctx.armed_allowed = True
    app.ctx.joy_arm_requested = True
    app.ctx.joy_takeoff_request = True
    app.ctx.joy_manual_request = True
    app.ctx.arm_switch = True
    app._last_rc_channel = [1900] * 8
    app.robot_sm = Robot_StateMachine(app.ctx, VehicleConfig())
    app.robot_sm.machine.set_state(RobotState.MANUAL)
    app.ctx.state = RobotState.MANUAL
    event = NoCommunicationEvent(
        last_seen_at=10.0,
        timeout_s=1.0,
        detected_at=11.0,
        stage=CommunicationTimeoutStage.STAGE1,
    )

    app._joystick_fs_enter(event)
    app.robot_sm.resolve()

    assert app.ctx.state == RobotState.FAILSAFE
    assert app.ctx.joy_fail_safe is True
    assert app.ctx.armed_allowed is False
    assert app.ctx.joy_arm_requested is False
    assert app.ctx.joy_takeoff_request is False
    assert app.ctx.joy_manual_request is False
    assert app.ctx.arm_switch is False
    assert app.ctx.request_rc == DEFAULT_RC_CHANNELS
    assert app._last_rc_channel == DEFAULT_RC_CHANNELS


def test_runtime_listener_failure_uses_same_joystick_failsafe_path():
    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.joy_arm_requested = True
    app.ctx.armed_allowed = True
    app._last_rc_channel = [1900] * 8

    app._joystick_listener_failed(
        MavlinkListenerError("receive failed", ConnectionError())
    )

    assert app.ctx.joy_fail_safe is True
    assert app.ctx.joy_arm_requested is False
    assert app.ctx.armed_allowed is False
    assert app.ctx.request_rc == DEFAULT_RC_CHANNELS


def test_controller_loading_converts_listener_start_failure(monkeypatch):
    class FailingService:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise MavlinkListenerError("bind failed")

        def stop(self):
            return None

    monkeypatch.setattr(app_module, "MavlinkListenerService", FailingService)
    app = App.__new__(App)
    app.config = VehicleConfig()
    app.controllers = {}

    with pytest.raises(AppStartupError, match="bind failed"):
        app._App__load_controllers()

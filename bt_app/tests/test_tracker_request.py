from types import SimpleNamespace

import msgpack

from bt_app.app import App
from bt_app.common import AutoModeType, InternalJoy, RobotState
from bt_app.control.tracker_request import TrackerRequestPublisher
from bt_app.control.visual_controller import VisualDetectionMessage, VisualObservation
from bt_app.context import Context
from bt_app.msgs import RCChannels
from bt_app.sm import Robot_StateMachine
from bt_app.vehicle_config import VehicleConfig
from bt_app.trackers import TrackerManager


class FakeSocket:
    def __init__(self):
        self.messages = []
        self.endpoint = None

    def setsockopt(self, *_args):
        return None

    def connect(self, endpoint):
        self.endpoint = endpoint

    def send(self, payload, flags=0):
        self.messages.append(msgpack.unpackb(payload, raw=False))

    def close(self, linger=0):
        return None


class FakeZmqContext:
    def __init__(self):
        self.socket_instance = FakeSocket()

    def socket(self, _kind):
        return self.socket_instance


def test_tracker_request_publisher_preserves_command_order() -> None:
    context = FakeZmqContext()
    publisher = TrackerRequestPublisher("inproc://requests", context=context)
    publisher.start()
    publisher.start_tracking(320, 240)
    publisher.adjust(-5, 3)
    publisher.resize(40, 40)
    publisher.stop()

    assert context.socket_instance.messages == [
        {"type": "start", "x": 320, "y": 240},
        {"type": "adjustment", "delta_x": -5, "delta_y": 3},
        {"type": "resize", "width": 40, "height": 40},
        {"type": "stop"},
    ]


class FakePublisher:
    def __init__(self):
        self.commands = []

    def start_tracking(self, x, y):
        self.commands.append(("start", x, y))

    def adjust(self, delta_x, delta_y):
        self.commands.append(("adjustment", delta_x, delta_y))

    def stop_tracking(self):
        self.commands.append(("stop",))


class HealthyObserver:
    def __init__(self):
        self.observation = VisualObservation(
            VisualDetectionMessage(
                1, 1, True, 10, 20, 30, 30, locked=True, lock_found_frames=10
            ),
            0.1,
            -0.1,
            RCChannels(1500, 1458, 1500, 1550, 1900, 1900, 1000, 1000),
        )

    def is_healthy(self, _timeout, *, now):
        return True

    def fresh_observation(self, **_kwargs):
        return self.observation


def make_pretracking_app() -> App:
    app = object.__new__(App)
    app.ctx = SimpleNamespace(
        state=RobotState.IDLE,
        auto_mode_type=AutoModeType.DISABLED,
        auto_mode_enable=False,
    )
    app.config = SimpleNamespace(
        tracker_initial_x=320,
        tracker_initial_y=240,
        tracker_adjust_step_x_px=5,
        tracker_adjust_step_y_px=3,
        tracker_adjust_rate_hz=5.0,
        tracker_adjust_deadband_pwm=100,
        tracker_bridge_health_timeout_s=1.0,
        tracker_result_timeout_s=0.25,
    )
    app.gst_bridge = HealthyObserver()
    app._tracker_manager = TrackerManager()
    app._tracker_manager.update_tracker(
        "default", app.gst_bridge.observation.detection, received_at_s=19.5
    )
    app._reset_glide_observation_pipeline = lambda _reason: app._tracker_manager.clear()
    app.tracker_request_publisher = FakePublisher()
    app._tracker_session_active = False
    app._tracker_start_pending = False
    app._tracker_requires_disabled = False
    app._tracker_next_adjust_at = 0.0
    app._tracker_enabled_at = float("inf")
    app._tracker_last_lateral_command = None
    app._last_rc_channel = [1500] * (int(InternalJoy.TRACKER_MODE) + 1)
    app.mavlink_service = SimpleNamespace(send_text_to_gcs=lambda *_args: None)
    return app


def test_cursor_session_starts_adjusts_at_rate_and_stops() -> None:
    app = make_pretracking_app()
    assert app._tracker_manager.get_result() is not None
    app.ctx.auto_mode_type = AutoModeType.CURSOR
    app._handle_tracker_mode(AutoModeType.DISABLED, AutoModeType.CURSOR, 10.0)
    assert app._tracker_manager.get_result() is None
    app._last_rc_channel[InternalJoy.ROLL] = 1300
    app._last_rc_channel[InternalJoy.PITCH] = 1700

    app._send_tracker_adjustment(10.0)
    app._send_tracker_adjustment(10.1)
    app._send_tracker_adjustment(10.2)
    app._handle_tracker_mode(AutoModeType.CURSOR, AutoModeType.DISABLED, 10.3)

    assert app.tracker_request_publisher.commands == [
        ("start", 320, 240),
        ("adjustment", -5, 3),
        ("adjustment", -5, 3),
        ("stop",),
    ]


def test_duplicate_transport_delivery_does_not_extend_receipt_time() -> None:
    app = make_pretracking_app()
    original = app._tracker_manager.get_result()

    app._gst_tracker_result_handler(original.detection)

    assert app._tracker_manager.get_result() is original


def test_bridge_health_uses_local_snapshot_age() -> None:
    app = make_pretracking_app()

    assert app._tracker_bridge_healthy(20.0)
    assert not app._tracker_bridge_healthy(20.6)


def test_enabler_rejects_legacy_tracking_mode() -> None:
    app = make_pretracking_app()
    app._tracker_session_active = True
    app.ctx.auto_mode_type = AutoModeType.TRACKING
    app.ctx.state = RobotState.ALT_HOLD

    app._handle_tracker_enabler(20.0)
    assert not app.ctx.auto_mode_enable
    assert app._tracker_enabled_at == float("inf")


def test_tracking_state_requires_selector_and_enabler() -> None:
    ctx = Context()
    ctx.state = RobotState.ALT_HOLD
    ctx.armed = True
    ctx.joy_fail_safe = False
    ctx.joy_manual_request = False
    ctx.auto_mode_type = AutoModeType.CURSOR
    ctx.auto_mode_enable = False
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.ALT_HOLD)

    machine.resolve()
    assert ctx.state == RobotState.ALT_HOLD

    ctx.auto_mode_type = AutoModeType.TRACKING
    ctx.auto_mode_enable = True
    machine.resolve()
    assert ctx.state == RobotState.TRACKING

    ctx.auto_mode_enable = False
    machine.resolve()
    assert ctx.state == RobotState.ALT_HOLD


class ObservationSource:
    def __init__(self, observation):
        self.observation = observation

    def fresh_observation(self, **_kwargs):
        return self.observation


class FallbackHoverController:
    setpoint = 2.0

    def __init__(self):
        self.yaw = None
        self.pitch_roll = None

    def update_yaw_from_joystick(self, value):
        self.yaw = value

    def update_yaw_from_direct_rc(self, value):
        self.yaw = value

    def update_pitch_roll(self, pitch, roll):
        self.pitch_roll = (pitch, roll)

    def update(self, *_args):
        return [1500, 1500, 1500, 1500, 2000, 2000, 1000, 1000]


def test_auto_mode_forced_entry_uses_neutral_alt_hold_fallback() -> None:
    app = object.__new__(App)
    app.ctx = SimpleNamespace(
        auto_mode_enable=True,
        drone_alt=2.0,
        drone_alt_received_at_s=1.0,
    )
    app.config = SimpleNamespace(tracker_result_timeout_s=0.25)
    app._tracker_enabled_at = 1.0
    app._tracker_last_lateral_command = None
    command = RCChannels(1510, 1520, 1530, 1540, 1900, 1900, 1000, 1000)
    observation = VisualObservation(
        VisualDetectionMessage(1, 1, True, 10, 20, 30, 30, locked=True),
        0.1,
        -0.1,
        command,
    )
    hover = FallbackHoverController()
    app.controllers = {RobotState.ALT_HOLD: hover}
    app.gst_bridge = ObservationSource(observation)

    expected_hover_command = [1500, 1500, 1500, 1500, 2000, 2000, 1000, 1000]
    assert app.auto_mode_handler() == expected_hover_command
    assert not app.ctx.auto_mode_enable
    assert hover.yaw == 1500
    assert hover.pitch_roll == (1500, 1500)


def test_forced_glide_handler_uses_neutral_alt_hold_fallback() -> None:
    app = object.__new__(App)
    app.ctx = SimpleNamespace(
        drone_alt=2.0,
        drone_alt_received_at_s=1.0,
    )
    hover = FallbackHoverController()
    app.controllers = {RobotState.ALT_HOLD: hover}

    channels = app.glide_handler()

    assert channels == [1500, 1500, 1500, 1500, 2000, 2000, 1000, 1000]
    assert hover.yaw == 1500
    assert hover.pitch_roll == (1500, 1500)

import pytest

from bt_app.app import App
from bt_app.common import AETR1234, MavSeverity, RobotState
from bt_app.context import Context
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey
from bt_app.sm import Robot_StateMachine
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


class FakeController:
    def __init__(self, channels):
        self.channels = list(channels)
        self.calls = []
        self.time_in_alt = 0
        self.setpoint = 42
        self.baseline = None
        self.reset_setpoint_altitude = None
        self.reset_altitude = None

    def update(self, *args):
        self.calls.append(args)
        return list(self.channels)

    def update_setpoint_from_throttle(self, throttle_rc):
        self.calls.append(("throttle", throttle_rc))

    def update_yaw_from_joystick(self, yaw_rc):
        self.calls.append(("yaw", yaw_rc))

    def consume_altitude_setpoint_request_event(self):
        return False

    def consume_descent_started_event(self):
        return False

    def consume_landed_event(self):
        return False

    def reset_setpoint(self, altitude):
        self.reset_setpoint_altitude = altitude

    def reset(self, altitude=None):
        self.reset_altitude = altitude

    def set_baseline(self, baseline):
        self.baseline = baseline


class FakeParams:
    def __init__(self, baseline=1375):
        self.baseline = baseline

    def get(self, key):
        if key == ParameterKey.HOV_BASELINE:
            return self.baseline
        return 42


class FakeMavlinkService:
    def __init__(self):
        self.messages = []

    def send_text_to_gcs(self, text, severity):
        self.messages.append((text, severity))

    def send_named_value_to_gcs(self, name, value):
        self.messages.append((name, value))


class FakeLandDetector:
    def reset(self):
        pass


def make_app_with_context():
    app = App.__new__(App)
    app.ctx = Context()
    app.controllers = {}
    app._App__params = FakeParams()
    app.mavlink_service = FakeMavlinkService()
    app.manual_land_detector = FakeLandDetector()
    app._manual_land_detection_started_notified = False
    app._manual_land_confirmed_notified = False
    return app


def test_robot_state_uses_stable_integer_values():
    assert RobotState.IDLE.value == 0
    assert RobotState.MANUAL.value == 1
    assert RobotState.TRACKING.value == 2
    assert RobotState.RECOVERY.value == 3
    assert RobotState.FAILSAFE.value == 4
    assert RobotState.TAKEOFF.value == 5
    assert RobotState.ARM.value == 6
    assert RobotState.ALT_HOLD.value == 7


def test_context_state_defaults_to_robot_state_member():
    assert Context().state == RobotState.IDLE
    assert isinstance(Context().state, RobotState)


def test_state_machine_transition_assigns_robot_state_member():
    ctx = Context()
    config = VehicleConfig()
    machine = Robot_StateMachine(ctx, config)

    ctx.armable = True
    ctx.joy_arm_requested = True
    ctx.joy_manual_request = True
    machine.resolve()
    ctx.armed = True
    machine.resolve()

    assert ctx.state == RobotState.MANUAL
    assert isinstance(ctx.state, RobotState)


@pytest.mark.parametrize(
    ("state", "controller_key"),
    [
        (RobotState.MANUAL, RobotState.MANUAL),
        (RobotState.ARM, RobotState.ARM),
        (RobotState.ALT_HOLD, RobotState.ALT_HOLD),
        (RobotState.FAILSAFE, RobotState.FAILSAFE),
        (RobotState.TAKEOFF, RobotState.TAKEOFF),
    ],
)
def test_rc_selector_uses_robot_state_members(state, controller_key):
    app = make_app_with_context()
    channels = [1100] * 8
    controller = FakeController(channels)
    app.controllers[controller_key] = controller
    app.ctx.state = state
    app.ctx.drone_alt = 12.5
    app.ctx.drone_vertical_speed = -0.1
    app.ctx.request_rc = [1500] * 8

    assert app._resolve_rc() == channels

    if state == RobotState.TAKEOFF:
        assert controller.calls == [(42, 12.5)]
    elif state == RobotState.FAILSAFE:
        assert controller.calls == [(12.5, -0.1)]
    elif state == RobotState.ALT_HOLD:
        assert controller.calls == [("throttle", 1500), ("yaw", 1500), (42, 12.5)]
    else:
        assert controller.calls == [()]


def test_rc_selector_idle_returns_neutral_channels():
    app = make_app_with_context()
    app.ctx.state = RobotState.IDLE

    channels = app._resolve_rc()

    assert channels[RCChannel.ROLL] == RC_MID
    assert channels[RCChannel.PITCH] == RC_MID
    assert channels[RCChannel.THROTTLE] == RC_MIN
    assert channels[RCChannel.YAW] == RC_MID
    assert channels[RCChannel.ARM] == RC_MIN
    assert channels[RCChannel.ANGLE] == RC_MAX


def test_alt_hold_entry_uses_hover_baseline_parameter():
    app = make_app_with_context()
    controller = FakeController([1500] * 8)
    app.controllers[RobotState.ALT_HOLD] = controller
    app.ctx.drone_alt = 3.25
    app._App__params = FakeParams(baseline=1325)

    app._handle_before_state_changed(RobotState.MANUAL, RobotState.ALT_HOLD)

    assert controller.reset_setpoint_altitude == 3.25
    assert controller.baseline == 1325


def test_failsafe_entry_uses_hover_baseline_parameter():
    app = make_app_with_context()
    controller = FakeController([1500] * 8)
    app.controllers[RobotState.FAILSAFE] = controller
    app.ctx.drone_alt = 4.5
    app._App__params = FakeParams(baseline=1400)

    app._handle_before_state_changed(RobotState.MANUAL, RobotState.FAILSAFE)

    assert controller.reset_altitude == 4.5
    assert controller.baseline == 1400


def test_manual_to_idle_waits_for_land_confirmation():
    ctx = Context()
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.MANUAL)
    ctx.state = RobotState.MANUAL
    ctx.armed = True
    ctx.joy_manual_request = False
    ctx.request_rc = [1500] * 8
    ctx.request_rc[AETR1234.THROTTLE] = 1000
    ctx.request_rc[AETR1234.YAW] = 1500

    machine.resolve()
    assert ctx.state == RobotState.MANUAL

    ctx.manual_land_confirmed = True
    machine.resolve()
    assert ctx.state == RobotState.IDLE


def test_manual_land_detector_sends_messages_once():
    class FakeLandDetector:
        def __init__(self):
            self.reset_calls = 0
            self.update_calls = []
            self.results = [False, True, True]

        def reset(self):
            self.reset_calls += 1

        def update(self, altitude, vertical_speed):
            self.update_calls.append((altitude, vertical_speed))
            return self.results.pop(0)

    app = make_app_with_context()
    app.manual_land_detector = FakeLandDetector()
    app._manual_land_detection_started_notified = False
    app._manual_land_confirmed_notified = False
    app.ctx.state = RobotState.MANUAL
    app.ctx.joy_manual_request = False
    app.ctx.drone_alt = 0.1
    app.ctx.drone_vertical_speed = 0.0
    app.ctx.request_rc = [1500] * 8
    app.ctx.request_rc[AETR1234.THROTTLE] = 1000

    app._update_manual_land_detector()
    app._update_manual_land_detector()
    app._update_manual_land_detector()

    assert app.ctx.manual_land_confirmed
    assert app.mavlink_service.messages == [
        ("Manual land detection started", MavSeverity.INFO),
        ("Manual land confirmed, disarming", MavSeverity.INFO),
    ]


def test_manual_land_detector_resets_when_request_stops():
    class FakeLandDetector:
        def __init__(self):
            self.reset_calls = 0

        def reset(self):
            self.reset_calls += 1

    app = make_app_with_context()
    app.manual_land_detector = FakeLandDetector()
    app._manual_land_detection_started_notified = True
    app._manual_land_confirmed_notified = True
    app.ctx.state = RobotState.MANUAL
    app.ctx.joy_manual_request = True
    app.ctx.manual_land_confirmed = True
    app.ctx.request_rc = [1500] * 8

    app._update_manual_land_detector()

    assert not app.ctx.manual_land_confirmed
    assert app.manual_land_detector.reset_calls == 1

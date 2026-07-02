import pytest

from bt_app.app import App
from bt_app.common import AETR1234, RobotState
from bt_app.context import Context
from bt_app.rc_utils import matching
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

    def update(self, *args):
        self.calls.append(args)
        return list(self.channels)


class FakeParams:
    def get(self, _key):
        return 42


def make_app_with_context():
    app = App.__new__(App)
    app.ctx = Context()
    app.controllers = {}
    app._App__params = FakeParams()
    return app


def test_robot_state_uses_stable_integer_values():
    assert RobotState.IDLE.value == 0
    assert RobotState.MANUAL.value == 1
    assert RobotState.TRACKING.value == 2
    assert RobotState.RECOVERY.value == 3
    assert RobotState.FAILSAFE.value == 4
    assert RobotState.TAKEOFF.value == 5
    assert RobotState.ARM.value == 6
    assert RobotState.SEARCH.value == 7


def test_context_state_defaults_to_robot_state_member():
    assert Context().state == RobotState.IDLE
    assert isinstance(Context().state, RobotState)


def test_state_machine_transition_assigns_robot_state_member():
    ctx = Context()
    config = VehicleConfig()
    machine = Robot_StateMachine(ctx, config)

    ctx.force_manual_mode = True
    machine.resolve()

    assert ctx.state == RobotState.MANUAL
    assert isinstance(ctx.state, RobotState)


@pytest.mark.parametrize(
    ("state", "controller_key"),
    [
        (RobotState.MANUAL, RobotState.MANUAL),
        (RobotState.ARM, RobotState.ARM),
        (RobotState.SEARCH, RobotState.SEARCH),
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

    assert app._App__resolve_rc() == channels

    if state in (RobotState.FAILSAFE, RobotState.TAKEOFF):
        assert controller.calls == [(42, 12.5)]
    else:
        assert controller.calls == [()]


def test_rc_selector_idle_returns_neutral_channels():
    app = make_app_with_context()
    app.ctx.state = RobotState.IDLE

    assert app._App__resolve_rc() == [1000] * 8


def test_matching_compares_context_state_to_robot_state_member():
    ctx = Context()
    config = VehicleConfig()
    config.has_external_pilot = True
    ctx.state = RobotState.MANUAL
    ctx.drone_rc = [1000] * 8
    ctx.drone_rc[AETR1234.THROTTLE] = 1500
    ctx.drone_rc[AETR1234.AUX3] = 1700

    rc_channels = [1000] * 8
    matched = matching(ctx, rc_channels, config)

    assert matched[AETR1234.THROTTLE] == 1500
    assert matched[AETR1234.AUX3] == 1700

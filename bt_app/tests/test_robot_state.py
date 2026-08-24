import pytest
from types import SimpleNamespace

from bt_app.app import App
import bt_app.app as app_module
from bt_app.common import AETR1234, InternalJoystick, RobotState, TrackerMode
from bt_app.common.mavlink import NamedValue
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
        self.reset_setpoint_kwargs = None
        self.reset_altitude = None
        self.is_arm_done = False

    def update(self, *args):
        self.calls.append(args)
        return list(self.channels)

    def update_setpoint_from_throttle(self, throttle_rc):
        self.calls.append(("throttle", throttle_rc))

    def update_yaw_from_joystick(self, yaw_rc):
        self.calls.append(("yaw", yaw_rc))

    def update_pitch_roll(self, pitch_rc, roll_rc):
        self.calls.append(("pitch_roll", pitch_rc, roll_rc))

    def consume_altitude_setpoint_request_event(self):
        return False

    def consume_descent_started_event(self):
        return False

    def consume_landed_event(self):
        return False

    def reset_setpoint(self, altitude, **kwargs):
        self.reset_setpoint_altitude = altitude
        self.reset_setpoint_kwargs = kwargs

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


class FakeManualLandService:
    def __init__(self):
        self.reset_calls = 0
        self.update_calls = 0

    def reset(self):
        self.reset_calls += 1

    def update(self):
        self.update_calls += 1


class FakeTrackerController:
    def __init__(self, channels=None):
        self.channels = tuple(channels or [1500] * 8)
        self.ready_to_track = False
        self.exit_requested = False
        self.started = 0
        self.start_calls = []
        self.stopped = 0
        self.end_reasons = []
        self.completion_latched = False
        self.observations = []
        self.update_calls = []
        self.vertical_speed_fresh = True

    def observe(self, estimate, *, now_s, mode_selected, **_telemetry):
        self.observations.append((estimate, now_s, mode_selected))
        if not mode_selected:
            self.ready_to_track = False

    def vertical_speed_is_fresh(self, **kwargs):
        return self.vertical_speed_fresh

    def start_tracking(self, **kwargs):
        self.started += 1
        self.start_calls.append(kwargs)

    def stop_tracking(self, *, end_reason="unknown"):
        self.stopped += 1
        self.end_reasons.append(end_reason)

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return SimpleNamespace(channels=self.channels)


def make_app_with_context():
    app = App.__new__(App)
    app.ctx = Context()
    app.controllers = {}
    app._tracker_now_s = 0.0
    app._tracker_result = None
    app._tracker_enable_was_low = False
    app._selected_tracker_mode = TrackerMode.DISABLED
    app.services = SimpleNamespace(
        parameters=FakeParams(),
        mavlink=FakeMavlinkService(),
        manual_land=FakeManualLandService(),
        tracker_results=SimpleNamespace(latest_observation=None),
    )
    return app


def test_robot_state_uses_stable_integer_values():
    assert RobotState.IDLE.value == 0
    assert RobotState.MANUAL.value == 1
    assert "TRACKING" not in RobotState.__members__
    assert RobotState.RECOVERY.value == 3
    assert RobotState.FAILSAFE.value == 4
    assert RobotState.TAKEOFF.value == 5
    assert RobotState.ARM.value == 6
    assert RobotState.ALT_HOLD.value == 7
    assert RobotState.TRACK.value == 8


def test_context_state_defaults_to_robot_state_member():
    assert Context().state == RobotState.IDLE
    assert isinstance(Context().state, RobotState)


def test_state_machine_transition_assigns_robot_state_member():
    ctx = Context()
    config = VehicleConfig()
    machine = Robot_StateMachine(ctx, config)

    ctx.armable = True
    ctx.request_rc = InternalJoystick(arm=RC_MAX)
    machine.resolve()
    ctx.armed = True
    machine.resolve()

    assert ctx.state == RobotState.MANUAL
    assert isinstance(ctx.state, RobotState)


def test_manual_to_takeoff_uses_initialized_altitude_setpoint():
    ctx = Context()
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.MANUAL)
    ctx.state = RobotState.MANUAL
    ctx.armed = True
    ctx.request_rc = InternalJoystick(manual=RC_MID, auto_takeoff=RC_MAX)
    ctx.drone_alt = 0.0
    ctx.alt_setpoint = 2.0

    machine.resolve()

    assert ctx.state == RobotState.TAKEOFF


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
    app.ctx.request_rc = InternalJoystick(
        roll=1500,
        pitch=1500,
        throttle=1500,
        yaw=1500,
        arm=1500,
        manual=1500,
        auto_takeoff=1500,
        tracker_mode=1500,
    )

    result = app._resolve_rc()

    if state == RobotState.MANUAL:
        expected = list(app.ctx.request_rc)
        expected[AETR1234.AUX2] = RC_MAX
        assert result == expected
        assert controller.calls == []
    elif state == RobotState.TAKEOFF:
        assert result == channels
        assert controller.calls == [(42, 12.5, 0.0)]
    elif state == RobotState.FAILSAFE:
        assert result == channels
        assert controller.calls == [(12.5, -0.1)]
    elif state == RobotState.ALT_HOLD:
        assert result == channels
        assert controller.calls == [
            ("throttle", 1500),
            ("yaw", 1500),
            ("pitch_roll", 1500, 1500),
            (42, 12.5, 0.0),
        ]
    else:
        assert result == channels
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
    app.services.parameters = FakeParams(baseline=1325)

    app._handle_before_state_changed(RobotState.MANUAL, RobotState.ALT_HOLD)

    assert controller.reset_setpoint_altitude == 3.25
    assert controller.baseline == 1325
    assert controller.reset_setpoint_kwargs["setpoint"] == 3.25
    assert not controller.reset_setpoint_kwargs["require_throttle_center"]


def test_takeoff_to_alt_hold_preserves_target_and_requires_centered_throttle():
    app = make_app_with_context()
    controller = FakeController([1500] * 8)
    app.controllers[RobotState.ALT_HOLD] = controller
    app.ctx.drone_alt = 9.9
    app.ctx.drone_vertical_speed = 0.12
    app.ctx.drone_alt_received_at_s = 123.0
    app.ctx.sent_rc = [1500] * 8
    app.ctx.sent_rc[AETR1234.THROTTLE] = 1710

    app._handle_before_state_changed(RobotState.TAKEOFF, RobotState.ALT_HOLD)

    assert controller.reset_setpoint_altitude == 9.9
    assert controller.reset_setpoint_kwargs == {
        "setpoint": 42,
        "altitude_sample_time_s": 123.0,
        "vertical_speed_m_s": 0.12,
        "require_throttle_center": True,
    }
    assert app.ctx.alt_setpoint == 42
    assert (NamedValue.ALT_SP, 42) in app.services.mavlink.messages


def test_failsafe_entry_uses_hover_baseline_parameter():
    app = make_app_with_context()
    controller = FakeController([1500] * 8)
    app.controllers[RobotState.FAILSAFE] = controller
    app.ctx.drone_alt = 4.5
    app.services.parameters = FakeParams(baseline=1400)

    app._handle_before_state_changed(RobotState.MANUAL, RobotState.FAILSAFE)

    assert controller.reset_altitude == 4.5
    assert controller.baseline == 1400


def test_manual_to_idle_uses_switches_and_low_throttle():
    ctx = Context()
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.MANUAL)
    ctx.state = RobotState.MANUAL
    ctx.armed = True
    ctx.request_rc = InternalJoystick(arm=RC_MAX)

    machine.resolve()
    assert ctx.state == RobotState.MANUAL

    ctx.request_rc = InternalJoystick()
    machine.resolve()
    assert ctx.state == RobotState.IDLE


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (RobotState.TAKEOFF, RobotState.MANUAL),
        (RobotState.ALT_HOLD, RobotState.MANUAL),
    ],
)
def test_manual_selection_returns_armed_flight_states_to_manual(source, expected):
    ctx = Context()
    ctx.state = source
    ctx.armed = True
    ctx.request_rc = InternalJoystick()
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(source)

    machine.resolve()

    assert ctx.state == expected


def test_failsafe_returns_to_idle_when_disarmed_with_no_mode_selected():
    ctx = Context()
    ctx.state = RobotState.FAILSAFE
    ctx.armed = False
    ctx.joy_fail_safe = False
    ctx.request_rc = InternalJoystick(manual=RC_MID)
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.FAILSAFE)

    machine.resolve()

    assert ctx.state == RobotState.IDLE


def test_notification_center_updates_manual_land_service():
    app = make_app_with_context()

    app._notification_center()

    assert app.services.manual_land.update_calls == 1
    assert app.services.mavlink.messages == []


@pytest.mark.parametrize(
    "tracker_mode",
    [TrackerMode.TRACKER1, TrackerMode.TRACKER2],
)
def test_alt_hold_enters_track_on_ready_sf_edge_request(tracker_mode):
    ctx = Context()
    ctx.state = RobotState.ALT_HOLD
    ctx.armed = True
    ctx.tracker_ready = True
    ctx.tracker_start_requested = True
    ctx.request_rc = InternalJoystick(
        manual=RC_MID,
        tracker_mode=tracker_mode,
    )
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.ALT_HOLD)

    machine.resolve()

    assert ctx.state == RobotState.TRACK


def test_alt_hold_override_priority_is_failsafe_then_manual_then_track():
    ctx = Context()
    ctx.state = RobotState.ALT_HOLD
    ctx.armed = True
    ctx.tracker_ready = True
    ctx.joy_fail_safe = True
    ctx.tracker_start_requested = True
    ctx.request_rc = InternalJoystick(tracker_mode=TrackerMode.TRACKER1)
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.ALT_HOLD)

    machine.resolve()

    assert ctx.state == RobotState.FAILSAFE


@pytest.mark.parametrize(
    ("joystick", "joy_failsafe", "exit_requested", "expected"),
    [
        (InternalJoystick(tracker_mode=TrackerMode.TRACKER1), True, True, RobotState.FAILSAFE),
        (
            InternalJoystick(manual=RC_MIN, tracker_mode=TrackerMode.TRACKER1),
            False,
            True,
            RobotState.MANUAL,
        ),
        (
            InternalJoystick(manual=RC_MID, tracker_mode=TrackerMode.TRACKER1),
            False,
            True,
            RobotState.ALT_HOLD,
        ),
    ],
)
def test_track_transition_priority(joystick, joy_failsafe, exit_requested, expected):
    ctx = Context()
    ctx.state = RobotState.TRACK
    ctx.armed = True
    ctx.request_rc = joystick
    ctx.joy_fail_safe = joy_failsafe
    ctx.tracker_exit_requested = exit_requested
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.TRACK)

    machine.resolve()

    assert ctx.state == expected


def test_tracker_disabled_exits_track_without_controller_exit_request():
    ctx = Context()
    ctx.state = RobotState.TRACK
    ctx.armed = True
    ctx.request_rc = InternalJoystick(manual=RC_MID)
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.TRACK)

    machine.resolve()

    assert ctx.state == RobotState.ALT_HOLD


def test_track_rc_handler_routes_cached_immutable_command():
    app = make_app_with_context()
    tracker = FakeTrackerController([1500, 1417, 1508, 1500, 2000, 2000, 1000, 1000])
    app.controllers[RobotState.TRACK] = tracker
    app.ctx.state = RobotState.TRACK
    app.ctx.drone_vertical_speed = -0.4
    app.ctx.drone_alt_received_at_s = 10.0
    app._tracker_now_s = 10.1

    channels = app._resolve_rc()

    assert channels == list(tracker.channels)
    assert tracker.update_calls == [
        {
            "now_s": 10.1,
            "vertical_speed_m_s": -0.4,
            "vertical_speed_sample_time_s": 10.0,
        }
    ]


def test_track_to_alt_hold_stops_tracker_and_seeds_current_altitude():
    app = make_app_with_context()
    tracker = FakeTrackerController()
    hover = FakeController([1500] * 8)
    app.controllers[RobotState.TRACK] = tracker
    app.controllers[RobotState.ALT_HOLD] = hover
    app.ctx.drone_alt = 6.5
    app.ctx.drone_vertical_speed = -0.2
    app.ctx.drone_alt_received_at_s = 10.0

    app._handle_before_state_changed(RobotState.TRACK, RobotState.ALT_HOLD)

    assert tracker.stopped == 1
    assert tracker.end_reasons == ["tracker_disabled"]
    assert hover.reset_setpoint_kwargs == {
        "setpoint": 6.5,
        "altitude_sample_time_s": 10.0,
        "vertical_speed_m_s": -0.2,
        "require_throttle_center": False,
    }


def test_tracker_end_reason_distinguishes_controller_and_override_exits():
    app = make_app_with_context()
    tracker = FakeTrackerController()
    app.ctx.request_rc = InternalJoystick(tracker_mode=TrackerMode.TRACKER1)

    tracker.exit_requested = True
    assert app._tracker_end_reason(tracker, RobotState.ALT_HOLD) == (
        "target_lost_or_stale"
    )

    tracker.completion_latched = True
    assert app._tracker_end_reason(tracker, RobotState.ALT_HOLD) == "commit_complete"
    assert app._tracker_end_reason(tracker, RobotState.MANUAL) == "manual_override"
    assert app._tracker_end_reason(tracker, RobotState.FAILSAFE) == "failsafe"

    app.ctx.request_rc = InternalJoystick()
    assert app._tracker_end_reason(tracker, RobotState.ALT_HOLD) == "commit_complete"
    tracker.completion_latched = False
    assert app._tracker_end_reason(tracker, RobotState.ALT_HOLD) == "tracker_disabled"


def test_app_prepares_tracker_from_one_latest_estimate_snapshot(monkeypatch):
    app = make_app_with_context()
    tracker = FakeTrackerController()
    tracker.ready_to_track = True
    observation = object()
    app.controllers[RobotState.TRACK] = tracker
    app.services.tracker_results.latest_observation = observation
    app.ctx.state = RobotState.TRACK
    app.ctx.drone_vertical_speed = -0.4
    app.ctx.drone_alt_received_at_s = 12.4
    app.ctx.request_rc = InternalJoystick(
        manual=RC_MID,
        tracker_mode=TrackerMode.TRACKER1,
    )
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 12.5)

    app._update_controllers()

    assert tracker.observations == [(observation, 12.5, True)]
    assert app.ctx.tracker_ready
    assert tracker.update_calls == [
        {
            "now_s": 12.5,
            "vertical_speed_m_s": -0.4,
            "vertical_speed_sample_time_s": 12.4,
        }
    ]


def test_tracker_enable_requires_observed_low_before_startup_high():
    app = make_app_with_context()
    app.ctx.request_rc = InternalJoystick(
        tracker_mode=TrackerMode.TRACKER1,
        tracker_enable=RC_MAX,
    )

    app._prepare_tracker_switches()

    assert not app.ctx.tracker_start_requested


def test_tracker_enable_rising_edge_is_one_loop_pulse():
    app = make_app_with_context()
    app.ctx.request_rc = InternalJoystick(
        tracker_mode=TrackerMode.TRACKER2,
        tracker_enable=RC_MIN,
    )
    app._prepare_tracker_switches()
    app.ctx.request_rc = app.ctx.request_rc._replace(tracker_enable=RC_MAX)

    app._prepare_tracker_switches()
    assert app.ctx.tracker_start_requested
    assert app._selected_tracker_mode == TrackerMode.TRACKER2

    app._prepare_tracker_switches()
    assert not app.ctx.tracker_start_requested


def test_tracker_enable_requires_direct_low_to_high_transition():
    app = make_app_with_context()
    app.ctx.request_rc = InternalJoystick(
        tracker_mode=TrackerMode.TRACKER1,
        tracker_enable=RC_MIN,
    )
    app._prepare_tracker_switches()
    app.ctx.request_rc = app.ctx.request_rc._replace(tracker_enable=RC_MID)
    app._prepare_tracker_switches()
    app.ctx.request_rc = app.ctx.request_rc._replace(tracker_enable=RC_MAX)

    app._prepare_tracker_switches()

    assert not app.ctx.tracker_start_requested


def test_tracker_enable_edge_is_ignored_when_tracker_is_not_ready(monkeypatch):
    app = make_app_with_context()
    tracker = FakeTrackerController()
    app.controllers[RobotState.TRACK] = tracker
    app.ctx.state = RobotState.ALT_HOLD
    app.ctx.armed = True
    app.ctx.request_rc = InternalJoystick(
        manual=RC_MID,
        tracker_mode=TrackerMode.TRACKER1,
        tracker_enable=RC_MIN,
    )
    app._prepare_tracker_switches()
    app.ctx.request_rc = app.ctx.request_rc._replace(tracker_enable=RC_MAX)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 12.5)

    app._update_controllers()

    assert not app.ctx.tracker_start_requested


def test_ready_tracker_accepts_sf_edge_in_armed_alt_hold(monkeypatch):
    app = make_app_with_context()
    tracker = FakeTrackerController()
    tracker.ready_to_track = True
    app.controllers[RobotState.TRACK] = tracker
    app.ctx.state = RobotState.ALT_HOLD
    app.ctx.armed = True
    app.ctx.request_rc = InternalJoystick(
        manual=RC_MID,
        tracker_mode=TrackerMode.TRACKER1,
        tracker_enable=RC_MIN,
    )
    app._prepare_tracker_switches()
    app.ctx.request_rc = app.ctx.request_rc._replace(tracker_enable=RC_MAX)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 12.5)

    app._update_controllers()

    assert app.ctx.tracker_start_requested


def test_ready_tracker_rejects_entry_without_fresh_vertical_speed(monkeypatch):
    app = make_app_with_context()
    tracker = FakeTrackerController()
    tracker.ready_to_track = True
    tracker.vertical_speed_fresh = False
    app.controllers[RobotState.TRACK] = tracker
    app.ctx.state = RobotState.ALT_HOLD
    app.ctx.armed = True
    app.ctx.request_rc = InternalJoystick(
        manual=RC_MID,
        tracker_mode=TrackerMode.TRACKER1,
        tracker_enable=RC_MIN,
    )
    app._prepare_tracker_switches()
    app.ctx.request_rc = app.ctx.request_rc._replace(tracker_enable=RC_MAX)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 12.5)

    app._update_controllers()

    assert not app.ctx.tracker_ready
    assert not app.ctx.tracker_start_requested


def test_track_entry_seeds_controller_with_current_vertical_speed():
    app = make_app_with_context()
    tracker = FakeTrackerController()
    app.controllers[RobotState.TRACK] = tracker
    app.ctx.drone_vertical_speed = -0.4
    app.ctx.drone_alt_received_at_s = 12.4
    app._tracker_now_s = 12.5

    app._handle_before_state_changed(RobotState.ALT_HOLD, RobotState.TRACK)

    assert tracker.start_calls == [
        {
            "now_s": 12.5,
            "vertical_speed_m_s": -0.4,
            "vertical_speed_sample_time_s": 12.4,
        }
    ]


def test_tracker_disabled_cancels_ready_acquisition(monkeypatch):
    app = make_app_with_context()
    tracker = FakeTrackerController()
    tracker.ready_to_track = True
    app.controllers[RobotState.TRACK] = tracker
    app.ctx.request_rc = InternalJoystick(tracker_mode=TrackerMode.DISABLED)
    monkeypatch.setattr(app_module.time, "monotonic", lambda: 12.5)

    app._update_controllers()

    assert tracker.observations == [(None, 12.5, False)]
    assert not app.ctx.tracker_ready
    assert not app.ctx.tracker_start_requested

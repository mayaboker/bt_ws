from types import SimpleNamespace

import pytest
from bt_msgs import TargetSelectorState

from bt_app.app import App
from bt_app.common import InternalJoystick, RobotState, TrackerMode
from bt_app.context import Context
from bt_app.services.target_selector import TargetSelectorPublisher, _normalize_rc


def test_rc_normalization_has_deadband_and_full_scale():
    assert _normalize_rc(1500) == 0.0
    assert _normalize_rc(1535) == 0.0
    assert _normalize_rc(2000) == 1.0
    assert _normalize_rc(1000) == -1.0


def test_selector_integrates_absolute_normalized_position_and_clamps():
    selector = TargetSelectorPublisher()
    selector.update(
        roll_rc=1500, pitch_rc=1500,
        state=TargetSelectorState.SELECTING, now_s=1.0,
    )
    moved = selector.update(
        roll_rc=2000, pitch_rc=2000,
        state=TargetSelectorState.SELECTING, now_s=1.1,
    )
    assert moved.center_x == pytest.approx(0.55625)
    assert moved.center_y == pytest.approx(0.44375)

    selector.center_x = 0.99
    selector.center_y = 0.01
    clamped = selector.update(
        roll_rc=2000, pitch_rc=2000,
        state=TargetSelectorState.SELECTING, now_s=1.2,
    )
    assert clamped.center_x == 1.0
    assert clamped.center_y == 0.0


def test_disabled_selector_resets_to_camera_center():
    selector = TargetSelectorPublisher()
    selector.center_x, selector.center_y = 0.2, 0.8
    message = selector.update(
        roll_rc=1500, pitch_rc=1500,
        state=TargetSelectorState.DISABLED, now_s=1.0,
    )
    assert (message.center_x, message.center_y) == (0.5, 0.5)


def test_tracker_selection_sticks_do_not_reach_hover_pitch_roll():
    class Hover:
        setpoint = 5.0
        def update_setpoint_from_throttle(self, _value): pass
        def update_yaw_from_joystick(self, _value): pass
        def consume_altitude_setpoint_request_event(self): return False
        def update_pitch_roll(self, pitch, roll): self.pitch_roll = (pitch, roll)
        def update(self, *_args): return [1500] * 8

    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.state = RobotState.ALT_HOLD
    app.ctx.alt_setpoint = 5.0
    app.ctx.drone_alt = 5.0
    app.ctx.request_rc = InternalJoystick(
        roll=1900, pitch=1800, tracker_mode=TrackerMode.TRACKER1
    )
    hover = Hover()
    app.controllers = {RobotState.ALT_HOLD: hover}
    app.services = SimpleNamespace()

    app.alt_hold_handler()

    assert hover.pitch_roll == (1500, 1500)


@pytest.mark.parametrize(
    ("robot_state", "tracker_mode", "expected"),
    [
        (RobotState.ALT_HOLD, TrackerMode.TRACKER1, TargetSelectorState.SELECTING),
        (RobotState.TRACK, TrackerMode.TRACKER1, TargetSelectorState.LOCKED),
        (RobotState.ALT_HOLD, TrackerMode.DISABLED, TargetSelectorState.DISABLED),
        (RobotState.MANUAL, TrackerMode.TRACKER1, TargetSelectorState.DISABLED),
    ],
)
def test_app_publishes_selector_lifecycle(robot_state, tracker_mode, expected):
    class Selector:
        def update(self, **values): self.values = values

    selector = Selector()
    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.state = robot_state
    app.ctx.request_rc = InternalJoystick(tracker_mode=tracker_mode)
    app.services = SimpleNamespace(target_selector=selector)

    app._update_target_selector(12.0)

    assert selector.values["state"] == expected
    assert selector.values["now_s"] == 12.0

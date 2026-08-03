from bt_app.app import App
from bt_app.common import AETR1234, MavSeverity, RobotState
from bt_app.context import Context
from bt_app.control import hover_yaw_controller as hover_module
from bt_app.control.hover_yaw_controller import HoverYawController
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey


class FakeEvent:
    def __init__(self):
        self.subscribers = []

    def subscribe(self, callback):
        self.subscribers.append(callback)


class FakeParameters:
    def __init__(self):
        self.on_parameter_changed = FakeEvent()
        self.values = {
            ParameterKey.HOV_KP: 80.0,
            ParameterKey.HOV_KI: 10.0,
            ParameterKey.HOV_KD: 20.0,
            ParameterKey.HOV_OUT_LIMIT: 400.0,
            ParameterKey.HOV_BASELINE: 1300,
            ParameterKey.HOV_ALT_RATE: 1.0,
            ParameterKey.HOV_THR_DB: 200,
            ParameterKey.HOV_MIN_ALT: 2.0,
            ParameterKey.HY_MAX_RATE: 120.0,
            ParameterKey.HY_DEADBAND: 30,
            ParameterKey.HY_EXPO: 0.35,
            ParameterKey.BF_YAW_RATE: 67.0,
        }

    def get(self, name):
        return self.values[name]


def controller_with_times(monkeypatch, times):
    remaining = iter(times)
    last = {"value": times[-1]}

    def monotonic():
        try:
            last["value"] = next(remaining)
        except StopIteration:
            pass
        return last["value"]

    monkeypatch.setattr(hover_module.time, "monotonic", monotonic)
    return HoverYawController(FakeParameters())


def test_reset_setpoint_clamps_to_min_altitude(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0])

    controller.reset_setpoint(1.0)

    assert controller.setpoint == 2.0


def test_baseline_parameter_change_applies_live(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])

    controller.on_parameter_changed(ParameterKey.HOV_BASELINE, 1450)

    assert controller._baseline == 1450.0


def test_centered_throttle_does_not_change_setpoint(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 1.0])
    controller.reset_setpoint(3.0)

    controller.update_setpoint_from_throttle(1500)

    assert controller.setpoint == 3.0


def test_throttle_inside_enlarged_deadband_does_not_change_setpoint(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 1.0, 2.0])
    controller.reset_setpoint(3.0)

    controller.update_setpoint_from_throttle(1400)
    controller.update_setpoint_from_throttle(1600)

    assert controller.setpoint == 3.0


def test_high_throttle_increases_setpoint(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 1.0])
    controller.reset_setpoint(3.0)

    controller.update_setpoint_from_throttle(2000)

    assert controller.setpoint == 4.0


def test_altitude_setpoint_request_event_fires_when_throttle_exits_deadband(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    controller.reset_setpoint(3.0)

    controller.update_setpoint_from_throttle(1500)
    assert not controller.consume_altitude_setpoint_request_event()

    controller.update_setpoint_from_throttle(1800)
    assert controller.consume_altitude_setpoint_request_event()
    assert not controller.consume_altitude_setpoint_request_event()

    controller.update_setpoint_from_throttle(1900)
    assert not controller.consume_altitude_setpoint_request_event()

    controller.update_setpoint_from_throttle(1500)
    controller.update_setpoint_from_throttle(1700)
    assert controller.consume_altitude_setpoint_request_event()


def test_low_throttle_decreases_setpoint_but_not_below_min_altitude(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 2.0])
    controller.reset_setpoint(3.0)

    controller.update_setpoint_from_throttle(1000)

    assert controller.setpoint == 2.0


def test_centered_yaw_stick_outputs_mid_yaw(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])

    controller.update_yaw_from_joystick(1500)
    channels = controller.update(setpoint=2.0, current=2.0)

    assert controller.yaw_rate == 0.0
    assert channels[RCChannel.YAW] == RC_MID


def test_yaw_stick_inside_deadband_outputs_mid_yaw(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])

    controller.update_yaw_from_joystick(1530)
    channels = controller.update(setpoint=2.0, current=2.0)

    assert controller.yaw_rate == 0.0
    assert channels[RCChannel.YAW] == RC_MID


def test_right_yaw_stick_increases_yaw_rc(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])

    controller.update_yaw_from_joystick(1700)
    channels = controller.update(setpoint=2.0, current=2.0)

    assert controller.yaw_rate > 0.0
    assert channels[RCChannel.YAW] > RC_MID


def test_left_yaw_stick_decreases_yaw_rc(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])

    controller.update_yaw_from_joystick(1300)
    channels = controller.update(setpoint=2.0, current=2.0)

    assert controller.yaw_rate < 0.0
    assert channels[RCChannel.YAW] < RC_MID


def test_full_yaw_stick_clamps_to_rc_range(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])

    controller.update_yaw_from_joystick(2000)
    right_channels = controller.update(setpoint=2.0, current=2.0)
    controller.update_yaw_from_joystick(1000)
    left_channels = controller.update(setpoint=2.0, current=2.0)

    assert right_channels[RCChannel.YAW] == RC_MAX
    assert left_channels[RCChannel.YAW] == RC_MIN


def test_yaw_expo_is_less_aggressive_than_linear_near_center(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0])
    controller.yaw_expo = 0.35

    expo_rate = controller.update_yaw_from_joystick(1600)
    controller.yaw_expo = 0.0
    linear_rate = controller.update_yaw_from_joystick(1600)

    assert 0.0 < expo_rate < linear_rate


def test_hover_handler_updates_setpoint_from_requested_throttle():
    class FakeHoverController:
        def __init__(self):
            self.setpoint = 5.0
            self.throttle_rc = None
            self.yaw_rc = None
            self.update_args = None

        def update_setpoint_from_throttle(self, throttle_rc):
            self.throttle_rc = throttle_rc

        def update_yaw_from_joystick(self, yaw_rc):
            self.yaw_rc = yaw_rc

        def consume_altitude_setpoint_request_event(self):
            return False

        def update(self, setpoint, current):
            self.update_args = (setpoint, current)
            return [1500] * 8

    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.state = RobotState.ALT_HOLD
    app.ctx.drone_alt = 4.2
    app.ctx.alt_setpoint = 5.0
    app.ctx.request_rc = [1500] * 8
    app.ctx.request_rc[AETR1234.THROTTLE] = 1800
    app.ctx.request_rc[AETR1234.YAW] = 1700
    hover_controller = FakeHoverController()
    app.controllers = {RobotState.ALT_HOLD: hover_controller}

    rc = app.alt_hold_handler()

    assert hover_controller.throttle_rc == 1800
    assert hover_controller.yaw_rc == 1700
    assert hover_controller.update_args == (5.0, 4.2)
    assert rc == [1500] * 8


def test_hover_handler_sends_low_severity_text_when_setpoint_request_starts():
    class FakeHoverController:
        def __init__(self):
            self.setpoint = 5.0
            self.event_pending = True

        def update_setpoint_from_throttle(self, throttle_rc):
            pass

        def update_yaw_from_joystick(self, yaw_rc):
            pass

        def consume_altitude_setpoint_request_event(self):
            if not self.event_pending:
                return False
            self.event_pending = False
            return True

        def update(self, setpoint, current):
            return [1500] * 8

    class FakeMavlinkService:
        def __init__(self):
            self.messages = []

        def send_text_to_gcs(self, text, severity):
            self.messages.append((text, severity))

        def send_named_value_to_gcs(self, name, value):
            pass

    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.state = RobotState.ALT_HOLD
    app.ctx.drone_alt = 4.2
    app.ctx.alt_setpoint = 5.0
    app.ctx.request_rc = [1500] * 8
    app.ctx.request_rc[AETR1234.THROTTLE] = 1800
    app.controllers = {RobotState.ALT_HOLD: FakeHoverController()}
    app.mavlink_service = FakeMavlinkService()

    app.alt_hold_handler()
    app.alt_hold_handler()

    assert app.mavlink_service.messages == [
        ("Hover altitude setpoint change requested", MavSeverity.DEBUG)
    ]

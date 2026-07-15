from bt_app.app import App
from bt_app.common import AETR1234, MavSeverity, RobotState
from bt_app.context import Context
from bt_app.control import hover_yaw_controller as hover_module
from bt_app.control.hover_yaw_controller import HoverYawController
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
            ParameterKey.HOVER_KP: 80.0,
            ParameterKey.HOVER_KI: 10.0,
            ParameterKey.HOVER_KD: 20.0,
            ParameterKey.HOVER_OUTPUT_LIMITS: 400.0,
            ParameterKey.HOVER_ALTITUDE_RATE_M_S: 1.0,
            ParameterKey.HOVER_THROTTLE_DEADBAND: 200,
            ParameterKey.HOVER_MIN_ALTITUDE: 2.0,
            ParameterKey.HOVER_YAW_YAW_RATE: 0,
            ParameterKey.BETAFLIGHT_YAW_RATE_FULL_STICK_DPS: 67.0,
        }

    def get(self, name):
        return self.values[name]


def controller_with_times(monkeypatch, times):
    remaining = iter(times)
    monkeypatch.setattr(hover_module.time, "monotonic", lambda: next(remaining))
    return HoverYawController(FakeParameters())


def test_reset_setpoint_clamps_to_min_altitude(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0])

    controller.reset_setpoint(1.0)

    assert controller.setpoint == 2.0


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


def test_hover_handler_updates_setpoint_from_requested_throttle():
    class FakeHoverController:
        def __init__(self):
            self.setpoint = 5.0
            self.throttle_rc = None
            self.update_args = None

        def update_setpoint_from_throttle(self, throttle_rc):
            self.throttle_rc = throttle_rc

        def consume_altitude_setpoint_request_event(self):
            return False

        def update(self, setpoint, current):
            self.update_args = (setpoint, current)
            return [1500] * 8

    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.state = RobotState.HOVER
    app.ctx.drone_alt = 4.2
    app.ctx.request_rc = [1500] * 8
    app.ctx.request_rc[AETR1234.THROTTLE] = 1800
    hover_controller = FakeHoverController()
    app.controllers = {RobotState.HOVER: hover_controller}

    rc = app.hover_handler()

    assert hover_controller.throttle_rc == 1800
    assert hover_controller.update_args == (5.0, 4.2)
    assert rc == [1500] * 8


def test_hover_handler_sends_low_severity_text_when_setpoint_request_starts():
    class FakeHoverController:
        def __init__(self):
            self.setpoint = 5.0
            self.event_pending = True

        def update_setpoint_from_throttle(self, throttle_rc):
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

    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.state = RobotState.HOVER
    app.ctx.drone_alt = 4.2
    app.ctx.request_rc = [1500] * 8
    app.ctx.request_rc[AETR1234.THROTTLE] = 1800
    app.controllers = {RobotState.HOVER: FakeHoverController()}
    app.mavlink_service = FakeMavlinkService()

    app.hover_handler()
    app.hover_handler()

    assert app.mavlink_service.messages == [
        ("Hover altitude setpoint change requested", MavSeverity.DEBUG)
    ]

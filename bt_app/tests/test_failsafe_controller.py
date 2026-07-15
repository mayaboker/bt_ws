from bt_app.app import App
from bt_app.common import MavSeverity, RobotState
from bt_app.context import Context
from bt_app.control import failsafe_controller as failsafe_module
from bt_app.control.failsafe_controller import FailSafeController, FailSafePhase
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
            ParameterKey.HOVER_KP: 80.0,
            ParameterKey.HOVER_KI: 10.0,
            ParameterKey.HOVER_KD: 20.0,
            ParameterKey.HOVER_OUTPUT_LIMITS: 400.0,
            ParameterKey.FAILSAFE_HOLD_TIME_S: 5.0,
            ParameterKey.FAILSAFE_DESCENT_RATE_M_S: 0.5,
            ParameterKey.FAILSAFE_MIN_ALTITUDE: 0.0,
            ParameterKey.FAILSAFE_LAND_ALTITUDE_M: 0.15,
            ParameterKey.FAILSAFE_LAND_VERTICAL_SPEED_M_S: 0.1,
            ParameterKey.FAILSAFE_LAND_CONFIRM_S: 1.0,
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

    monkeypatch.setattr(failsafe_module.time, "monotonic", monotonic)
    return FailSafeController(FakeParameters())


def test_reset_starts_hold_phase_at_current_altitude(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0])

    controller.reset(4.0)

    assert controller.phase == FailSafePhase.HOLD
    assert controller.setpoint == 4.0
    assert not controller.consume_descent_started_event()


def test_holds_altitude_before_timeout(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 4.0])
    controller.reset(4.0)

    controller.update(current_altitude=4.0, vertical_speed_m_s=0.0)

    assert controller.phase == FailSafePhase.HOLD
    assert controller.setpoint == 4.0


def test_starts_descent_after_timeout_and_emits_event_once(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 6.0])
    controller.reset(4.0)

    controller.update(current_altitude=4.0, vertical_speed_m_s=0.0)

    assert controller.phase == FailSafePhase.DESCEND
    assert controller.setpoint == 1.0
    assert controller.consume_descent_started_event()
    assert not controller.consume_descent_started_event()


def test_zero_hold_time_disables_descent_phase(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 60.0])
    controller.hold_time_s = 0.0
    controller.reset(4.0)

    controller.update(current_altitude=4.0, vertical_speed_m_s=0.0)

    assert controller.phase == FailSafePhase.HOLD
    assert controller.setpoint == 4.0
    assert not controller.consume_descent_started_event()


def test_descent_setpoint_clamps_to_min_altitude(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 20.0])
    controller.reset(1.0)
    controller.min_altitude = 0.5

    controller.update(current_altitude=1.0, vertical_speed_m_s=1.0)

    assert controller.setpoint == 0.5


def test_land_detection_requires_confirm_time(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0, 6.0, 6.0, 6.5, 6.5, 7.6])
    controller.reset(0.2)
    controller.update(current_altitude=0.2, vertical_speed_m_s=0.0)

    controller.update(current_altitude=0.1, vertical_speed_m_s=0.0)
    assert controller.phase == FailSafePhase.DESCEND

    controller.update(current_altitude=0.1, vertical_speed_m_s=0.0)
    assert controller.phase == FailSafePhase.LANDED
    assert controller.consume_landed_event()


def test_landed_phase_outputs_disarm_channels(monkeypatch):
    controller = controller_with_times(monkeypatch, [0.0, 0.0])
    controller.reset(0.0)
    controller.phase = FailSafePhase.LANDED

    channels = controller.update(current_altitude=0.0, vertical_speed_m_s=0.0)

    assert channels[RCChannel.THROTTLE] == RC_MIN
    assert channels[RCChannel.ARM] == RC_MIN
    assert channels[RCChannel.ROLL] == RC_MID
    assert channels[RCChannel.PITCH] == RC_MID
    assert channels[RCChannel.YAW] == RC_MID
    assert channels[RCChannel.ANGLE] == RC_MAX


def test_app_failsafe_handler_sends_gcs_messages_once():
    class FakeFailsafeController:
        def __init__(self):
            self.calls = []
            self.descent_event = True
            self.landed_event = True

        def update(self, current_altitude, vertical_speed_m_s):
            self.calls.append((current_altitude, vertical_speed_m_s))
            return [1500] * 8

        def consume_descent_started_event(self):
            if not self.descent_event:
                return False
            self.descent_event = False
            return True

        def consume_landed_event(self):
            if not self.landed_event:
                return False
            self.landed_event = False
            return True

    class FakeMavlinkService:
        def __init__(self):
            self.messages = []

        def send_text_to_gcs(self, text, severity):
            self.messages.append((text, severity))

    app = App.__new__(App)
    app.ctx = Context()
    app.ctx.drone_alt = 1.2
    app.ctx.drone_vertical_speed = -0.1
    controller = FakeFailsafeController()
    app.controllers = {RobotState.FAILSAFE: controller}
    app.mavlink_service = FakeMavlinkService()

    assert app.failsafe_handler() == [1500] * 8
    assert app.failsafe_handler() == [1500] * 8

    assert controller.calls == [(1.2, -0.1), (1.2, -0.1)]
    assert app.mavlink_service.messages == [
        ("Failsafe landing started", MavSeverity.WARNING),
        ("Failsafe land detected, disarming", MavSeverity.WARNING),
    ]

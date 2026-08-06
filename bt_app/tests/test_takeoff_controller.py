from bt_app.control.takeoff_controller import TakeoffController
from bt_app.msp.bt_v2 import RCChannel_alias as RCChannel
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
            ParameterKey.ALT_KP: 60.0,
            ParameterKey.ALT_KI: 0.0,
            ParameterKey.ALT_KD: 6.0,
            ParameterKey.ALT_OUT_LIMIT: 400.0,
            ParameterKey.TAKEOFF_RATE: 1.0,
            ParameterKey.HOV_BASELINE: 1660,
        }

    def get(self, name):
        return self.values[name]


def test_takeoff_setpoint_ramps_from_measured_altitude(monkeypatch):
    times = iter([10.0, 10.0, 11.0, 11.0, 12.0, 12.0])
    monkeypatch.setattr(
        "bt_app.control.takeoff_controller.time.monotonic",
        lambda: next(times),
    )
    controller = TakeoffController(FakeParameters())

    initial = controller.update(setpoint=2.0, current=0.0)
    first_step = controller.update(setpoint=2.0, current=0.0)
    final_step = controller.update(setpoint=2.0, current=0.0)

    assert initial[RCChannel.THROTTLE] == 1660
    assert first_step[RCChannel.THROTTLE] == 1720
    assert final_step[RCChannel.THROTTLE] == 1780
    assert controller.setpoint == 2.0


def test_reset_restarts_ramp_at_current_altitude(monkeypatch):
    times = iter([10.0, 10.0, 11.0, 11.0, 20.0, 20.0])
    monkeypatch.setattr(
        "bt_app.control.takeoff_controller.time.monotonic",
        lambda: next(times),
    )
    controller = TakeoffController(FakeParameters())
    controller.update(setpoint=2.0, current=0.0)
    controller.update(setpoint=2.0, current=0.0)

    controller.reset()
    channels = controller.update(setpoint=3.0, current=0.5)

    assert controller.setpoint == 0.5
    assert channels[RCChannel.THROTTLE] == 1660


def test_hover_baseline_parameter_change_applies_live():
    controller = TakeoffController(FakeParameters())

    controller.on_parameter_changed(ParameterKey.HOV_BASELINE, 1750)
    channels = controller.make_channels(correction=120)

    assert channels[RCChannel.THROTTLE] == 1870


def test_takeoff_rate_parameter_change_applies_live():
    controller = TakeoffController(FakeParameters())

    controller.on_parameter_changed(ParameterKey.TAKEOFF_RATE, 0.5)

    assert controller._takeoff_rate_mps == 0.5


def test_takeoff_damps_upward_velocity():
    controller = TakeoffController(FakeParameters())

    assert controller._derive_vertical_speed(0.0, 10.0) == 0.0
    assert controller._derive_vertical_speed(1.0, 11.0) == 1.0

    assert controller._vertical_speed_gain == 6.0


def test_velocity_damping_is_included_in_takeoff_output_limit(monkeypatch):
    times = iter([0.0, 0.0, 1.0, 1.0])
    monkeypatch.setattr(
        "bt_app.control.takeoff_controller.time.monotonic",
        lambda: next(times),
    )
    controller = TakeoffController(FakeParameters())
    controller.on_parameter_changed(ParameterKey.ALT_KD, 1000.0)
    controller.on_parameter_changed(ParameterKey.ALT_OUT_LIMIT, 100.0)
    controller.update(2.0, 0.0, altitude_sample_time_s=0.0)

    channels = controller.update(2.0, 1.0, altitude_sample_time_s=1.0)

    assert channels[RCChannel.THROTTLE] == 1560


def test_takeoff_settle_time_requires_altitude_and_low_vertical_speed(monkeypatch):
    times = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0])
    monkeypatch.setattr(
        "bt_app.control.takeoff_controller.time.monotonic",
        lambda: next(times),
    )
    controller = TakeoffController(FakeParameters())

    controller.update(2.0, 1.8, altitude_sample_time_s=0.0)

    # Inside the altitude band, but still climbing too quickly.
    controller.update(2.0, 1.9, altitude_sample_time_s=0.2)
    assert controller.time_in_alt == 0.0

    # The timer starts only after vertical motion has settled.
    controller.update(2.0, 1.91, altitude_sample_time_s=1.2)
    assert controller.time_in_alt == 1.0

    controller.update(2.0, 2.21, altitude_sample_time_s=2.2)
    assert controller.time_in_alt == 0.0


def test_takeoff_settle_time_resets_when_vertical_speed_increases(monkeypatch):
    times = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0])
    monkeypatch.setattr(
        "bt_app.control.takeoff_controller.time.monotonic",
        lambda: next(times),
    )
    controller = TakeoffController(FakeParameters())

    controller.update(2.0, 1.90, altitude_sample_time_s=0.0)
    controller.update(2.0, 1.91, altitude_sample_time_s=1.0)
    assert controller.time_in_alt == 1.0

    controller.update(2.0, 2.09, altitude_sample_time_s=2.0)
    assert controller.time_in_alt == 0.0


def test_takeoff_output_is_clamped_to_rc_range():
    controller = TakeoffController(FakeParameters())

    assert controller.make_channels(correction=400)[RCChannel.THROTTLE] == 2000
    assert controller.make_channels(correction=-800)[RCChannel.THROTTLE] == 1000

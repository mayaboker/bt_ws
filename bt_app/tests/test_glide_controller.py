import pytest

from bt_app.control.glide_controller import GlideController
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
            ParameterKey.GLIDE_DESC_RATE: 0.5,
            ParameterKey.GLIDE_VEL_KP: 100.0,
            ParameterKey.GLIDE_VEL_KI: 20.0,
            ParameterKey.GLIDE_FLARE_ALT: 1.0,
            ParameterKey.GLIDE_FLARE_RATE: 0.15,
            ParameterKey.GLIDE_OUT_LIMIT: 150.0,
            ParameterKey.GLIDE_LAND_ALT: 0.15,
            ParameterKey.GLIDE_LAND_VS: 0.1,
            ParameterKey.GLIDE_LAND_SEC: 1.0,
            ParameterKey.HOV_BASELINE: 1660,
        }

    def get(self, name):
        return self.values[name]


def make_clock(monkeypatch, initial=0.0):
    clock = [initial]
    monkeypatch.setattr(
        "bt_app.control.glide_controller.time.monotonic", lambda: clock[0]
    )
    return clock


def test_velocity_pi_lowers_throttle_when_descent_is_too_slow(monkeypatch):
    clock = make_clock(monkeypatch)
    controller = GlideController(FakeParameters())
    controller.reset(3.0, altitude_sample_time_s=0.0)

    clock[0] = 0.05
    channels = controller.update(3.0, 0.0, altitude_sample_time_s=0.05)

    assert controller.setpoint == -0.5
    assert channels[RCChannel.THROTTLE] < 1660


def test_velocity_pi_adds_throttle_when_descent_is_too_fast(monkeypatch):
    clock = make_clock(monkeypatch)
    controller = GlideController(FakeParameters())
    controller.reset(3.0, altitude_sample_time_s=0.0)

    clock[0] = 0.05
    channels = controller.update(3.0, -1.0, altitude_sample_time_s=0.05)

    assert channels[RCChannel.THROTTLE] > 1660


def test_pi_updates_only_once_for_each_msp_sample(monkeypatch):
    clock = make_clock(monkeypatch)
    controller = GlideController(FakeParameters())
    controller.reset(3.0, altitude_sample_time_s=0.0)
    clock[0] = 0.05
    first = controller.update(3.0, 0.0, altitude_sample_time_s=0.05)
    integral = controller._integral

    clock[0] = 0.06
    repeated = controller.update(3.0, 0.0, altitude_sample_time_s=0.05)

    assert repeated == first
    assert controller._integral == integral


def test_pi_anti_windup_rejects_error_that_deepens_saturation():
    controller = GlideController(FakeParameters())
    controller._output_limit = 10.0

    output = controller._update_pi(-0.5, 2.0, 1.0)

    assert output == -10.0
    assert controller._integral == 0.0


def test_flare_interpolates_descent_target():
    controller = GlideController(FakeParameters())

    assert controller._target_velocity(2.0) == -0.5
    assert controller._target_velocity(0.15) == -0.15
    assert controller._target_velocity(0.575) == pytest.approx(-0.325)


def test_stale_vario_commands_hover_baseline_without_integrating(monkeypatch):
    clock = make_clock(monkeypatch, 1.0)
    controller = GlideController(FakeParameters())
    controller.reset(3.0, altitude_sample_time_s=0.0)
    controller._integral = -2.0

    channels = controller.update(3.0, -2.0, altitude_sample_time_s=0.0)

    assert channels[RCChannel.THROTTLE] == 1660
    assert controller._integral == -2.0

    clock[0] = 1.05
    recovered = controller.update(3.0, -0.5, altitude_sample_time_s=1.05)
    assert recovered[RCChannel.THROTTLE] == 1660
    assert controller._integral == -2.0

    clock[0] = 1.1
    controller.update(3.0, -0.5, altitude_sample_time_s=1.1)
    assert controller._integral == -2.0


def test_output_limit_is_correction_not_absolute_pwm():
    controller = GlideController(FakeParameters())

    assert controller.make_channels(-150)[RCChannel.THROTTLE] == 1510
    assert controller.make_channels(150)[RCChannel.THROTTLE] == 1810
    assert controller.make_channels(-1000)[RCChannel.THROTTLE] == RC_MIN
    assert controller.make_channels(1000)[RCChannel.THROTTLE] == RC_MAX


def test_glide_keeps_level_angle_mode_armed():
    channels = GlideController(FakeParameters()).make_channels()

    assert channels[RCChannel.ROLL] == RC_MID
    assert channels[RCChannel.PITCH] == RC_MID
    assert channels[RCChannel.YAW] == RC_MID
    assert channels[RCChannel.ARM] == RC_MAX
    assert channels[RCChannel.ANGLE] == RC_MAX


def test_landing_requires_fresh_low_speed_and_confirmation_time(monkeypatch):
    clock = make_clock(monkeypatch)
    controller = GlideController(FakeParameters())
    controller.reset(0.1, altitude_sample_time_s=0.0)

    clock[0] = 0.05
    first = controller.update(0.05, 0.0, altitude_sample_time_s=0.05)
    assert first[RCChannel.ARM] == RC_MAX
    assert not controller.landed

    clock[0] = 1.1
    landed = controller.update(0.05, 0.0, altitude_sample_time_s=1.1)
    assert landed[RCChannel.ARM] == RC_MIN
    assert landed[RCChannel.THROTTLE] == RC_MIN
    assert controller.consume_landed_event()
    assert not controller.consume_landed_event()


def test_live_parameter_updates_apply():
    controller = GlideController(FakeParameters())

    controller.on_parameter_changed(ParameterKey.GLIDE_DESC_RATE, 0.8)
    controller.on_parameter_changed(ParameterKey.GLIDE_VEL_KP, 120.0)
    controller.on_parameter_changed(ParameterKey.GLIDE_FLARE_RATE, 0.2)
    controller.on_parameter_changed(ParameterKey.GLIDE_OUT_LIMIT, 100.0)
    controller.on_parameter_changed(ParameterKey.HOV_BASELINE, 1700)

    assert controller._descent_rate_m_s == 0.8
    assert controller._kp == 120.0
    assert controller._flare_rate_m_s == 0.2
    assert controller._output_limit == 100.0
    assert controller.make_channels(-100)[RCChannel.THROTTLE] == 1600

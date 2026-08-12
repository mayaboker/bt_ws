from dataclasses import replace

import pytest

from bt_app.control.glide_controller import GlideControlResult, GlideController
from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.estimators import GlideObservation
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey


class Event:
    def subscribe(self, callback):
        self.callback = callback


class Params:
    def __init__(self):
        self.on_parameter_changed = Event()
        self.values = {
            ParameterKey.HOV_BASELINE: 1660,
            ParameterKey.GLIDE_PITCH_FF: -20.0,
            ParameterKey.GLIDE_PITCH_MAX: 25.0,
            ParameterKey.GLIDE_VX_KP: 1.0,
            ParameterKey.GLIDE_VX_KI: 0.1,
            ParameterKey.GLIDE_VY_KP: 10.0,
            ParameterKey.GLIDE_VY_KI: 0.0,
            ParameterKey.GLIDE_VY_OUT: 100.0,
            ParameterKey.GLIDE_YAW_KP: 15.0,
            ParameterKey.GLIDE_YAW_MAX: 20.0,
            ParameterKey.GLIDE_CENTER_KY: 1.0,
            ParameterKey.GLIDE_DEPTH_EMA: 0.35,
            ParameterKey.BF_ANGLE_LIMIT: 60.0,
            ParameterKey.BF_YAW_RATE: 67.0,
        }

    def get(self, name):
        return self.values[name]


def observation(frame=1, received=1.0, depth=10.0, ex=0.0, ey=0.0,
                vx=15.0, vy=0.0, valid=True, reason=None):
    return GlideObservation(
        frame, frame, received, 0.0, (100, 100, 50, 50), ex, ey,
        min(1.0, (ex * ex + ey * ey) ** 0.5), 1.0, depth, 0.0,
        vx, vy, (vx * vx + vy * vy) ** 0.5, False, valid, reason,
    )


def update(controller, obs, *, vario=0.0, vario_time=None, now=None):
    sample = obs.received_at_s if vario_time is None else vario_time
    current = sample if now is None else now
    return controller.update(
        obs,
        vertical_speed_m_s=vario,
        vertical_speed_received_at_s=sample,
        now_s=current,
    )


def test_first_frame_uses_feedforward_without_forward_feedback():
    result = update(GlideController(Params()), observation())
    assert isinstance(result, GlideControlResult)
    assert result.pitch_feedforward_deg == pytest.approx(-20.0)
    assert result.pitch_feedback_deg == 0.0
    assert not result.forward_feedback_active
    assert result.channels[RCChannel.PITCH] > RC_MID


def test_depth_derivative_uses_local_receipt_time_and_activates_feedback():
    controller = GlideController(Params())
    update(controller, observation(frame=1, received=1.0, depth=10.0))
    result = update(controller, observation(frame=2, received=1.5, depth=8.0))
    assert result.vx_measured_m_s == pytest.approx(4.0)
    assert result.forward_feedback_active
    assert result.pitch_feedback_deg < 0.0
    assert result.pitch_command_deg < result.pitch_feedforward_deg


def test_duplicate_frame_holds_forward_filter_and_integral():
    controller = GlideController(Params())
    update(controller, observation(frame=1, received=1.0, depth=10.0))
    first = update(controller, observation(frame=2, received=2.0, depth=8.0))
    integral = controller._vx_integral
    repeated = update(controller, observation(frame=2, received=2.0, depth=8.0), now=2.1)
    assert repeated.vx_measured_m_s == first.vx_measured_m_s
    assert controller._vx_integral == integral


def test_three_sample_median_then_ema_rejects_depth_velocity_spike():
    controller = GlideController(Params())
    update(controller, observation(1, 1.0, 10.0))
    update(controller, observation(2, 2.0, 9.0))       # raw 1
    update(controller, observation(3, 3.0, 1.0))       # raw 8
    result = update(controller, observation(4, 4.0, 0.5))  # raw .5, median 1
    assert result.vx_measured_m_s < 2.0


def test_vertical_request_correction_and_vario_timestamp_gate():
    controller = GlideController(Params(), max_vertical_speed_m_s=3.0)
    first = update(controller, observation(ey=0.25, vy=2.9), vario_time=1.0)
    assert first.vy_desired_m_s == 3.0
    assert first.throttle_correction_rc == 0.0
    second = update(controller, observation(2, 2.0, 9.0, ey=0.25, vy=2.9),
                    vario=0.0, vario_time=2.0)
    assert second.throttle_correction_rc > 0.0
    held = update(controller, observation(2, 2.0, 9.0, ey=0.25, vy=2.9),
                  vario=-3.0, vario_time=2.0, now=2.1)
    assert held.throttle_correction_rc == second.throttle_correction_rc


def test_yaw_deadband_direction_and_limit():
    controller = GlideController(Params(), center_deadband=0.05)
    assert update(controller, observation(ex=0.04)).yaw_rate_dps == 0.0
    assert update(controller, observation(2, 2.0, 9.0, ex=0.25)).yaw_rate_dps > 0.0
    saturated = update(controller, observation(3, 3.0, 8.0, ex=1.0))
    assert saturated.yaw_rate_dps <= 20.0


def test_invalid_or_stale_input_returns_neutral_hover_and_resets():
    controller = GlideController(Params())
    update(controller, observation())
    invalid = update(controller, replace(observation(), valid=False, reason="lost"))
    assert not invalid.valid and invalid.reason == "lost"
    assert invalid.channels[RCChannel.PITCH] == RC_MID
    assert invalid.channels[RCChannel.YAW] == RC_MID
    assert invalid.channels[RCChannel.THROTTLE] == 1660
    assert invalid.channels[RCChannel.ARM] == RC_MAX
    stale = update(controller, observation(), vario_time=0.0, now=1.0)
    assert not stale.valid and stale.reason == "vertical speed stale"


def test_reset_clears_all_control_history():
    controller = GlideController(Params())
    update(controller, observation(1, 1.0, 10.0))
    update(controller, observation(2, 2.0, 8.0))
    controller.reset()
    assert controller._vx_measured is None
    assert controller._vx_integral == 0.0
    assert controller._vy_integral == 0.0


def test_pitch_and_throttle_outputs_are_bounded():
    params = Params()
    params.values[ParameterKey.GLIDE_VX_KP] = 100.0
    params.values[ParameterKey.GLIDE_VY_KP] = 1000.0
    controller = GlideController(params)
    update(controller, observation(1, 1.0, 10.0))
    result = update(controller, observation(2, 2.0, 10.0), vario=-10.0)
    assert abs(result.pitch_command_deg) <= 25.0
    assert abs(result.throttle_correction_rc) <= 100.0
    assert result.pitch_saturated
    assert result.throttle_saturated


def test_pi_anti_windup_rejects_integral_that_deepens_saturation():
    output, integral, saturated = GlideController._pi(
        10.0, 1.0, 0.0, -5.0, 5.0,
        output_sign=1.0, kp=10.0, ki=1.0,
    )
    assert output == 5.0
    assert integral == 0.0
    assert saturated


def test_complete_command_centers_roll_and_enables_angle_mode():
    result = update(GlideController(Params()), observation())
    assert result.channels[RCChannel.ROLL] == RC_MID
    assert result.channels[RCChannel.ARM] == RC_MAX
    assert result.channels[RCChannel.ANGLE] == RC_MAX


def test_angle_mapper_clamps_physical_attitude_and_validates_limit():
    mapper = BetaflightRcMapper(yaw_rate_full_stick_dps=67.0)
    assert mapper.angle_to_rc(0.0, angle_limit_deg=60.0) == RC_MID
    assert mapper.angle_to_rc(60.0, angle_limit_deg=60.0) == 2000
    assert mapper.angle_to_rc(-120.0, angle_limit_deg=60.0) == 1000
    with pytest.raises(ValueError, match="angle_limit_deg"):
        mapper.angle_to_rc(1.0, angle_limit_deg=0.0)

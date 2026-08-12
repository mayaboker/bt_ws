from dataclasses import replace

import pytest

from bt_app.control.glide_controller import (
    GlideAircraftState,
    GlideControlResult,
    GlideController,
    GlidePhase,
)
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
            ParameterKey.GLIDE_YAW_DB: 0.02,
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
    if controller.phase == GlidePhase.IDLE:
        controller.begin_acquisition()
        for frame_id in range(-controller._lock_frame_count, 0):
            controller.observe_acquisition(replace(observation(), frame_id=frame_id))
        assert controller.engage()
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


def test_each_update_records_aircraft_and_control_diagnostic():
    class Recorder:
        def __init__(self):
            self.samples = []
            self.started = 0
            self.stopped = 0

        def start(self):
            self.started += 1

        def record(self, sample):
            self.samples.append(sample)

        def stop(self):
            self.stopped += 1

    recorder = Recorder()
    controller = GlideController(Params(), diagnostic_enabled=False)
    controller._diagnostic_recorder = recorder
    obs = observation(ex=0.2, ey=-0.1, depth=8.0, vx=2.0, vy=-0.4)
    if controller.phase == GlidePhase.IDLE:
        controller.begin_acquisition()
        for frame_id in range(-controller._lock_frame_count, 0):
            controller.observe_acquisition(replace(observation(), frame_id=frame_id))
        assert controller.engage()

    result = controller.update(
        obs,
        vertical_speed_m_s=-0.3,
        vertical_speed_received_at_s=1.0,
        aircraft_state=GlideAircraftState(5.0, 1.0, 2.0, 3.0),
        now_s=1.0,
    )

    assert len(recorder.samples) == 1
    diagnostic = recorder.samples[0]
    assert diagnostic.glide_phase == result.phase.value
    assert diagnostic.dx_norm == pytest.approx(0.2)
    assert diagnostic.dy_norm == pytest.approx(-0.1)
    assert diagnostic.altitude_m == pytest.approx(5.0)
    assert diagnostic.distance_to_target_m == pytest.approx(8.0)
    assert diagnostic.pitch_deg == pytest.approx(2.0)
    assert diagnostic.throttle_rc == result.channels[RCChannel.THROTTLE]
    assert recorder.started == 1

    controller.close_attempt()
    assert recorder.stopped == 1
    assert controller.phase == GlidePhase.IDLE


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
    update(controller, observation(3, 3.0, 2.0))       # raw 7
    result = update(controller, observation(4, 4.0, 1.5))  # raw .5, median 1
    assert result.vx_measured_m_s < 2.0


def test_vertical_request_correction_and_vario_timestamp_gate():
    controller = GlideController(Params(), max_vertical_speed_m_s=3.0)
    first = update(controller, observation(ey=0.25, vy=2.9), vario_time=1.0)
    assert first.vy_desired_m_s == 3.0
    assert first.throttle_correction_rc == pytest.approx(30.0)
    second = update(controller, observation(2, 2.0, 9.0, ey=0.25, vy=2.9),
                    vario=0.0, vario_time=2.0)
    assert second.throttle_correction_rc > 0.0
    held = update(controller, observation(2, 2.0, 9.0, ey=0.25, vy=2.9),
                  vario=-3.0, vario_time=2.0, now=2.1)
    assert held.throttle_correction_rc == second.throttle_correction_rc


def test_first_vertical_sample_applies_descent_proportional_correction():
    controller = GlideController(Params())

    result = update(
        controller,
        observation(vy=-1.0),
        vario=0.0,
        vario_time=1.0,
    )

    assert result.vy_desired_m_s == pytest.approx(-1.0)
    assert result.throttle_correction_rc == pytest.approx(-10.0)
    assert result.channels[RCChannel.THROTTLE] == 1650
    assert not result.throttle_saturated


def test_yaw_deadband_direction_and_limit():
    controller = GlideController(Params(), center_deadband=0.05)
    assert update(controller, observation(ex=0.01)).yaw_rate_dps == 0.0
    assert update(controller, observation(2, 2.0, 9.5, ex=0.04)).yaw_rate_dps > 0.0
    assert update(controller, observation(3, 3.0, 9.0, ex=0.25)).yaw_rate_dps > 0.0
    saturated = update(controller, observation(4, 4.0, 8.0, ex=1.0))
    assert saturated.yaw_rate_dps <= 20.0


def test_short_invalid_input_is_held_but_stale_vario_aborts():
    controller = GlideController(Params())
    update(controller, observation())
    invalid = update(controller, replace(observation(), valid=False, reason="lost"))
    assert invalid.valid
    assert controller.phase == GlidePhase.TRACK
    assert invalid.channels[RCChannel.ARM] == RC_MAX
    controller.reset()
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


def test_acquisition_requires_distinct_consecutive_centered_frames():
    controller = GlideController(
        Params(), lock_frame_count=3, acquisition_error_max=0.10
    )
    controller.begin_acquisition()
    assert not controller.observe_acquisition(observation(1, ex=0.0))
    assert controller.acquisition_count == 1
    assert not controller.observe_acquisition(observation(1, ex=0.8))
    assert controller.acquisition_count == 1
    assert not controller.observe_acquisition(observation(2, ex=0.2))
    assert controller.acquisition_count == 0
    assert not controller.observe_acquisition(observation(3))
    assert not controller.observe_acquisition(observation(4))
    assert controller.observe_acquisition(observation(5))
    assert controller.engage()
    assert controller.phase == GlidePhase.TRACK


def test_acquisition_accepts_target_outside_full_speed_deadband():
    controller = GlideController(
        Params(),
        center_deadband=0.05,
        acquisition_error_max=0.40,
        lock_frame_count=2,
    )
    controller.begin_acquisition()

    assert not controller.observe_acquisition(observation(1, ex=0.30, ey=0.10))
    assert controller.observe_acquisition(observation(2, ex=0.30, ey=0.10))
    assert controller.engage()


def test_acquisition_rejects_target_outside_maximum_centering_region():
    controller = GlideController(
        Params(), acquisition_error_max=0.40, lock_frame_count=1
    )
    controller.begin_acquisition()

    assert not controller.observe_acquisition(observation(1, ex=0.40, ey=0.10))
    assert controller.acquisition_count == 0


def test_commit_freezes_complete_command_and_times_out_to_neutral():
    controller = GlideController(
        Params(), lock_frame_count=1, commit_depth_m=1.0, commit_timeout_s=1.0
    )
    first = update(controller, observation(1, 1.0, 0.9), now=1.0)
    assert first.phase == GlidePhase.COMMIT
    frozen = update(controller, observation(2, 1.1, 0.2, ex=0.9), now=1.5)
    assert frozen is first
    timed_out = update(controller, observation(3, 2.1, 0.1), now=2.01)
    assert timed_out.phase == GlidePhase.COMMIT_TIMEOUT
    assert timed_out.channels[RCChannel.PITCH] == RC_MID
    assert not timed_out.valid


def test_track_input_failure_aborts_and_returns_one_neutral_command():
    controller = GlideController(Params(), lock_frame_count=1)
    result = update(
        controller, replace(observation(), valid=False, reason="target lost")
    )
    assert controller.phase == GlidePhase.ABORTED
    assert result.abort_reason == "target lost"
    assert result.channels[RCChannel.PITCH] == RC_MID


def test_short_invalid_visual_holds_last_vector_and_new_centering_error():
    controller = GlideController(Params(), lock_frame_count=1)
    valid = update(controller, observation(1, 1.0, 10.0, ex=0.20), now=1.0)
    degraded = GlideObservation.invalid(
        "width/height depth disagreement",
        frame_id=2,
        received_at_s=1.1,
        age_s=0.0,
        ex=-0.20,
        ey=0.10,
        centering_error=0.22,
    )

    held = update(controller, degraded, now=1.1, vario_time=1.1)

    assert controller.phase == GlidePhase.TRACK
    assert held.valid
    assert held.vx_desired_m_s == valid.vx_desired_m_s
    assert held.yaw_rate_dps < 0.0


def test_invalid_visual_aborts_after_hold_timeout():
    controller = GlideController(Params(), lock_frame_count=1)
    update(controller, observation(1, 1.0, 10.0), now=1.0)
    invalid = GlideObservation.invalid(
        "target not found", frame_id=2, received_at_s=1.4, age_s=0.0
    )

    result = update(controller, invalid, now=1.4, vario_time=1.4)

    assert controller.phase == GlidePhase.ABORTED
    assert not result.valid
    assert result.abort_reason == "target not found"


def test_ordinary_abort_is_ignored_after_commit():
    controller = GlideController(Params(), lock_frame_count=1)
    committed = update(controller, observation(depth=0.9), now=1.0)
    controller.abort("switch released")
    assert controller.phase == GlidePhase.COMMIT
    assert update(controller, observation(depth=0.5), now=1.2) is committed

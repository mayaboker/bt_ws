from __future__ import annotations

import csv
import math

import pytest

from bt_app.control.rc_mapper import BetaflightRcMapper
from bt_app.control.tracker_controller import TrackerController, TrackerPhase
from bt_app.msp.bt_v2 import RC_MAX, RC_MID, RC_MIN, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey
from bt_app.services import TargetEstimate


class FakeEvent:
    def __init__(self):
        self.subscribers = []

    def subscribe(self, callback):
        self.subscribers.append(callback)

    def emit(self, name, value):
        for callback in tuple(self.subscribers):
            callback(name, value)


class FakeParameters:
    def __init__(self):
        self.on_parameter_changed = FakeEvent()
        self.values = {
            ParameterKey.TRK_PITCH_DEG: -10.0,
            ParameterKey.TRK_PITCH_RATE: 5.0,
            ParameterKey.TRK_YAW_KP: 15.0,
            ParameterKey.TRK_YAW_MAX: 20.0,
            ParameterKey.TRK_THR_KP: 100.0,
            ParameterKey.TRK_VZ_KD: 20.0,
            ParameterKey.TRK_VZ_MAX: 1.0,
            ParameterKey.TRK_VZ_ACCEL: 0.75,
            ParameterKey.TRK_VZ_NEAR: 0.5,
            ParameterKey.TRK_VZ_TAPER_S: 6.0,
            ParameterKey.TRK_VZ_TAPER_E: 2.0,
            ParameterKey.TRK_VZ_BRAKE: 1.5,
            ParameterKey.TRK_THR_MAX: 100.0,
            ParameterKey.TRK_DEADBAND: 0.03,
            ParameterKey.TRK_TIMEOUT_S: 0.25,
            ParameterKey.TRK_LOCK_FRAMES: 3,
            ParameterKey.TRK_COMMIT_M: 1.0,
            ParameterKey.TRK_COMMIT_S: 1.0,
            ParameterKey.TRK_COMMIT_XY: 0.1,
            ParameterKey.TRK_COMMIT_VZ: 0.5,
            ParameterKey.TRK_COMMIT_HOLD: 0.25,
            ParameterKey.TRK_TERM_TIMEOUT: 2.0,
            ParameterKey.BF_ANGLE_LIMIT: 60.0,
            ParameterKey.HOV_BASELINE: 1500,
            ParameterKey.BF_YAW_RATE: 67.0,
        }

    def get(self, name):
        return self.values[name]


def estimate(
    frame_id=1,
    *,
    received_at_s=0.0,
    depth_m=10.0,
    error_x=0.0,
    error_y=0.0,
    valid=True,
):
    return TargetEstimate(
        frame_id=frame_id,
        timestamp_ns=frame_id * 10,
        received_at_s=received_at_s,
        depth_m=depth_m if valid else None,
        slant_range_m=depth_m if valid else None,
        error_x=error_x if valid else None,
        error_y=error_y if valid else None,
        vx_m_s=5.0 if valid else 0.0,
        vy_m_s=0.0,
        valid=valid,
        reason=None if valid else "lost",
    )


_UNSET = object()


def update_controller(
    controller,
    *,
    now_s,
    vertical_speed_m_s=0.0,
    vertical_speed_sample_time_s=_UNSET,
):
    sample_time_s = (
        now_s
        if vertical_speed_sample_time_s is _UNSET
        else vertical_speed_sample_time_s
    )
    return controller.update(
        now_s=now_s,
        vertical_speed_m_s=vertical_speed_m_s,
        vertical_speed_sample_time_s=sample_time_s,
    )


def acquire(controller, *, now_s=0.0, target=None, vertical_speed_m_s=0.0):
    for frame_id in range(1, 4):
        observation = target or estimate(frame_id, received_at_s=now_s)
        if target is not None:
            observation = estimate(
                frame_id,
                received_at_s=now_s,
                depth_m=target.depth_m,
                error_x=target.error_x,
                error_y=target.error_y,
            )
        controller.observe(observation, now_s=now_s, mode_selected=True)
    assert controller.ready_to_track
    controller.start_tracking(
        now_s=now_s,
        vertical_speed_m_s=vertical_speed_m_s,
        vertical_speed_sample_time_s=now_s,
    )


def test_angle_mapper_uses_active_simulator_forward_pitch_sign():
    mapper = BetaflightRcMapper(yaw_rate_full_stick_dps=67.0)

    assert mapper.angle_to_rc(-10.0, angle_limit_deg=60.0) == 1417
    assert mapper.angle_to_rc(10.0, angle_limit_deg=60.0) == 1583
    assert mapper.angle_to_rc(-100.0, angle_limit_deg=60.0) == RC_MIN


def test_acquisition_requires_three_distinct_fresh_frames():
    controller = TrackerController(FakeParameters())

    first = estimate(1)
    controller.observe(first, now_s=0.0, mode_selected=True)
    controller.observe(first, now_s=0.0, mode_selected=True)
    assert not controller.ready_to_track
    controller.observe(estimate(2), now_s=0.0, mode_selected=True)
    assert not controller.ready_to_track
    controller.observe(estimate(3), now_s=0.0, mode_selected=True)

    assert controller.ready_to_track


def test_centered_target_smoothly_commands_forward_pitch_and_hover_compensation():
    controller = TrackerController(FakeParameters())
    acquire(controller)

    initial = update_controller(controller, now_s=0.0)
    controller.observe(
        estimate(4, received_at_s=1.0), now_s=1.0, mode_selected=True
    )
    halfway = update_controller(controller, now_s=1.0)
    controller.observe(
        estimate(5, received_at_s=2.0), now_s=2.0, mode_selected=True
    )
    result = update_controller(controller, now_s=2.0)

    assert initial.pitch_command_deg == 0.0
    assert initial.channels[RCChannel.PITCH] == RC_MID
    assert halfway.pitch_command_deg == -5.0
    assert result.valid
    assert result.phase == TrackerPhase.TRACKING
    assert len(result.channels) == 8
    assert result.channels[RCChannel.ROLL] == RC_MID
    assert halfway.channels[RCChannel.PITCH] == 1542
    assert result.channels[RCChannel.PITCH] == 1583
    assert result.channels[RCChannel.THROTTLE] == 1508
    assert result.channels[RCChannel.YAW] == RC_MID
    assert result.channels[RCChannel.ARM] == RC_MAX
    assert result.channels[RCChannel.ANGLE] == RC_MAX


def test_pitch_profile_eases_from_cruise_to_terminal_over_depth():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=15.0))

    update_controller(controller, now_s=0.0)
    controller.observe(
        estimate(4, received_at_s=2.0, depth_m=9.0),
        now_s=2.0,
        mode_selected=True,
    )
    taper_start = update_controller(controller, now_s=2.0)
    controller.observe(
        estimate(5, received_at_s=3.0, depth_m=5.0),
        now_s=3.0,
        mode_selected=True,
    )
    taper_midpoint = update_controller(controller, now_s=3.0)
    controller.observe(
        estimate(6, received_at_s=4.0, depth_m=1.0),
        now_s=4.0,
        mode_selected=True,
    )
    taper_end = update_controller(controller, now_s=4.0)

    assert taper_start.pitch_command_deg == -10.0
    assert taper_midpoint.pitch_command_deg == -7.5
    assert taper_end.pitch_command_deg == -5.0
    assert taper_end.phase == TrackerPhase.TERMINAL


def test_pitch_profile_progress_does_not_reverse_when_depth_increases():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=15.0))

    update_controller(controller, now_s=0.0)
    controller.observe(
        estimate(4, received_at_s=2.0, depth_m=5.0),
        now_s=2.0,
        mode_selected=True,
    )
    closest = update_controller(controller, now_s=2.0)
    controller.observe(
        estimate(5, received_at_s=3.0, depth_m=7.0),
        now_s=3.0,
        mode_selected=True,
    )
    noisy_increase = update_controller(controller, now_s=3.0)

    assert closest.pitch_command_deg == -7.5
    assert noisy_increase.pitch_command_deg == -7.5


def test_new_tracking_session_captures_a_fresh_initial_depth():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=15.0))
    update_controller(controller, now_s=0.0)
    controller.stop_tracking()

    acquire(controller, now_s=1.0, target=estimate(depth_m=10.0))
    update_controller(controller, now_s=1.0)
    controller.observe(
        estimate(4, received_at_s=3.0, depth_m=6.0),
        now_s=3.0,
        mode_selected=True,
    )
    result = update_controller(controller, now_s=3.0)

    assert result.pitch_command_deg == -10.0


def test_image_errors_command_bounded_yaw_and_throttle():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_x=1.0, error_y=-1.0))

    update_controller(controller, now_s=0.0)
    controller.observe(
        estimate(4, received_at_s=2.0, error_x=1.0, error_y=-1.0),
        now_s=2.0,
        mode_selected=True,
    )
    result = update_controller(controller, now_s=2.0)

    assert result.yaw_rate_dps == pytest.approx(14.55)
    assert result.vertical_speed_requested_m_s == pytest.approx(-4.85)
    assert result.vertical_speed_target_m_s == -1.0
    assert result.vertical_speed_setpoint_m_s == -1.0
    assert result.throttle_correction_rc == -20.0
    assert result.channels[RCChannel.YAW] > RC_MID
    assert result.channels[RCChannel.THROTTLE] == 1488


def test_deadband_removes_small_image_error():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_x=0.02, error_y=-0.02))

    result = update_controller(controller, now_s=0.0)

    assert result.yaw_rate_dps == 0.0
    assert result.throttle_correction_rc == 0.0


def test_vertical_speed_damping_opposes_measured_motion():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_y=0.5))

    climbing = update_controller(controller,
        now_s=0.1,
        vertical_speed_m_s=1.0,
        vertical_speed_sample_time_s=0.0,
    )
    descending = update_controller(controller,
        now_s=0.2,
        vertical_speed_m_s=-1.0,
        vertical_speed_sample_time_s=0.2,
    )

    assert climbing.vertical_speed_requested_m_s == pytest.approx(2.35)
    assert climbing.vertical_speed_target_m_s == 1.0
    assert climbing.vertical_speed_setpoint_m_s == pytest.approx(0.075)
    assert climbing.throttle_visual_correction_rc == pytest.approx(1.5)
    assert climbing.throttle_damping_correction_rc == -20.0
    assert climbing.throttle_correction_rc == pytest.approx(-18.5)
    assert climbing.drone_vertical_speed_valid
    assert descending.throttle_damping_correction_rc == 20.0
    assert descending.vertical_speed_setpoint_m_s == pytest.approx(0.15)
    assert descending.throttle_correction_rc == pytest.approx(23.0)


def test_vertical_speed_setpoint_is_capped_and_acceleration_limited():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_y=1.0))

    controller.observe(
        estimate(4, received_at_s=0.4, error_y=1.0),
        now_s=0.4,
        mode_selected=True,
    )
    first = update_controller(controller, now_s=0.4)
    controller.observe(
        estimate(5, received_at_s=0.8, error_y=1.0),
        now_s=0.8,
        mode_selected=True,
    )
    second = update_controller(controller, now_s=0.8)

    assert first.vertical_speed_requested_m_s == pytest.approx(4.85)
    assert first.vertical_speed_target_m_s == 1.0
    assert first.vertical_speed_setpoint_m_s == pytest.approx(0.3)
    assert second.vertical_speed_setpoint_m_s == pytest.approx(0.6)


def test_vertical_speed_limit_tapers_with_closest_depth():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=10.0, error_y=-1.0))

    far = update_controller(controller, now_s=0.0)
    controller.observe(
        estimate(4, received_at_s=1.0, depth_m=4.0, error_y=-1.0),
        now_s=1.0,
        mode_selected=True,
    )
    midpoint = update_controller(controller, now_s=1.0)
    controller.observe(
        estimate(5, received_at_s=2.0, depth_m=2.0, error_y=-1.0),
        now_s=2.0,
        mode_selected=True,
    )
    near = update_controller(controller, now_s=2.0)
    controller.observe(
        estimate(6, received_at_s=3.0, depth_m=5.0, error_y=-1.0),
        now_s=3.0,
        mode_selected=True,
    )
    noisy_increase = update_controller(controller, now_s=3.0)

    assert far.vertical_speed_limit_m_s == 1.0
    assert midpoint.vertical_speed_limit_m_s == pytest.approx(0.75)
    assert near.vertical_speed_limit_m_s == 0.5
    assert noisy_increase.vertical_speed_limit_m_s == 0.5


def test_vertical_speed_setpoint_brakes_faster_than_it_accelerates():
    controller = TrackerController(FakeParameters())
    acquire(
        controller,
        target=estimate(error_y=-1.0),
        vertical_speed_m_s=-1.0,
    )
    controller.observe(
        estimate(4, received_at_s=0.2, error_y=0.0),
        now_s=0.2,
        mode_selected=True,
    )

    braking = update_controller(controller, now_s=0.2)

    assert braking.vertical_speed_target_m_s == 0.0
    assert braking.vertical_speed_setpoint_m_s == pytest.approx(-0.7)


def test_vertical_speed_setpoint_reversal_brakes_to_zero_before_reversing():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_y=1.0))
    controller.observe(
        estimate(4, received_at_s=0.8, error_y=1.0),
        now_s=0.8,
        mode_selected=True,
    )
    update_controller(controller, now_s=0.8)
    controller.observe(
        estimate(5, received_at_s=1.2, error_y=-1.0),
        now_s=1.2,
        mode_selected=True,
    )

    reversing = update_controller(controller, now_s=1.2)

    assert reversing.vertical_speed_target_m_s == -1.0
    assert reversing.vertical_speed_setpoint_m_s == pytest.approx(0.0)


def test_tracking_start_requires_fresh_vertical_speed():
    controller = TrackerController(FakeParameters())
    for frame_id in range(1, 4):
        controller.observe(
            estimate(frame_id, received_at_s=1.0),
            now_s=1.0,
            mode_selected=True,
        )

    with pytest.raises(ValueError, match="fresh vertical speed"):
        controller.start_tracking(
            now_s=1.0,
            vertical_speed_m_s=0.0,
            vertical_speed_sample_time_s=0.69,
        )


def test_combined_velocity_correction_keeps_existing_output_limit():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_y=1.0), vertical_speed_m_s=-10.0)

    result = update_controller(
        controller,
        now_s=0.0,
        vertical_speed_m_s=-10.0,
        vertical_speed_sample_time_s=0.0,
    )

    assert result.vertical_speed_setpoint_m_s == -1.0
    assert result.vertical_speed_error_m_s == 9.0
    assert result.throttle_correction_rc == 100.0


@pytest.mark.parametrize(
    ("speed", "sample_time"),
    [
        (1.0, None),
        (1.0, 0.0),
        (1.0, 1.1),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
    ],
)
def test_unusable_vertical_speed_exits_tracking(speed, sample_time):
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(received_at_s=1.0, error_y=0.5), now_s=1.0)

    result = update_controller(controller,
        now_s=1.0,
        vertical_speed_m_s=speed,
        vertical_speed_sample_time_s=sample_time,
    )

    assert not result.valid
    assert controller.exit_requested
    assert not result.drone_vertical_speed_valid
    assert result.reason == "vertical speed is invalid or stale"
    assert result.throttle_visual_correction_rc == 0.0
    assert result.throttle_damping_correction_rc == 0.0
    assert result.throttle_correction_rc == 0.0


def test_stale_vertical_speed_exits_tracking():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(received_at_s=1.0, error_y=0.5), now_s=1.0)

    result = update_controller(controller,
        now_s=1.0,
        vertical_speed_m_s=1.0,
        vertical_speed_sample_time_s=0.69,
    )

    assert not result.valid
    assert controller.exit_requested
    assert not result.drone_vertical_speed_valid
    assert result.throttle_damping_correction_rc == 0.0
    assert result.throttle_correction_rc == 0.0


def test_speed_outside_cap_produces_braking_correction():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_y=1.0))

    result = update_controller(controller,
        now_s=0.0,
        vertical_speed_m_s=-2.0,
        vertical_speed_sample_time_s=0.0,
    )

    assert result.vertical_speed_requested_m_s == pytest.approx(4.85)
    assert result.vertical_speed_target_m_s == 1.0
    assert result.vertical_speed_setpoint_m_s == 0.0
    assert result.throttle_visual_correction_rc == 0.0
    assert result.throttle_damping_correction_rc == 40.0
    assert result.throttle_correction_rc == 40.0


def test_live_vertical_speed_gain_change_applies_immediately():
    parameters = FakeParameters()
    controller = TrackerController(parameters)
    acquire(controller, target=estimate(error_y=0.5))

    parameters.on_parameter_changed.emit(ParameterKey.TRK_VZ_KD, 40.0)
    result = update_controller(controller,
        now_s=0.0,
        vertical_speed_m_s=1.0,
        vertical_speed_sample_time_s=0.0,
    )

    assert result.throttle_damping_correction_rc == -40.0
    assert result.throttle_correction_rc == -40.0


def test_invalid_observation_holds_last_command_during_timeout_grace():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    previous = update_controller(controller, now_s=0.0)
    controller.observe(estimate(4, valid=False), now_s=0.1, mode_selected=True)

    result = update_controller(controller, now_s=0.1)

    assert not controller.exit_requested
    assert result is previous


def test_invalid_observation_exits_after_last_valid_estimate_times_out():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    update_controller(controller, now_s=0.0)
    controller.observe(estimate(4, valid=False), now_s=0.1, mode_selected=True)
    controller.observe(estimate(5, valid=False), now_s=0.26, mode_selected=True)

    result = update_controller(controller, now_s=0.26)

    assert controller.exit_requested
    assert not result.valid
    assert result.channels[RCChannel.PITCH] == RC_MID
    assert result.channels[RCChannel.YAW] == RC_MID
    assert result.channels[RCChannel.THROTTLE] == 1500


def test_missing_observations_exit_when_last_valid_estimate_becomes_stale():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    update_controller(controller, now_s=0.0)

    controller.observe(estimate(3), now_s=0.26, mode_selected=True)
    result = update_controller(controller, now_s=0.26)

    assert controller.exit_requested
    assert not result.valid


def test_valid_observation_resumes_pitch_ramp_without_loss_time_jump():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    update_controller(controller, now_s=0.0)
    before_loss = update_controller(controller, now_s=0.1)
    controller.observe(estimate(4, valid=False), now_s=0.15, mode_selected=True)
    assert update_controller(controller, now_s=0.2) is before_loss

    controller.observe(
        estimate(5, received_at_s=0.21),
        now_s=0.21,
        mode_selected=True,
    )
    recovered = update_controller(controller, now_s=0.21)

    assert recovered.valid
    assert recovered.pitch_command_deg == pytest.approx(-0.55)


def test_valid_observation_resumes_vertical_slew_without_loss_time_jump():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_y=1.0))
    controller.observe(
        estimate(4, received_at_s=0.1, error_y=1.0),
        now_s=0.1,
        mode_selected=True,
    )
    before_loss = update_controller(controller, now_s=0.1)
    assert before_loss.vertical_speed_setpoint_m_s == pytest.approx(0.075)

    controller.observe(estimate(5, valid=False), now_s=0.15, mode_selected=True)
    assert update_controller(controller, now_s=0.2) is before_loss
    controller.observe(
        estimate(6, received_at_s=0.21, error_y=1.0),
        now_s=0.21,
        mode_selected=True,
    )
    recovered = update_controller(controller, now_s=0.21)

    assert recovered.vertical_speed_setpoint_m_s == pytest.approx(0.0825)


def test_live_pitch_target_change_uses_same_slew_rate():
    parameters = FakeParameters()
    controller = TrackerController(parameters)
    acquire(controller)
    update_controller(controller, now_s=0.0)
    controller.observe(
        estimate(4, received_at_s=2.0), now_s=2.0, mode_selected=True
    )
    at_target = update_controller(controller, now_s=2.0)
    assert at_target.pitch_command_deg == -10.0

    parameters.on_parameter_changed.emit(ParameterKey.TRK_PITCH_DEG, -20.0)
    controller.observe(estimate(5, received_at_s=3.0), now_s=3.0, mode_selected=True)
    updated = update_controller(controller, now_s=3.0)

    assert updated.pitch_command_deg == -15.0


def test_commit_freezes_exact_command_and_times_out_to_safe_result():
    parameters = FakeParameters()
    controller = TrackerController(parameters)
    acquire(
        controller,
        target=estimate(depth_m=0.8, error_x=0.05, error_y=0.05),
    )

    terminal = update_controller(controller,
        now_s=0.0,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.0,
    )
    assert terminal.phase == TrackerPhase.TERMINAL
    controller.observe(
        estimate(4, received_at_s=0.25, depth_m=0.8, error_x=0.05, error_y=0.05),
        now_s=0.25,
        mode_selected=True,
    )
    frozen = update_controller(
        controller,
        now_s=0.25,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.25,
    )
    assert frozen.phase == TrackerPhase.COMMIT
    assert frozen.terminal_ready
    controller.observe(
        estimate(5, received_at_s=0.5, depth_m=0.5, error_x=-1.0, error_y=-1.0),
        now_s=0.5,
        mode_selected=True,
    )
    parameters.on_parameter_changed.emit(ParameterKey.TRK_PITCH_DEG, -20.0)
    parameters.on_parameter_changed.emit(ParameterKey.TRK_COMMIT_S, 0.1)

    assert (
        update_controller(controller,
            now_s=0.75,
            vertical_speed_m_s=-1.0,
            vertical_speed_sample_time_s=0.75,
        )
        is frozen
    )
    expired = update_controller(controller, now_s=1.25)
    assert not expired.valid
    assert expired.channels[RCChannel.PITCH] == RC_MID
    assert controller.exit_requested
    assert controller.completion_latched


def test_terminal_gate_resets_hold_when_alignment_becomes_unsafe():
    controller = TrackerController(FakeParameters())
    acquire(
        controller,
        target=estimate(depth_m=0.8, error_x=0.05, error_y=0.05),
    )
    first = update_controller(controller, now_s=0.0)
    assert first.phase == TrackerPhase.TERMINAL

    controller.observe(
        estimate(4, received_at_s=0.2, depth_m=0.8, error_x=0.2, error_y=0.05),
        now_s=0.2,
        mode_selected=True,
    )
    blocked = update_controller(controller, now_s=0.2)
    assert blocked.terminal_block_reason == "horizontal alignment"

    controller.observe(
        estimate(5, received_at_s=0.3, depth_m=0.8, error_x=0.05, error_y=0.05),
        now_s=0.3,
        mode_selected=True,
    )
    restarted = update_controller(controller, now_s=0.3)
    assert restarted.phase == TrackerPhase.TERMINAL
    controller.observe(
        estimate(6, received_at_s=0.55, depth_m=0.8, error_x=0.05, error_y=0.05),
        now_s=0.55,
        mode_selected=True,
    )
    ready = update_controller(controller, now_s=0.55)
    assert ready.phase == TrackerPhase.COMMIT


def test_terminal_gate_rejects_high_vertical_speed_and_times_out_safely():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=0.8))

    terminal = update_controller(controller, now_s=0.0, vertical_speed_m_s=-1.0)
    assert terminal.phase == TrackerPhase.TERMINAL
    assert terminal.terminal_block_reason == "vertical speed"
    controller.observe(
        estimate(4, received_at_s=2.0, depth_m=0.8),
        now_s=2.0,
        mode_selected=True,
    )
    timed_out = update_controller(
        controller,
        now_s=2.0,
        vertical_speed_m_s=-1.0,
    )

    assert not timed_out.valid
    assert timed_out.reason == "terminal stabilization timeout"
    assert timed_out.channels[RCChannel.PITCH] == RC_MID
    assert timed_out.channels[RCChannel.THROTTLE] == 1500
    assert controller.exit_requested


def test_completed_session_can_reacquire_while_mode_remains_selected():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=0.8))
    update_controller(controller, now_s=0.0)
    update_controller(controller, now_s=1.0)
    controller.stop_tracking()

    for frame_id in range(4, 8):
        controller.observe(
            estimate(frame_id, received_at_s=1.0),
            now_s=1.0,
            mode_selected=True,
        )
    assert controller.ready_to_track


def test_invalid_live_configuration_keeps_previous_snapshot():
    parameters = FakeParameters()
    controller = TrackerController(parameters)
    acquire(controller)
    original = update_controller(controller, now_s=0.0)

    parameters.on_parameter_changed.emit(ParameterKey.BF_ANGLE_LIMIT, 5.0)
    controller.observe(estimate(4, received_at_s=0.1), now_s=0.1, mode_selected=True)
    updated = update_controller(controller, now_s=0.1)

    assert original.pitch_command_deg == 0.0
    assert updated.pitch_command_deg == -0.5
    assert updated.channels[RCChannel.PITCH] == 1504
    assert math.isfinite(updated.pitch_command_deg)


def read_csv(path):
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_csv_is_buffered_until_track_exit_and_contains_every_update(tmp_path):
    path = tmp_path / "logs" / "tracker_controller.csv"
    controller = TrackerController(FakeParameters(), csv_path=path)
    acquire(controller)

    first = update_controller(controller,
        now_s=0.0,
        vertical_speed_m_s=0.4,
        vertical_speed_sample_time_s=0.0,
    )
    second = update_controller(controller,
        now_s=0.1,
        vertical_speed_m_s=0.4,
        vertical_speed_sample_time_s=0.0,
    )
    assert not path.exists()

    controller.stop_tracking(end_reason="manual_override")

    rows = read_csv(path)
    assert len(rows) == 2
    assert [row["sample_index"] for row in rows] == ["0", "1"]
    assert [row["time_monotonic_ns"] for row in rows] == ["0", "100000000"]
    assert [row["elapsed_s"] for row in rows] == ["0.0", "0.1"]
    assert {row["end_reason"] for row in rows} == {"manual_override"}
    assert int(rows[0]["ch2_pitch"]) == first.channels[RCChannel.PITCH]
    assert int(rows[1]["ch2_pitch"]) == second.channels[RCChannel.PITCH]
    assert rows[0]["control_vx_m_s"] == "5.0"
    assert rows[0]["trk_pitch_rate_deg_s"] == "5.0"
    assert rows[0]["drone_vertical_speed_m_s"] == "0.4"
    assert rows[0]["drone_vertical_speed_age_s"] == "0.0"
    assert rows[0]["drone_vertical_speed_valid"] == "True"
    assert rows[0]["vertical_speed_requested_m_s"] == "0.0"
    assert rows[0]["vertical_speed_limit_m_s"] == "1.0"
    assert rows[0]["vertical_speed_target_m_s"] == "0.0"
    assert rows[0]["vertical_speed_setpoint_m_s"] == "0.0"
    assert rows[0]["vertical_speed_error_m_s"] == "-0.4"
    assert rows[0]["throttle_visual_correction_rc"] == "0.0"
    assert rows[0]["throttle_damping_correction_rc"] == "-8.0"
    assert rows[0]["throttle_correction_rc"] == "-8.0"
    assert rows[0]["trk_vertical_speed_kd"] == "20.0"
    assert rows[0]["trk_vertical_speed_max_m_s"] == "1.0"
    assert rows[0]["trk_vertical_speed_accel_m_s2"] == "0.75"
    assert rows[0]["trk_vertical_speed_near_m_s"] == "0.5"
    assert rows[0]["trk_vertical_speed_taper_start_m"] == "6.0"
    assert rows[0]["trk_vertical_speed_taper_end_m"] == "2.0"
    assert rows[0]["trk_vertical_speed_brake_m_s2"] == "1.5"
    assert rows[0]["live_vertical_speed_m_s"] == "0.4"
    assert rows[0]["live_vertical_speed_valid"] == "True"


def test_csv_distinguishes_lost_observation_from_held_control_estimate(tmp_path):
    path = tmp_path / "tracker_controller.csv"
    controller = TrackerController(FakeParameters(), csv_path=path)
    acquire(controller, target=estimate(error_x=0.4, error_y=-0.2))
    update_controller(controller, now_s=0.0)
    controller.observe(estimate(4, valid=False), now_s=0.1, mode_selected=True)
    update_controller(controller, now_s=0.1)

    controller.stop_tracking(end_reason="target_lost_or_stale")

    lost = read_csv(path)[-1]
    assert lost["observed_frame_id"] == "4"
    assert lost["observed_valid"] == "False"
    assert lost["observed_reason"] == "lost"
    assert lost["observed_dx_norm"] == ""
    assert lost["control_frame_id"] == "3"
    assert lost["control_dx_norm"] == "0.4"
    assert lost["control_dy_norm"] == "-0.2"
    assert lost["result_valid"] == "True"


def test_csv_logs_live_vertical_speed_while_commit_command_is_frozen(tmp_path):
    path = tmp_path / "tracker_controller.csv"
    controller = TrackerController(FakeParameters(), csv_path=path)
    acquire(controller, target=estimate(depth_m=0.8))
    update_controller(controller, now_s=0.0, vertical_speed_m_s=0.0)
    controller.observe(
        estimate(4, received_at_s=0.25, depth_m=0.8),
        now_s=0.25,
        mode_selected=True,
    )
    frozen = update_controller(controller, now_s=0.25, vertical_speed_m_s=0.0)
    assert frozen.phase == TrackerPhase.COMMIT
    update_controller(controller, now_s=0.5, vertical_speed_m_s=-0.4)
    controller.stop_tracking(end_reason="test")

    commit_row = read_csv(path)[-1]
    assert commit_row["drone_vertical_speed_m_s"] == "0.0"
    assert commit_row["live_vertical_speed_m_s"] == "-0.4"
    assert commit_row["live_vertical_speed_valid"] == "True"


def test_new_tracking_session_overwrites_previous_csv(tmp_path):
    path = tmp_path / "tracker_controller.csv"
    controller = TrackerController(FakeParameters(), csv_path=path)
    acquire(controller)
    update_controller(controller, now_s=0.0)
    controller.stop_tracking(end_reason="first")

    acquire(controller, now_s=1.0)
    update_controller(controller, now_s=1.0)
    update_controller(controller, now_s=1.1)
    controller.stop_tracking(end_reason="second")

    rows = read_csv(path)
    assert len(rows) == 2
    assert {row["end_reason"] for row in rows} == {"second"}


def test_csv_export_error_does_not_escape_stop_tracking(tmp_path):
    controller = TrackerController(FakeParameters(), csv_path=tmp_path)
    acquire(controller)
    update_controller(controller, now_s=0.0)

    controller.stop_tracking(end_reason="tracker_disabled")

    assert not controller.exit_requested

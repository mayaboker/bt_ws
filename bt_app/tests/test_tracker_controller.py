from __future__ import annotations

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
            ParameterKey.TRK_YAW_KP: 15.0,
            ParameterKey.TRK_YAW_MAX: 20.0,
            ParameterKey.TRK_THR_KP: 100.0,
            ParameterKey.TRK_THR_MAX: 100.0,
            ParameterKey.TRK_DEADBAND: 0.03,
            ParameterKey.TRK_TIMEOUT_S: 0.25,
            ParameterKey.TRK_LOCK_FRAMES: 3,
            ParameterKey.TRK_COMMIT_M: 1.0,
            ParameterKey.TRK_COMMIT_S: 1.0,
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
    depth_m=5.0,
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


def acquire(controller, *, now_s=0.0, target=None):
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
    controller.start_tracking()


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


def test_centered_target_commands_forward_pitch_and_hover_compensation():
    controller = TrackerController(FakeParameters())
    acquire(controller)

    result = controller.update(now_s=0.0)

    assert result.valid
    assert result.phase == TrackerPhase.TRACKING
    assert len(result.channels) == 8
    assert result.channels[RCChannel.ROLL] == RC_MID
    assert result.channels[RCChannel.PITCH] == 1417
    assert result.channels[RCChannel.THROTTLE] == 1508
    assert result.channels[RCChannel.YAW] == RC_MID
    assert result.channels[RCChannel.ARM] == RC_MAX
    assert result.channels[RCChannel.ANGLE] == RC_MAX


def test_image_errors_command_bounded_yaw_and_throttle():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_x=1.0, error_y=-1.0))

    result = controller.update(now_s=0.0)

    assert result.yaw_rate_dps == pytest.approx(14.55)
    assert result.throttle_correction_rc == -97.0
    assert result.channels[RCChannel.YAW] > RC_MID
    assert result.channels[RCChannel.THROTTLE] == 1411


def test_deadband_removes_small_image_error():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(error_x=0.02, error_y=-0.02))

    result = controller.update(now_s=0.0)

    assert result.yaw_rate_dps == 0.0
    assert result.throttle_correction_rc == 0.0


def test_invalid_or_stale_observation_requests_exit_and_returns_safe_result():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    controller.observe(estimate(4, valid=False), now_s=0.1, mode_selected=True)

    result = controller.update(now_s=0.1)

    assert controller.exit_requested
    assert not result.valid
    assert result.channels[RCChannel.PITCH] == RC_MID
    assert result.channels[RCChannel.YAW] == RC_MID
    assert result.channels[RCChannel.THROTTLE] == 1500


def test_commit_freezes_exact_command_and_times_out_to_safe_result():
    parameters = FakeParameters()
    controller = TrackerController(parameters)
    acquire(
        controller,
        target=estimate(depth_m=0.8, error_x=0.2, error_y=0.1),
    )

    frozen = controller.update(now_s=0.0)
    assert frozen.phase == TrackerPhase.COMMIT
    controller.observe(
        estimate(4, received_at_s=0.2, depth_m=0.5, error_x=-1.0, error_y=-1.0),
        now_s=0.2,
        mode_selected=True,
    )
    parameters.on_parameter_changed.emit(ParameterKey.TRK_PITCH_DEG, -20.0)
    parameters.on_parameter_changed.emit(ParameterKey.TRK_COMMIT_S, 0.1)

    assert controller.update(now_s=0.5) is frozen
    expired = controller.update(now_s=1.0)
    assert not expired.valid
    assert expired.channels[RCChannel.PITCH] == RC_MID
    assert controller.exit_requested
    assert controller.completion_latched


def test_completed_session_can_reacquire_while_mode_remains_selected():
    controller = TrackerController(FakeParameters())
    acquire(controller, target=estimate(depth_m=0.8))
    controller.update(now_s=0.0)
    controller.update(now_s=1.0)
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
    original = controller.update(now_s=0.0)

    parameters.on_parameter_changed.emit(ParameterKey.BF_ANGLE_LIMIT, 5.0)
    controller.observe(estimate(4, received_at_s=0.1), now_s=0.1, mode_selected=True)
    updated = controller.update(now_s=0.1)

    assert updated.channels[RCChannel.PITCH] == original.channels[RCChannel.PITCH]
    assert math.isfinite(updated.pitch_command_deg)

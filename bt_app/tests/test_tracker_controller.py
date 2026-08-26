from __future__ import annotations

import math

import pytest
from bt_msgs import TrackerResultMessage

from bt_app.control.tracker_controller import TrackerController, TrackerPhase
from bt_app.msp.bt_v2 import RC_MID, RCChannel_alias as RCChannel
from bt_app.parameters.generated import ParameterKey
from bt_app.services import TrackerObservation


class FakeEvent:
    def __init__(self):
        self.subscribers = []

    def subscribe(self, callback):
        self.subscribers.append(callback)


class FakeParameters:
    def __init__(self):
        self.on_parameter_changed = FakeEvent()
        self.values = {
            ParameterKey.TTC_PIT_INIT: -5.0,
            ParameterKey.TTC_PIT_MIN: -15.0,
            ParameterKey.TTC_PIT_SLEW: 5.0,
            ParameterKey.TTC_PIT_REC: 25.0,
            ParameterKey.TTC_INV_KP: 8.0,
            ParameterKey.TTC_SCALE_A: 0.35,
            ParameterKey.TTC_SCALE_B: 0.08,
            ParameterKey.TTC_INV_MAX: 4.0,
            ParameterKey.TTC_LOG_MAX: 30.0,
            ParameterKey.TTC_LOCK_FR: 8,
            ParameterKey.TTC_LOCK_S: 0.2,
            ParameterKey.TTC_TIMEOUT: 0.25,
            ParameterKey.TTC_SCALE_JMP: 0.35,
            ParameterKey.TGT_HEIGHT_M: 0.5,
            ParameterKey.TTC_VY_NOM: 1.25,
            ParameterKey.TTC_VY_MIN: -5.0,
            ParameterKey.TTC_VY_MAX: 2.0,
            ParameterKey.TTC_MIN_S: 0.5,
            ParameterKey.TTC_DY_KP: 1.0,
            ParameterKey.TTC_DY_VMAX: 0.5,
            ParameterKey.TTC_DY_NEAR: 1.5,
            ParameterKey.TTC_VY_KP: 20.0,
            ParameterKey.TTC_VY_KI: 3.0,
            ParameterKey.TTC_VY_KD: 10.0,
            ParameterKey.TTC_AZ_ALPHA: 0.2,
            ParameterKey.TTC_VY_I_MAX: 40.0,
            ParameterKey.TRK_VZ_ACCEL: 0.5,
            ParameterKey.TTC_THR_MAX: 100.0,
            ParameterKey.TTC_FILL: 0.6,
            ParameterKey.TTC_CLIP_FILL: 0.8,
            ParameterKey.TTC_ALIGN: 0.15,
            ParameterKey.TTC_COMMIT_FR: 5,
            ParameterKey.TTC_ALN_PIT: -5.0,
            ParameterKey.TTC_ALN_XY: 0.25,
            ParameterKey.TTC_ALN_FR: 5,
            ParameterKey.TRK_COMMIT_S: 0.3,
            ParameterKey.TRK_YAW_KP: 15.0,
            ParameterKey.TRK_YAW_MAX: 20.0,
            ParameterKey.TRK_YAW_SLEW: 20.0,
            ParameterKey.TRK_DEADBAND: 0.03,
            ParameterKey.BF_ANGLE_LIMIT: 60.0,
            ParameterKey.HOV_BASELINE: 1660,
            ParameterKey.BF_YAW_RATE: 67.0,
            ParameterKey.CAM_WIDTH_PX: 640,
            ParameterKey.CAM_HEIGHT_PX: 480,
            ParameterKey.CAM_CX_PX: 320.0,
            ParameterKey.CAM_CY_PX: 240.0,
        }

    def get(self, key):
        return self.values[key]


def observation(frame_id: int, time_s: float, *, width=100, height=80, x=None, y=None):
    x = (640 - width) // 2 if x is None else x
    y = (480 - height) // 2 if y is None else y
    return TrackerObservation(
        TrackerResultMessage(
            tracker_id=1,
            frame_id=frame_id,
            timestamp_ns=round(time_s * 1e9),
            locked=True,
            bbox_x=x,
            bbox_y=y,
            bbox_width=width,
            bbox_height=height,
            score=1.0,
        ),
        received_at_s=time_s,
    )


def acquire(controller: TrackerController) -> float:
    for frame in range(1, 9):
        time_s = (frame - 1) * 0.04
        controller.observe(
            observation(frame, time_s),
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
    assert controller.ready_to_track
    controller.start_tracking(
        now_s=0.28,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.28,
    )
    assert controller.phase == TrackerPhase.ALIGN
    for frame in range(9, 14):
        time_s = 0.28 + (frame - 8) * 0.04
        controller.observe(
            observation(frame, time_s),
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
        controller.update(
            now_s=time_s,
            vertical_speed_m_s=0.0,
            vertical_speed_sample_time_s=time_s,
        )
    assert controller.phase == TrackerPhase.TRACKING
    return 0.48


def test_acquisition_requires_eight_distinct_frames_and_holds_on_duplicate():
    controller = TrackerController(FakeParameters())
    for frame in range(1, 8):
        time_s = (frame - 1) * 0.04
        item = observation(frame, time_s)
        controller.observe(item, now_s=time_s, mode_selected=True)
        controller.observe(item, now_s=time_s + 0.01, mode_selected=True)
        assert not controller.ready_to_track
    final = observation(8, 0.28)
    controller.observe(final, now_s=0.28, mode_selected=True)
    assert controller.ready_to_track
    controller.observe(final, now_s=0.29, mode_selected=True)
    assert controller.ready_to_track


def test_alignment_blocks_ttc_approach_until_distinct_centered_frames():
    controller = TrackerController(FakeParameters())
    for frame in range(1, 9):
        time_s = (frame - 1) * 0.04
        controller.observe(
            observation(frame, time_s),
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
    controller.start_tracking(
        now_s=0.28,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.28,
    )

    for frame in range(9, 14):
        time_s = 0.28 + (frame - 8) * 0.04
        item = observation(frame, time_s, x=30, y=30)
        controller.observe(
            item,
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
        result = controller.update(
            now_s=time_s,
            vertical_speed_m_s=0.0,
            vertical_speed_sample_time_s=time_s,
        )

    assert result.phase == TrackerPhase.ALIGN
    assert result.pitch_command_deg == pytest.approx(-5.0)
    assert result.vertical_speed_target_m_s > 0.0
    assert result.vertical_speed_setpoint_m_s > 0.0

    for frame in range(14, 18):
        time_s = 0.48 + (frame - 13) * 0.04
        item = observation(frame, time_s)
        controller.observe(
            item,
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
        result = controller.update(
            now_s=time_s,
            vertical_speed_m_s=0.0,
            vertical_speed_sample_time_s=time_s,
        )
    controller.observe(
        item,
        now_s=time_s + 0.01,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=time_s + 0.01,
    )
    duplicate_result = controller.update(
        now_s=time_s + 0.01,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=time_s + 0.01,
    )
    assert duplicate_result.phase == TrackerPhase.ALIGN

    final_time_s = 0.68
    controller.observe(
        observation(18, final_time_s),
        now_s=final_time_s,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=final_time_s,
    )
    final_result = controller.update(
        now_s=final_time_s,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=final_time_s,
    )
    assert final_result.phase == TrackerPhase.TRACKING


def test_alignment_descends_when_target_is_below_camera_center():
    controller = TrackerController(FakeParameters())
    for frame in range(1, 9):
        time_s = (frame - 1) * 0.04
        controller.observe(
            observation(frame, time_s),
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
    controller.start_tracking(
        now_s=0.28,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.28,
    )
    time_s = 0.32
    controller.observe(
        observation(9, time_s, x=30, y=380),
        now_s=time_s,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=time_s,
    )

    result = controller.update(
        now_s=time_s,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=time_s,
    )

    assert result.phase == TrackerPhase.ALIGN
    assert result.vertical_speed_target_m_s < 0.0
    assert result.vertical_speed_setpoint_m_s < 0.0
    assert result.channels[RCChannel.THROTTLE] < 1663


def test_control_uses_ttc_pitch_vertical_speed_and_yaw():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    item = observation(14, 0.52, x=300, y=200)
    controller.observe(
        item,
        now_s=0.52,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=0.52,
    )
    result = controller.update(
        now_s=0.52,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.52,
    )

    assert result.valid
    assert result.phase == TrackerPhase.TRACKING
    assert result.pitch_command_deg == pytest.approx(-5.4)
    assert result.vertical_speed_target_m_s == pytest.approx(-9.5 / 30.0)
    assert result.vertical_speed_setpoint_m_s == pytest.approx(-0.04)
    assert result.channels[RCChannel.PITCH] > RC_MID
    assert 1655 <= result.channels[RCChannel.THROTTLE] <= 1670
    assert result.channels[RCChannel.YAW] > RC_MID


def test_yaw_rate_slew_limits_initial_command_and_sign_reversal():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    right = observation(14, 0.52, x=530)
    controller.observe(
        right, now_s=0.52, mode_selected=True, altitude_m=10.0,
        vertical_speed_m_s=0.0, altitude_sample_time_s=0.52,
    )
    first = controller.update(
        now_s=0.52, vertical_speed_m_s=0.0, vertical_speed_sample_time_s=0.52
    )
    second = controller.update(
        now_s=0.54, vertical_speed_m_s=0.0, vertical_speed_sample_time_s=0.54
    )

    left = observation(15, 0.56, x=10)
    controller.observe(
        left, now_s=0.56, mode_selected=True, altitude_m=10.0,
        vertical_speed_m_s=0.0, altitude_sample_time_s=0.56,
    )
    reversing = controller.update(
        now_s=0.56, vertical_speed_m_s=0.0, vertical_speed_sample_time_s=0.56
    )

    assert first.yaw_rate_dps == pytest.approx(0.8)
    assert second.yaw_rate_dps == pytest.approx(1.2)
    assert reversing.yaw_rate_dps == pytest.approx(0.8)
    assert reversing.channels[RCChannel.YAW] > RC_MID


def test_bbox_expansion_estimates_inverse_ttc():
    params = FakeParameters()
    params.values[ParameterKey.TTC_SCALE_A] = 1.0
    params.values[ParameterKey.TTC_SCALE_B] = 1.0
    controller = TrackerController(params)
    acquire(controller)
    scale_factor = math.exp(1.5 * 0.04)
    controller.observe(
        observation(14, 0.52, width=round(100 * scale_factor), height=round(80 * scale_factor)),
        now_s=0.52,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=0.52,
    )
    result = controller.update(
        now_s=0.52,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.52,
    )
    assert result.pitch_command_deg > -5.2


def test_vertical_integral_accumulates_slowly_behind_slew_limiter():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    controller.update(
        now_s=0.50,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.50,
    )
    result = controller.update(
        now_s=0.52,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.52,
    )

    assert result.throttle_correction_rc < result.throttle_damping_correction_rc
    assert result.throttle_correction_rc > -3.0


def test_vertical_acceleration_damping_updates_only_on_new_vario_sample():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    controller.update(
        now_s=0.50,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.48,
    )
    result = controller.update(
        now_s=0.52,
        vertical_speed_m_s=-1.0,
        vertical_speed_sample_time_s=0.52,
    )

    assert result.throttle_damping_correction_rc == pytest.approx(19.2)
    assert result.throttle_correction_rc > result.throttle_damping_correction_rc


def test_stale_camera_or_vario_requests_exit():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    result = controller.update(
        now_s=0.80,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.80,
    )
    assert not result.valid
    assert controller.exit_requested
    assert controller.exit_reason == "tracker observation stale"


def test_fresh_clipped_bbox_remains_available_for_recovery_control():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    clipped = observation(14, 0.52, x=250, y=400, width=100, height=80)
    controller.observe(
        clipped,
        now_s=0.52,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=0.52,
    )

    result = controller.update(
        now_s=0.52,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.52,
    )

    assert result.valid
    assert not controller.exit_requested
    assert result.error_y < 0.0
    assert result.vertical_speed_target_m_s == pytest.approx(
        -9.5 / 29.96 - (200.0 / 240.0 - 0.03)
    )
    assert -5.3 < result.pitch_command_deg < -5.0


def test_pitch_relaxes_faster_than_forward_pitch_slew():
    params = FakeParameters()
    params.values[ParameterKey.TTC_PIT_INIT] = -15.0
    params.values[ParameterKey.TTC_INV_KP] = 0.0
    controller = TrackerController(params)
    time_s = acquire(controller)
    for frame in range(14, 65):
        time_s += 0.04
        controller.observe(
            observation(frame, time_s),
            now_s=time_s,
            mode_selected=True,
            altitude_m=10.0,
            vertical_speed_m_s=0.0,
            altitude_sample_time_s=time_s,
        )
        result = controller.update(
            now_s=time_s,
            vertical_speed_m_s=0.0,
            vertical_speed_sample_time_s=time_s,
        )
    assert result.pitch_command_deg == pytest.approx(-15.0)

    time_s += 0.04
    controller.observe(
        observation(65, time_s, y=340),
        now_s=time_s,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=time_s,
    )
    recovering = controller.update(
        now_s=time_s,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=time_s,
    )

    assert recovering.pitch_command_deg == pytest.approx(-14.0)


def test_clipped_scale_uses_counting_down_effective_ttc():
    controller = TrackerController(FakeParameters())
    acquire(controller)
    controller._filter.rate_hz = 0.2
    controller._filter.time_s = 0.50
    controller.observe(
        observation(14, 1.50, x=250, y=400, width=100, height=80),
        now_s=1.50,
        mode_selected=True,
        altitude_m=10.0,
        vertical_speed_m_s=0.0,
        altitude_sample_time_s=1.50,
    )

    result = controller.update(
        now_s=1.50,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=1.50,
    )

    assert result.vertical_speed_requested_m_s == pytest.approx(-9.5 / 4.0)
    assert controller._diagnostics.measured_ttc_s == pytest.approx(5.0)
    assert controller._diagnostics.effective_ttc_s == pytest.approx(4.0)
    assert controller._diagnostics.ttc_prediction_age_s == pytest.approx(1.0)


def test_large_clipped_bbox_enters_commit_without_fresh_ttc():
    controller = TrackerController(FakeParameters())
    time_s = acquire(controller)
    for frame in range(14, 19):
        time_s += 0.04
        controller.observe(
            observation(frame, time_s, width=600, height=390, x=0, y=90),
            now_s=time_s,
            mode_selected=True,
            altitude_m=1.0,
            vertical_speed_m_s=-1.0,
            altitude_sample_time_s=time_s,
        )
        result = controller.update(
            now_s=time_s,
            vertical_speed_m_s=-1.0,
            vertical_speed_sample_time_s=time_s,
        )

    assert result.phase == TrackerPhase.COMMIT
    assert result.terminal_ready
    assert result.terminal_block_reason is None


def test_tracking_stop_exports_ttc_diagnostics(tmp_path):
    path = tmp_path / "tracker.csv"
    controller = TrackerController(FakeParameters(), csv_path=path)
    acquire(controller)
    controller.update(
        now_s=0.49,
        vertical_speed_m_s=0.0,
        vertical_speed_sample_time_s=0.49,
    )
    controller.stop_tracking(end_reason="test complete")

    text = path.read_text(encoding="utf-8")
    assert "inverse_ttc_measured_hz" in text.splitlines()[0]
    assert "effective_ttc_s" in text.splitlines()[0]
    assert "ttc_prediction_age_s" in text.splitlines()[0]
    assert "test complete" in text.splitlines()[1]

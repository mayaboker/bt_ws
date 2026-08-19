import math

import pytest
from bt_msgs import TrackerResultMessage

from bt_app.estimators import CameraIntrinsics, PinholeDistanceEstimator
from bt_app.estimators import TargetVelocityEstimator
from bt_app.parameters import Parameters
from bt_app.services import DistanceEstimatorService


def tracker_result(
    *,
    frame_id=1,
    locked=True,
    x=304,
    y=224,
    width=32,
    height=32,
):
    return TrackerResultMessage(
        frame_id=frame_id,
        timestamp_ns=123,
        locked=locked,
        bbox_x=x if locked else 0,
        bbox_y=y if locked else 0,
        bbox_width=width if locked else 0,
        bbox_height=height if locked else 0,
    )


def make_distance_estimator():
    return PinholeDistanceEstimator(
        CameraIntrinsics(320.0, 320.0, 320.0, 240.0, 640, 480),
        target_width_m=1.0,
        target_height_m=1.0,
    )


def make_service(clock=lambda: 12.5):
    return DistanceEstimatorService(
        distance_estimator=make_distance_estimator(),
        velocity_estimator=TargetVelocityEstimator(
            target_speed_m_s=5.0,
        ),
        clock=clock,
    )


def test_centered_target_produces_depth_slant_and_forward_velocity():
    estimate = make_service().process_tracker_result(tracker_result())

    assert estimate.valid
    assert estimate.received_at_s == 12.5
    assert estimate.depth_m == pytest.approx(10.0)
    assert estimate.slant_range_m == pytest.approx(10.0)
    assert estimate.vx_m_s == pytest.approx(5.0)
    assert estimate.vy_m_s == pytest.approx(0.0)


def test_distance_estimator_uses_full_camera_ray_for_slant_range():
    result = make_distance_estimator().estimate(
        tracker_result(x=464, y=64, width=32, height=32)
    )

    assert result.depth_m == pytest.approx(10.0)
    assert result.horizontal_offset_m == pytest.approx(5.0)
    assert result.vertical_offset_m == pytest.approx(5.0)
    assert result.slant_range_m == pytest.approx(math.sqrt(150.0))


def test_velocity_has_configured_speed_and_points_toward_target():
    estimator = TargetVelocityEstimator(
        target_speed_m_s=5.0,
    )

    result = estimator.estimate(
        depth_m=1.0,
        vertical_offset_m=10.0,
    )

    assert math.hypot(result.vx_m_s, result.vy_m_s) == pytest.approx(5.0)
    assert result.vx_m_s / result.vy_m_s == pytest.approx(0.1)


def test_velocity_has_no_centering_constraint():
    estimator = TargetVelocityEstimator(
        target_speed_m_s=5.0,
    )

    result = estimator.estimate(
        depth_m=10.0,
        vertical_offset_m=0.0,
    )

    assert result.vx_m_s == pytest.approx(5.0)
    assert result.vy_m_s == 0.0


def test_invalid_tracker_result_clears_distance_and_velocity():
    service = make_service()
    assert service.process_tracker_result(tracker_result()).valid

    result = service.process_tracker_result(tracker_result(frame_id=2, locked=False))

    assert not result.valid
    assert result.reason == "tracker unlocked"
    assert result.depth_m is None
    assert result.slant_range_m is None
    assert result.vx_m_s == 0.0
    assert result.vy_m_s == 0.0
    assert service.latest_estimate == result


def test_geometry_disagreement_is_invalid():
    result = make_service().process_tracker_result(
        tracker_result(width=32, height=64)
    )

    assert not result.valid
    assert result.reason == "width/height depth disagreement"


def test_service_builds_from_application_parameters():
    service = DistanceEstimatorService.from_parameters(
        Parameters("bt_app/parameters.yaml"), clock=lambda: 1.0
    )

    result = service.process_tracker_result(tracker_result())

    assert result.valid
    assert result.depth_m == pytest.approx(10.0)


def test_invalid_camera_calibration_is_rejected():
    with pytest.raises(ValueError, match="camera cx must be inside the image"):
        PinholeDistanceEstimator(
            CameraIntrinsics(320.0, 320.0, 640.0, 240.0, 640, 480),
            target_width_m=1.0,
            target_height_m=1.0,
        )

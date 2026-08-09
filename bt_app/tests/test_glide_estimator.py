import math

import pytest

from bt_app.control.visual_range import TargetRangeEstimate
from bt_app.estimators import GlideVelocityEstimate, GlideVelocityEstimator


def target_range(
    distance_m: float | None,
    *,
    valid: bool = True,
    frame_id: int = 7,
    reason: str | None = None,
) -> TargetRangeEstimate:
    return TargetRangeEstimate(frame_id, distance_m, distance_m, valid, reason)


def test_calculates_fifteen_meter_per_second_three_four_five_vector():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=20.0)

    result = estimator.update(3.0, target_range(5.0))

    assert result.valid
    assert result.horizontal_distance_m == pytest.approx(4.0)
    assert result.vx_m_s == pytest.approx(12.0)
    assert result.vy_m_s == pytest.approx(-9.0)
    assert result.achieved_speed_m_s == pytest.approx(15.0)
    assert not result.limited
    assert result.frame_id == 7


def test_vertical_limit_scales_whole_vector_and_preserves_direction():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=3.0)

    result = estimator.update(3.0, target_range(5.0))

    assert result.valid
    assert result.limited
    assert result.vx_m_s == pytest.approx(4.0)
    assert result.vy_m_s == pytest.approx(-3.0)
    assert result.achieved_speed_m_s == pytest.approx(5.0)
    assert result.vx_m_s / abs(result.vy_m_s) == pytest.approx(4.0 / 3.0)


def test_handles_horizontal_and_vertical_paths():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=4.0)

    horizontal = estimator.update(0.0, target_range(10.0))
    assert horizontal.vx_m_s == pytest.approx(15.0)
    assert horizontal.vy_m_s == pytest.approx(0.0)
    assert not horizontal.limited

    vertical = estimator.update(10.0, target_range(10.0, frame_id=8))
    assert vertical.horizontal_distance_m == pytest.approx(0.0)
    assert vertical.vx_m_s == pytest.approx(0.0)
    assert vertical.vy_m_s == pytest.approx(-4.0)
    assert vertical.achieved_speed_m_s == pytest.approx(4.0)
    assert vertical.limited


def test_clamps_roundoff_sized_impossible_geometry():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=20.0)

    result = estimator.update(10.0, target_range(10.0 - 1e-10))

    assert result.valid
    assert result.horizontal_distance_m == 0.0
    assert result.vy_m_s == pytest.approx(-15.0)


@pytest.mark.parametrize(
    ("altitude_m", "estimate", "reason"),
    [
        (1.0, None, "range estimate unavailable"),
        (1.0, target_range(None), "range distance unavailable"),
        (1.0, target_range(2.0, valid=False, reason="target lost"), "target lost"),
        (-1.0, target_range(2.0), "negative altitude"),
        (math.nan, target_range(2.0), "non-finite altitude"),
        (1.0, target_range(math.inf), "non-finite range"),
        (1.0, target_range(0.0), "non-positive range"),
        (2.0, target_range(1.0), "range shorter than altitude"),
    ],
)
def test_invalid_runtime_input_returns_zero_request(altitude_m, estimate, reason):
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=5.0)

    result = estimator.update(altitude_m, estimate)

    assert not result.valid
    assert result.vx_m_s == 0.0
    assert result.vy_m_s == 0.0
    assert result.achieved_speed_m_s == 0.0
    assert result.reason == reason


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan])
def test_rejects_invalid_maximum_vertical_speed(value):
    with pytest.raises(ValueError, match="max_vertical_speed_m_s"):
        GlideVelocityEstimator(max_vertical_speed_m_s=value)


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan])
def test_rejects_invalid_target_speed(value):
    with pytest.raises(ValueError, match="target_speed_m_s"):
        GlideVelocityEstimator(
            max_vertical_speed_m_s=5.0,
            target_speed_m_s=value,
        )


def test_retains_latest_estimate_and_reset_clears_it():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=20.0)
    result = estimator.update(3.0, target_range(5.0))

    assert estimator.estimate is result

    reset = estimator.reset("GLIDE reset")
    assert estimator.estimate is reset
    assert not reset.valid
    assert reset.vx_m_s == 0.0
    assert reset.vy_m_s == 0.0
    assert reset.reason == "GLIDE reset"


def test_package_reexports_estimator_types():
    assert GlideVelocityEstimator.__name__ == "GlideVelocityEstimator"
    assert GlideVelocityEstimate.__name__ == "GlideVelocityEstimate"

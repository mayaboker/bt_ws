import math

import pytest

from bt_app.estimators import GlideObservation, GlideVelocityEstimator


def estimate(estimator, *, depth=4.0, vertical=3.0, error=0.0, frame=7):
    return estimator.update(
        frame_id=frame,
        depth_m=depth,
        vertical_offset_m=vertical,
        centering_error=error,
    )


def test_calculates_fifteen_meter_per_second_three_four_five_vector():
    result = estimate(GlideVelocityEstimator(max_vertical_speed_m_s=20.0))
    assert result.valid
    assert result.vx_m_s == pytest.approx(12.0)
    assert result.vy_m_s == pytest.approx(9.0)
    assert result.achieved_speed_m_s == pytest.approx(15.0)
    assert not result.vertical_limited


def test_vertical_limit_scales_whole_vector_and_preserves_direction():
    result = estimate(GlideVelocityEstimator(max_vertical_speed_m_s=3.0))
    assert result.vx_m_s == pytest.approx(4.0)
    assert result.vy_m_s == pytest.approx(3.0)
    assert result.vertical_limited
    assert result.vx_m_s / result.vy_m_s == pytest.approx(4.0 / 3.0)


def test_vertical_offset_sign_is_upward_positive():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=20.0)
    assert estimate(estimator, vertical=2.0).vy_m_s > 0
    assert estimate(estimator, vertical=-2.0, frame=8).vy_m_s < 0


def test_centering_quality_deadband_ramp_and_stop():
    estimator = GlideVelocityEstimator(
        max_vertical_speed_m_s=20.0,
        center_deadband=0.05,
        center_error_max=0.40,
    )
    assert estimator.speed_quality(0.0) == 1.0
    assert estimator.speed_quality(0.05) == 1.0
    assert estimator.speed_quality(0.225) == pytest.approx(0.5)
    assert estimator.speed_quality(0.40) == 0.0
    assert estimator.speed_quality(1.0) == 0.0
    assert estimate(estimator, vertical=0.0, error=0.40).vx_m_s == 0.0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"depth": 0.0}, "non-positive depth"),
        ({"depth": math.nan}, "non-finite vector geometry"),
        ({"vertical": math.inf}, "non-finite vector geometry"),
        ({"error": -0.1}, "negative centering error"),
    ],
)
def test_invalid_runtime_geometry_returns_zero(kwargs, reason):
    result = estimate(GlideVelocityEstimator(max_vertical_speed_m_s=3.0), **kwargs)
    assert not result.valid
    assert (result.vx_m_s, result.vy_m_s) == (0.0, 0.0)
    assert result.reason == reason


@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan])
def test_rejects_invalid_speed_limits(value):
    with pytest.raises(ValueError):
        GlideVelocityEstimator(max_vertical_speed_m_s=value)


@pytest.mark.parametrize("limits", [(-0.1, 0.4), (0.4, 0.4), (0.5, 0.4), (0.1, 1.1)])
def test_rejects_invalid_centering_limits(limits):
    with pytest.raises(ValueError, match="centering limits"):
        GlideVelocityEstimator(
            max_vertical_speed_m_s=3.0,
            center_deadband=limits[0],
            center_error_max=limits[1],
        )


def test_reset_and_public_observation_type():
    estimator = GlideVelocityEstimator(max_vertical_speed_m_s=3.0)
    estimate(estimator)
    reset = estimator.reset("lost")
    assert not reset.valid and reset.reason == "lost"
    assert GlideObservation.invalid("missing").reason == "missing"

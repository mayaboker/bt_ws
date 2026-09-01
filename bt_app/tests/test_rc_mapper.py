from __future__ import annotations

import pytest

from bt_app.control.rc_mapper import BetaflightRcMapper


def mapper(*, expo: float = 0.0) -> BetaflightRcMapper:
    return BetaflightRcMapper(
        yaw_center_sensitivity_dps=70.0,
        yaw_max_rate_dps=670.0,
        yaw_expo=expo,
    )


def test_actual_rates_match_betaflight_endpoints_and_center() -> None:
    rates = mapper()

    assert rates.yaw_norm_to_rate(0.0) == pytest.approx(0.0)
    assert rates.yaw_norm_to_rate(1.0) == pytest.approx(670.0)
    assert rates.yaw_norm_to_rate(-1.0) == pytest.approx(-670.0)


def test_fifteen_dps_uses_expected_actual_rates_rc_deflection() -> None:
    rates = mapper()

    assert rates.yaw_rate_to_rc(15.0) == 1555
    assert rates.yaw_rate_to_rc(-15.0) == 1445


@pytest.mark.parametrize("expo", [0.0, 0.35, 1.0])
@pytest.mark.parametrize("rate", [-670.0, -120.0, -15.0, 0.0, 15.0, 120.0, 670.0])
def test_actual_rates_inverse_round_trip(expo: float, rate: float) -> None:
    rates = mapper(expo=expo)

    normalized = rates.yaw_rate_to_norm(rate)

    assert rates.yaw_norm_to_rate(normalized) == pytest.approx(rate, abs=1e-8)


def test_rate_requests_are_saturated_at_full_stick() -> None:
    rates = mapper()

    assert rates.yaw_rate_to_rc(1000.0) == 2000
    assert rates.yaw_rate_to_rc(-1000.0) == 1000


@pytest.mark.parametrize(
    ("center", "maximum", "expo"),
    [(0.0, 670.0, 0.0), (100.0, 70.0, 0.0), (70.0, 670.0, -0.1), (70.0, 670.0, 1.1)],
)
def test_invalid_actual_rates_configuration_is_rejected(
    center: float, maximum: float, expo: float
) -> None:
    with pytest.raises(ValueError):
        BetaflightRcMapper(
            yaw_center_sensitivity_dps=center,
            yaw_max_rate_dps=maximum,
            yaw_expo=expo,
        )

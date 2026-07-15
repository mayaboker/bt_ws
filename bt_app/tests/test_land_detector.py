from bt_app.control import land_detector as land_detector_module
from bt_app.control.land_detector import LandDetector


def detector_with_times(monkeypatch, times):
    remaining = iter(times)
    last = {"value": times[-1]}

    def monotonic():
        try:
            last["value"] = next(remaining)
        except StopIteration:
            pass
        return last["value"]

    monkeypatch.setattr(land_detector_module.time, "monotonic", monotonic)
    return LandDetector(
        confirm_s=2.0,
        land_altitude_m=0.15,
        land_vertical_speed_m_s=0.1,
    )


def test_land_detector_requires_continuous_confirm_time(monkeypatch):
    detector = detector_with_times(monkeypatch, [0.0, 1.0, 2.1])

    assert not detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)
    assert not detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)
    assert detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)


def test_land_detector_resets_when_candidate_breaks(monkeypatch):
    detector = detector_with_times(monkeypatch, [0.0, 1.0, 2.0, 4.1])

    assert not detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)
    assert not detector.update(current_altitude=0.4, vertical_speed_m_s=0.0)
    assert not detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)
    assert detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)


def test_land_detector_requires_low_vertical_speed(monkeypatch):
    detector = detector_with_times(monkeypatch, [0.0, 3.0])

    assert not detector.update(current_altitude=0.1, vertical_speed_m_s=0.2)
    assert not detector.update(current_altitude=0.1, vertical_speed_m_s=0.0)

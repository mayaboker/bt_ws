from types import SimpleNamespace

import pytest

from bt_app.comm.visual_target import VisualDetectionMessage
from bt_app.control.visual_range import (
    CameraIntrinsics,
    TargetRangeEstimate,
    VisualRangeEstimator,
)


def detection(frame_id=1, **overrides):
    values = {
        "timestamp_ns": 0,
        "found": True,
        "x": 200,
        "y": 160,
        "width": 32,
        "height": 32,
        "locked": True,
    }
    values.update(overrides)
    return VisualDetectionMessage(frame_id=frame_id, **values)


@pytest.fixture
def estimator():
    return VisualRangeEstimator(
        CameraIntrinsics(320.0, 320.0, 320.0, 240.0, 640, 480),
        target_width_m=1.0,
        target_height_m=1.0,
    )


def test_height_based_depth_for_known_square(estimator):
    estimate = estimator.update(detection())

    assert estimate.valid
    assert estimate.raw_depth_m == pytest.approx(10.0)
    assert estimate.distance_m == pytest.approx(10.0)


def test_height_is_primary_when_dimensions_are_consistent(estimator):
    estimate = estimator.update(detection(width=30, height=32))

    assert estimate.valid
    assert estimate.raw_depth_m == pytest.approx(10.0)


def test_rejects_inconsistent_or_clipped_geometry(estimator):
    inconsistent = estimator.update(detection(width=16, height=32))
    clipped = estimator.update(detection(2, x=0))

    assert not inconsistent.valid
    assert inconsistent.reason == "width/height depth disagreement"
    assert not clipped.valid
    assert clipped.reason == "bounding box clipped by image edge"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"found": False}, "target not found"),
        ({"locked": False}, "target not locked"),
        ({"width": 0}, "non-positive bounding box"),
    ],
)
def test_rejects_untrusted_detections(estimator, overrides, reason):
    estimate = estimator.update(detection(**overrides))

    assert not estimate.valid
    assert estimate.reason == reason


def test_rolling_median_and_reset_on_loss(estimator):
    for frame_id, height_px in enumerate((32, 16, 8, 4, 2), start=1):
        estimate = estimator.update(
            detection(frame_id, width=height_px, height=height_px)
        )

    assert estimate.distance_m == pytest.approx(40.0)

    estimator.update(detection(6, found=False))
    reacquired = estimator.update(detection(7, width=64, height=64))
    assert reacquired.distance_m == pytest.approx(5.0)


def test_duplicate_frame_does_not_change_filter(estimator):
    first = estimator.update(detection(1))
    duplicate = estimator.update(detection(1, width=64, height=64))

    assert duplicate == first


def test_visual_controller_temporarily_reexports_comm_types():
    from bt_app.comm.visual_target import VisualTargetComm as MovedComm
    from bt_app.control.visual_controller import VisualTargetComm as CompatibleComm

    assert CompatibleComm is MovedComm


def test_app_publishes_filtered_range_then_nan_on_loss():
    import math

    from bt_app.app import App
    from bt_app.common.mavlink import NamedValue

    class Mavlink:
        def __init__(self):
            self.messages = []

        def send_named_value_to_gcs(self, name, value):
            self.messages.append((name, value))

    app = App.__new__(App)
    app.ctx = SimpleNamespace(target_distance_m=None)
    app.mavlink_service = Mavlink()
    valid = TargetRangeEstimate(1, 10.2, 10.0, True)
    app._update_glide_range_telemetry(SimpleNamespace(target_range=valid), 1.0)

    assert app.ctx.target_distance_m == 10.0
    assert app.mavlink_service.messages == [(NamedValue.TARGET_DISTANCE, 10.0)]

    invalid = TargetRangeEstimate(2, None, None, False, "target not found")
    app._update_glide_range_telemetry(SimpleNamespace(target_range=invalid), 1.1)

    assert app.ctx.target_distance_m is None
    name, value = app.mavlink_service.messages[-1]
    assert name == NamedValue.TARGET_DISTANCE
    assert math.isnan(value)


def test_app_rate_limits_range_mavlink_updates():
    from bt_app.app import App

    class Mavlink:
        def __init__(self):
            self.messages = []

        def send_named_value_to_gcs(self, name, value):
            self.messages.append((name, value))

    app = App.__new__(App)
    app.ctx = SimpleNamespace(target_distance_m=None)
    app.mavlink_service = Mavlink()
    for frame_id, now_s in ((1, 1.0), (2, 1.1), (3, 1.2)):
        estimate = TargetRangeEstimate(frame_id, 10.0, 10.0, True)
        app._update_glide_range_telemetry(SimpleNamespace(target_range=estimate), now_s)

    assert len(app.mavlink_service.messages) == 1


def test_glide_controller_clears_range_when_observation_is_stale(
    monkeypatch, estimator
):
    from bt_app.control.glide_controller import GlideController
    from bt_app.parameters.generated import ParameterKey

    class Event:
        def subscribe(self, _callback):
            pass

    class Parameters:
        on_parameter_changed = Event()
        values = {
            ParameterKey.GLIDE_DESC_RATE: 0.5,
            ParameterKey.GLIDE_VEL_KP: 100.0,
            ParameterKey.GLIDE_VEL_KI: 20.0,
            ParameterKey.GLIDE_FLARE_ALT: 1.0,
            ParameterKey.GLIDE_FLARE_RATE: 0.15,
            ParameterKey.GLIDE_OUT_LIMIT: 150.0,
            ParameterKey.GLIDE_LAND_ALT: 0.15,
            ParameterKey.GLIDE_LAND_VS: 0.1,
            ParameterKey.GLIDE_LAND_SEC: 1.0,
            ParameterKey.HOV_BASELINE: 1660,
        }

        def get(self, key):
            return self.values[key]

    observations = [SimpleNamespace(detection=detection()), None]
    controller = GlideController(
        Parameters(),
        visual_observation_supplier=lambda: observations.pop(0),
        visual_range_estimator=estimator,
    )
    monkeypatch.setattr("bt_app.control.glide_controller.time.monotonic", lambda: 0.0)

    controller.update(3.0, 0.0, 0.0)
    assert controller.target_distance_m == pytest.approx(10.0)
    controller.update(3.0, 0.0, 0.0)
    assert controller.target_distance_m is None
    assert controller.target_range.reason == "visual observation stale"

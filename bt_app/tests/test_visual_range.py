from types import SimpleNamespace

import pytest

from bt_app.comm.gst_bridge import VisualDetectionMessage
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
    from bt_app.comm.gst_bridge import GST_Bridge as MovedComm
    from bt_app.control.visual_controller import GST_Bridge as CompatibleComm

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
    app._update_glide_range_telemetry(SimpleNamespace(estimate=valid), 1.0)

    assert app.ctx.target_distance_m == 10.0
    assert app.mavlink_service.messages == [(NamedValue.TARGET_DISTANCE, 10.0)]

    invalid = TargetRangeEstimate(2, None, None, False, "target not found")
    app._update_glide_range_telemetry(SimpleNamespace(estimate=invalid), 1.1)

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
        app._update_glide_range_telemetry(SimpleNamespace(estimate=estimate), now_s)

    assert len(app.mavlink_service.messages) == 1


def test_app_visual_range_handler_clears_range_when_observation_is_stale(estimator):
    from bt_app.app import App
    from bt_app.estimators import GlideObservation, GlideVelocityEstimator
    from bt_app.trackers import TrackerManager

    app = App.__new__(App)
    app.config = SimpleNamespace(tracker_result_timeout_s=0.25)
    app._tracker_manager = TrackerManager()
    app._visual_range_estimator = estimator
    app._glide_velocity_estimator = GlideVelocityEstimator(
        max_vertical_speed_m_s=3.0
    )
    app._glide_observation = GlideObservation.invalid("no tracker result")
    app._glide_last_accepted_frame_id = None
    app._glide_last_accepted_timestamp_ns = None
    app._glide_cached_observation = None
    app._tracker_manager.update_tracker(
        "default", detection(x=304, y=224), received_at_s=10.0
    )

    import bt_app.app as app_module
    original = app_module.time.monotonic
    app_module.time.monotonic = lambda: 10.1
    app._visual_range_handler()
    assert estimator.estimate.distance_m == pytest.approx(10.0)
    assert app.glide_observation.valid
    assert app.glide_observation.ex == pytest.approx(0.0)
    assert app.glide_observation.ey == pytest.approx(0.0)
    assert app.glide_observation.vx_geometry_m_s == pytest.approx(15.0)

    first = app.glide_observation
    app_module.time.monotonic = lambda: 10.2
    app._visual_range_handler()
    assert app.glide_observation is not first
    assert app.glide_observation.age_s == pytest.approx(0.2)
    assert app.glide_observation.depth_m == first.depth_m

    app_module.time.monotonic = lambda: 10.3
    app._visual_range_handler()
    app_module.time.monotonic = original
    assert estimator.estimate.distance_m is None
    assert estimator.estimate.reason == "visual observation stale"
    assert not app.glide_observation.valid
    assert app.glide_observation.reason == "visual observation stale"


def test_app_rejects_non_monotonic_source_timestamp(estimator, monkeypatch):
    from bt_app.app import App
    from bt_app.estimators import GlideObservation, GlideVelocityEstimator
    from bt_app.trackers import TrackerManager

    app = App.__new__(App)
    app.config = SimpleNamespace(tracker_result_timeout_s=0.25)
    app._tracker_manager = TrackerManager()
    app._visual_range_estimator = estimator
    app._glide_velocity_estimator = GlideVelocityEstimator(max_vertical_speed_m_s=3.0)
    app._glide_observation = GlideObservation.invalid("no tracker result")
    app._glide_last_accepted_frame_id = None
    app._glide_last_accepted_timestamp_ns = None
    app._glide_cached_observation = None
    monkeypatch.setattr("bt_app.app.time.monotonic", lambda: 5.0)
    app._tracker_manager.update_tracker(
        "default", detection(1, timestamp_ns=20, x=304, y=224), received_at_s=4.9
    )
    app._visual_range_handler()
    assert app.glide_observation.valid

    app._tracker_manager.update_tracker(
        "default", detection(2, timestamp_ns=20, x=304, y=224), received_at_s=4.95
    )
    app._visual_range_handler()
    assert app.glide_observation.reason == "non-monotonic visual frame"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("glide_target_speed_m_s", float("nan")),
        ("glide_max_vertical_speed_m_s", 0.0),
        ("glide_center_deadband", -0.1),
        ("glide_center_error_max", 1.1),
    ],
)
def test_app_rejects_invalid_glide_geometry_config(field, value):
    from bt_app.app import App
    from bt_app.errors import AppStartupError
    from bt_app.vehicle_config import VehicleConfig

    app = App.__new__(App)
    app.config = VehicleConfig()
    original = getattr(app.config, field)
    setattr(app.config, field, value)

    try:
        with pytest.raises(AppStartupError):
            app._App__validate_startup_config()
    finally:
        setattr(app.config, field, original)

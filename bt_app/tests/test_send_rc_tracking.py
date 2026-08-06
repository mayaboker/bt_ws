from importlib.util import module_from_spec, spec_from_file_location
import time
from pathlib import Path
import sys

import pytest
from bt_app.visual_mavlink import encode_red_detection

EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_tracking.py"
SPEC = spec_from_file_location("send_rc_tracking", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
tracking = module_from_spec(SPEC)
sys.modules[SPEC.name] = tracking
SPEC.loader.exec_module(tracking)


def make_scenario(**overrides):
    values = {
        "destination": ("127.0.0.1", 14560),
        "parameter_destination": ("127.0.0.1", 14551),
        "listen": ("0.0.0.0", 14550),
        "rate_hz": 50.0,
        "state_timeout_s": 20.0,
        "landing_timeout_s": 120.0,
        "touchdown_altitude_m": 0.15,
        "alt_hold_duration_s": 0.0,
        "descent_throttle": 1500,
        "target_altitude_m": 4.0,
        "first_alt_hold_duration_s": 0.0,
        "manual_hold_duration_s": 0.0,
        "second_alt_hold_duration_s": 0.0,
        "descent_rate_m_s": 0.5,
        "descent_velocity_kp": 50.0,
        "descent_min_throttle": 1500,
        "descent_hover_throttle": 1660,
        "descent_max_throttle": 1800,
        "search_yaw_rc": 1750,
        "search_timeout_s": 240.0,
        "lock_dwell_s": 0.5,
        "image_width_px": 640,
        "center_tolerance_px": 60,
        "alignment_yaw_kp": 0.4,
        "alignment_yaw_min": 80,
        "alignment_yaw_limit": 100,
        "alignment_timeout_s": 10.0,
        "vision_timeout_s": 1.0,
        "search_log_rate_hz": 2.0,
        "tracking_timeout_s": 20.0,
        "settle_duration_s": 2.0,
        "parameter_timeout_s": 5.0,
    }
    values.update(overrides)
    return tracking.TrackingScenario(**values)


def test_tracker_channels_extend_rc_override_without_changing_flight_axes() -> None:
    channels = tracking.tracker_channels(
        tracking.ALT_HOLD_ARMED,
        selected=True,
        enabler=True,
    )

    assert channels[:7] == tracking.ALT_HOLD_ARMED[:7]
    assert len(channels) == 9
    assert channels[tracking.ENABLER] == tracking.RC_MAX
    assert channels[tracking.TRACKER_MODE] == tracking.RC_MAX
    assert tracking.PRE_TRACKING[tracking.ENABLER] == tracking.RC_MIN
    assert tracking.TRACKING_ENABLE[tracking.ENABLER] == tracking.RC_MAX
    assert tracking.TRACKING_DISABLED[tracking.TRACKER_MODE] == tracking.RC_MIN


def test_poc_parameters_match_tracking_contract() -> None:
    assert tracking.POC_PARAMETERS == {
        "TAKEOFF_ALT": 4.0,
        "HOV_KP": 20.0,
        "HOV_KD": 35.0,
        "HOV_OUT_LIMIT": 100.0,
        "VIS_FWD_PITCH": -5.0,
        "VIS_KP_YAW": 15.0,
        "VIS_MAX_YAW": 15.0,
    }


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [("_read_parameter", ("TAKEOFF_ALT",)), ("_set_parameter", ("TAKEOFF_ALT", 4.0))],
)
def test_parameter_transaction_keeps_ground_rc_alive(
    monkeypatch, method_name, arguments
) -> None:
    scenario = make_scenario(parameter_timeout_s=0.12, rate_hz=50.0)
    clock = [0.0]
    rc_packets = []

    class FakeMessage:
        def pack(self, _encoder):
            return b"parameter"

    class FakeEncoder:
        def param_request_read_encode(self, *_args):
            return FakeMessage()

        def param_set_encode(self, *_args):
            return FakeMessage()

    parameter_destinations = []

    class FakeSocket:
        def sendto(self, _payload, destination):
            parameter_destinations.append(destination)
            return None

    scenario._encoder = FakeEncoder()
    scenario._socket = FakeSocket()
    monkeypatch.setattr(tracking.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        tracking.time,
        "sleep",
        lambda duration: clock.__setitem__(0, clock[0] + duration),
    )
    monkeypatch.setattr(scenario, "_receive_pending", lambda: None)
    monkeypatch.setattr(scenario, "_send_rc", lambda channels: rc_packets.append(channels))

    with pytest.raises(tracking.ScenarioError, match="Timed out"):
        getattr(scenario, method_name)(*arguments)

    assert len(rc_packets) >= 5
    assert all(channels == tracking.NEUTRAL_DISARMED for channels in rc_packets)
    assert parameter_destinations
    assert all(
        destination == scenario.parameter_destination
        for destination in parameter_destinations
    )


def test_fresh_detector_lock_requires_found_locked_and_recent() -> None:
    scenario = object.__new__(tracking.TrackingScenario)
    scenario._last_detection_received_at = float("-inf")
    scenario._last_detection = None
    assert not scenario._fresh_detector_lock()

    scenario._last_detection_received_at = time.monotonic()
    scenario._last_detection = {"found": True, "locked": True}
    assert scenario._fresh_detector_lock()

    scenario._last_detection["found"] = False
    assert not scenario._fresh_detector_lock()


def visual_message(frame_id, *, system_id=None, component_id=None):
    payload = encode_red_detection(
        {
            "type": "red-detection",
            "frame_id": frame_id,
            "timestamp_ns": frame_id,
            "found": False,
            "x": 0,
            "y": 0,
            "width": 0,
            "height": 0,
            "locked": False,
            "lock_found_frames": 0,
            "lock_missing_frames": 5,
        }
    )

    class Message:
        def get_srcSystem(self):
            return tracking.APP_SYSTEM_ID if system_id is None else system_id

        def get_srcComponent(self):
            return tracking.APP_COMPONENT_ID if component_id is None else component_id

    message = Message()
    message.payload = payload
    return message


def test_preflight_requires_state_and_mavlink_detection() -> None:
    scenario = make_scenario()
    assert not scenario._preflight_ready()

    scenario.telemetry.state = tracking.STATE_IDLE
    assert not scenario._preflight_ready()

    scenario._consume_visual_mavlink(visual_message(1))
    assert scenario._preflight_ready()


def test_visual_mavlink_sequence_wrap_and_stale_restart(monkeypatch) -> None:
    scenario = make_scenario(vision_timeout_s=1.0)
    clock = [10.0]
    monkeypatch.setattr(tracking.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(scenario, "_phase", lambda *_args, **_kwargs: None)

    scenario._consume_visual_mavlink(visual_message(0xFFFFFFFE))
    scenario._consume_visual_mavlink(visual_message(1))
    assert scenario._last_detection_frame_id == 1

    scenario._consume_visual_mavlink(visual_message(0))
    assert scenario._last_detection_frame_id == 1

    clock[0] += 1.1
    scenario._consume_visual_mavlink(visual_message(0))
    assert scenario._last_detection_frame_id == 0


def test_duplicate_visual_frame_does_not_refresh_freshness(monkeypatch) -> None:
    scenario = make_scenario()
    clock = [10.0]
    monkeypatch.setattr(tracking.time, "monotonic", lambda: clock[0])

    scenario._consume_visual_mavlink(visual_message(7))
    clock[0] = 11.0
    scenario._consume_visual_mavlink(visual_message(7))

    assert scenario._last_detection_received_at == 10.0


def test_search_command_preserves_pretracking_and_commands_clockwise_yaw() -> None:
    scenario = make_scenario(search_yaw_rc=1750)

    channels = scenario._search_channels()

    assert channels[tracking.YAW] == 1750
    assert channels[tracking.ENABLER] == tracking.RC_MIN
    assert channels[tracking.TRACKER_MODE] == tracking.RC_MAX
    assert channels[tracking.THROTTLE] == tracking.ALT_HOLD_ARMED[tracking.THROTTLE]


@pytest.mark.parametrize(
    ("x", "width", "expected_error", "expected_yaw"),
    [(636, 4, 318.0, 1600), (300, 40, 0.0, 1500), (0, 20, -310.0, 1400),
     (440, 20, 130.0, 1580)],
)
def test_alignment_command_moves_target_toward_image_center(
    x, width, expected_error, expected_yaw
) -> None:
    scenario = make_scenario()
    scenario._last_detection = {"found": True, "x": x, "width": width}

    error = scenario._target_horizontal_error_px()

    assert error == expected_error
    assert scenario._alignment_channels(error)[tracking.YAW] == expected_yaw


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [(359.0, 1.0, 2.0), (1.0, 359.0, -2.0), (10.0, 20.0, 10.0)],
)
def test_wrapped_yaw_delta(previous, current, expected) -> None:
    assert tracking.TrackingScenario._wrapped_yaw_delta(previous, current) == expected


def test_measured_full_turn_without_lock_returns_no_target(monkeypatch) -> None:
    scenario = make_scenario(lock_dwell_s=0.0)
    scenario.telemetry.state = tracking.STATE_ALT_HOLD
    scenario.telemetry.armed = True
    scenario.telemetry.yaw_deg = 0.0
    scenario._last_detection = {"type": "red-detection", "found": False}
    scenario._last_detection_received_at = 0.0
    clock = [0.0]

    monkeypatch.setattr(tracking.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        tracking.time,
        "sleep",
        lambda duration: clock.__setitem__(0, clock[0] + max(duration, 0.01)),
    )
    monkeypatch.setattr(scenario, "_send_for", lambda *_args: None)
    monkeypatch.setattr(scenario, "_send_rc", lambda *_args: None)
    monkeypatch.setattr(scenario, "_ensure_search_inputs", lambda *_args: None)
    monkeypatch.setattr(scenario, "_check_search_health", lambda *_args: None)
    monkeypatch.setattr(scenario, "_log_search_progress", lambda *_args: None)

    def receive() -> None:
        scenario.telemetry.yaw_deg = (scenario.telemetry.yaw_deg + 120.0) % 360.0
        scenario.telemetry.attitude_samples += 1

    monkeypatch.setattr(scenario, "_receive_pending", receive)

    assert not scenario._search_and_enable_tracking()


def test_search_stops_and_enables_when_lock_appears(monkeypatch) -> None:
    scenario = make_scenario(lock_dwell_s=0.0)
    scenario.telemetry.state = tracking.STATE_ALT_HOLD
    scenario.telemetry.armed = True
    scenario.telemetry.yaw_deg = 0.0
    scenario._last_detection = {"type": "red-detection", "found": False}
    scenario._last_detection_received_at = time.monotonic()
    receive_count = [0]

    monkeypatch.setattr(scenario, "_send_for", lambda *_args: None)
    monkeypatch.setattr(scenario, "_send_rc", lambda *_args: None)
    monkeypatch.setattr(scenario, "_ensure_search_inputs", lambda *_args: None)
    monkeypatch.setattr(scenario, "_check_search_health", lambda *_args: None)
    monkeypatch.setattr(scenario, "_log_search_progress", lambda *_args: None)
    monkeypatch.setattr(scenario, "_settle_and_enable_lock", lambda: True)

    def receive() -> None:
        receive_count[0] += 1
        scenario.telemetry.yaw_deg += 10.0
        scenario.telemetry.attitude_samples += 1
        if receive_count[0] == 2:
            scenario._last_detection = {
                "type": "red-detection",
                "found": True,
                "locked": True,
            }
            scenario._last_detection_received_at = time.monotonic()

    monkeypatch.setattr(scenario, "_receive_pending", receive)

    assert scenario._search_and_enable_tracking()


def test_lock_drop_while_centering_resumes_search(monkeypatch) -> None:
    scenario = make_scenario()
    scenario.telemetry.state = tracking.STATE_ALT_HOLD
    scenario.telemetry.armed = True
    scenario._last_detection = {
        "frame_id": 10,
        "found": True,
        "locked": True,
        "x": 1,
        "y": 2,
        "width": 3,
        "height": 4,
    }
    scenario._last_detection_received_at = time.monotonic()

    def lose_lock(*_args) -> None:
        scenario._last_detection["found"] = False
        scenario._last_detection["locked"] = False
        scenario._last_detection_received_at = time.monotonic()

    monkeypatch.setattr(scenario, "_receive_pending", lose_lock)
    monkeypatch.setattr(scenario, "_send_rc", lambda *_args: None)
    monkeypatch.setattr(scenario, "_check_search_health", lambda *_args: None)

    assert not scenario._settle_and_enable_lock()


def test_stale_visual_telemetry_is_search_failure() -> None:
    scenario = make_scenario(vision_timeout_s=1.0)
    scenario.telemetry.state = tracking.STATE_ALT_HOLD
    scenario._last_detection_received_at = 10.0

    with pytest.raises(tracking.SearchError, match="No valid red-detection"):
        scenario._check_search_health(11.1)


def test_invalid_visual_frame_is_ignored_before_valid_detection(monkeypatch) -> None:
    scenario = make_scenario()
    monkeypatch.setattr(scenario, "_phase", lambda *_args, **_kwargs: None)

    class Message:
        def __init__(self, payload):
            self.payload = payload

        def get_srcSystem(self):
            return tracking.APP_SYSTEM_ID

        def get_srcComponent(self):
            return tracking.APP_COMPONENT_ID

    scenario._consume_visual_mavlink(Message(b"\x01\x03\x00bad"))
    scenario._consume_visual_mavlink(
        Message(
            encode_red_detection(
                {
                    "type": "red-detection",
                    "frame_id": 4,
                    "timestamp_ns": None,
                    "found": False,
                    "x": 0,
                    "y": 0,
                    "width": 0,
                    "height": 0,
                    "locked": False,
                    "lock_found_frames": 0,
                    "lock_missing_frames": 5,
                }
            )
        )
    )

    assert scenario._invalid_visual_frames == 1
    assert scenario._last_detection["frame_id"] == 4

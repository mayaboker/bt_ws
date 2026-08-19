import struct
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_takeoff_tracker.py"
SPEC = spec_from_file_location("send_rc_takeoff_tracker", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
tracker_script = module_from_spec(SPEC)
sys.modules[SPEC.name] = tracker_script
SPEC.loader.exec_module(tracker_script)


def make_scenario():
    return tracker_script.TakeoffTrackerScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=20.0,
        landing_timeout_s=60.0,
        touchdown_altitude_m=0.15,
        alt_hold_duration_s=0.0,
        descent_throttle=1600,
        tracker_entry_timeout_s=30.0,
        tracking_timeout_s=60.0,
        tracker_pulse_duration_s=0.25,
    )


class ChannelStatusMessage:
    def __init__(self, state):
        packed = struct.pack(
            tracker_script.CHANNEL_STATUS_FORMAT,
            tracker_script.CHANNEL_STATUS_VERSION,
            1,
            state,
            0,
            *([1500] * 8),
        )
        self.message_type = tracker_script.CHANNEL_STATUS_MESSAGE_TYPE
        self.payload = packed.ljust(249, b"\0")

    @staticmethod
    def get_srcSystem():
        return tracker_script.APP_SYSTEM_ID

    @staticmethod
    def get_srcComponent():
        return tracker_script.APP_COMPONENT_ID

    @staticmethod
    def get_type():
        return "V2_EXTENSION"


def test_tracking_commands_are_complete_18_channel_snapshots():
    for channels in (
        tracker_script.NEUTRAL_18,
        tracker_script.ARM_MANUAL_18,
        tracker_script.AUTO_TAKEOFF_18,
        tracker_script.ALT_HOLD_18,
        tracker_script.TRACKER_SELECTED_LOW,
        tracker_script.TRACKER_SELECTED_HIGH,
        tracker_script.MANUAL_DISARMED_18,
    ):
        assert len(channels) == 18


def test_tracker_channels_do_not_change_takeoff_controls():
    low = tracker_script.TRACKER_SELECTED_LOW
    high = tracker_script.TRACKER_SELECTED_HIGH

    assert low[:7] == tracker_script.ALT_HOLD_ARMED[:7]
    assert low[tracker_script.TRACKER_MODE] == tracker_script.TRACKER1
    assert low[tracker_script.TRACKER_ENABLE] == tracker_script.RC_MIN
    assert high[tracker_script.TRACKER_ENABLE] == tracker_script.RC_MAX


def test_mavlink_override_carries_extended_tracker_channels():
    scenario = make_scenario()

    message = scenario._encoder.rc_channels_override_encode(
        254,
        0,
        *tracker_script.TRACKER_SELECTED_HIGH,
    )

    assert message.chan8_raw == tracker_script.TRACKER1
    assert message.chan9_raw == tracker_script.RC_MAX
    assert message.chan18_raw == tracker_script.RC_MIN


def test_extended_channels_rejects_more_than_18_values():
    with pytest.raises(ValueError, match="more than 18"):
        tracker_script.extended_channels([1500] * 19)


def test_channel_status_extension_detects_track_state():
    telemetry = tracker_script.TrackerTelemetry()

    changed = telemetry.consume(ChannelStatusMessage(tracker_script.STATE_TRACK))

    assert changed
    assert telemetry.state == tracker_script.STATE_TRACK
    assert "state=TRACK" in telemetry.describe()


def test_entry_retries_direct_low_then_high_pulses(monkeypatch):
    scenario = make_scenario()
    sent_phases = []
    released = []
    results = iter([False, False, False, True])
    monkeypatch.setattr(
        scenario,
        "_send_for_or_track",
        lambda channels, duration: sent_phases.append((channels, duration))
        or next(results),
    )
    monkeypatch.setattr(scenario, "_send_rc", released.append)

    scenario._enter_tracking()

    assert [channels for channels, _duration in sent_phases] == [
        tracker_script.TRACKER_SELECTED_LOW,
        tracker_script.TRACKER_SELECTED_HIGH,
        tracker_script.TRACKER_SELECTED_LOW,
        tracker_script.TRACKER_SELECTED_HIGH,
    ]
    assert released == [tracker_script.TRACKER_SELECTED_LOW]


def test_tracker_failure_recovers_and_lands_before_propagating(monkeypatch):
    scenario = make_scenario()
    recovered = []
    landed = []
    monkeypatch.setattr(scenario, "_print_banner", lambda: None)
    monkeypatch.setattr(scenario, "_open", lambda: None)
    monkeypatch.setattr(scenario, "_cleanup", lambda: None)
    monkeypatch.setattr(scenario, "_phase", lambda _message: None)
    monkeypatch.setattr(
        scenario,
        "_wait_for_state",
        lambda channels, state, timeout: setattr(scenario.telemetry, "state", state),
    )

    def wait_for(channels, predicate, timeout, expectation):
        if expectation == "application telemetry":
            scenario.telemetry.state = tracker_script.STATE_IDLE
        elif expectation == "ALT_HOLD after tracker disable":
            recovered.append(channels)
            scenario.telemetry.state = tracker_script.STATE_ALT_HOLD

    monkeypatch.setattr(scenario, "_wait_for", wait_for)
    monkeypatch.setattr(
        scenario,
        "_enter_tracking",
        lambda: (_ for _ in ()).throw(tracker_script.ScenarioError("no target")),
    )
    monkeypatch.setattr(scenario, "_land_and_disarm", lambda: landed.append(True))

    with pytest.raises(tracker_script.ScenarioError, match="no target"):
        scenario.run()

    assert recovered == [tracker_script.ALT_HOLD_18]
    assert landed == [True]
    assert scenario._completed


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--tracker-entry-timeout", "0", "tracker timeouts"),
        ("--tracking-timeout", "0", "tracker timeouts"),
        ("--tracker-pulse-duration", "0", "pulse-duration"),
    ],
)
def test_tracker_cli_rejects_nonpositive_timing(option, value, message):
    with pytest.raises(SystemExit, match=message):
        tracker_script.main([option, value])


def test_help_contains_tracker_scenario_banner():
    assert tracker_script.SCENARIO_BANNER in tracker_script.build_parser().format_help()

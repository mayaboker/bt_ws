from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_manual_alt_hold_100.py"
SPEC = spec_from_file_location("send_rc_manual_alt_hold_100", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
manual_tracker = module_from_spec(SPEC)
sys.modules[SPEC.name] = manual_tracker
SPEC.loader.exec_module(manual_tracker)

from send_rc import PITCH, RC_MAX, RC_MID, RC_MIN, ROLL  # noqa: E402
from send_rc_takeoff_tracker import (  # noqa: E402
    INTERNAL_CHANNEL_COUNT,
    TRACKER_ENABLE,
    TRACKER_MODE,
)


def make_scenario():
    return manual_tracker.ManualClimbScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=20.0,
        landing_timeout_s=90.0,
        touchdown_altitude_m=0.15,
        alt_hold_duration_s=10.0,
        descent_throttle=1550,
    )


def test_alt_hold_dwell_selects_tracker1_without_enabling_track():
    channels = manual_tracker.TRACKER_SELECTED_LOW

    assert len(channels) == INTERNAL_CHANNEL_COUNT
    assert channels[TRACKER_MODE] == RC_MID
    assert channels[TRACKER_ENABLE] == RC_MIN
    assert channels[4] == RC_MAX


def test_manual_descent_explicitly_deselects_tracker():
    scenario = make_scenario()

    assert len(scenario.manual_descent_channels) == INTERNAL_CHANNEL_COUNT
    assert scenario.manual_descent_channels[TRACKER_MODE] == RC_MIN
    assert scenario.manual_descent_channels[TRACKER_ENABLE] == RC_MIN


def test_selector_starts_at_camera_center_with_enable_low():
    channels = manual_tracker.TRACKER_SELECTED_LOW

    assert channels[ROLL] == RC_MID
    assert channels[PITCH] == RC_MID
    assert channels[TRACKER_MODE] == RC_MID
    assert channels[TRACKER_ENABLE] == RC_MIN


def test_vertical_scan_keeps_horizontal_gate_position_and_pulses_enable():
    low = manual_tracker.tracker_selector_channels(
        roll=RC_MID,
        pitch=manual_tracker.SELECTOR_SCAN_UP_RC,
        enable_high=False,
    )
    high = manual_tracker.tracker_selector_channels(
        roll=RC_MID,
        pitch=manual_tracker.SELECTOR_SCAN_DOWN_RC,
        enable_high=True,
    )

    assert low[ROLL] == RC_MID
    assert low[PITCH] == 1613
    assert low[TRACKER_ENABLE] == RC_MIN
    assert high[ROLL] == RC_MID
    assert high[PITCH] == 1387
    assert high[TRACKER_ENABLE] == RC_MAX
    assert manual_tracker.SELECTOR_SCAN_SPEED_PX_S == 60.0
    assert manual_tracker.SELECTOR_INITIAL_SCAN_RC == manual_tracker.SELECTOR_SCAN_DOWN_RC
    assert manual_tracker.DEFAULT_SELECTOR_SWEEP_DURATION_S == 400.0 / 60.0
    assert manual_tracker.SELECTOR_SCAN_STEP_DURATION_S == 20.0 / 60.0

    stationary_high = manual_tracker.tracker_selector_channels(
        roll=RC_MID, pitch=RC_MID, enable_high=True
    )
    assert stationary_high[ROLL] == RC_MID
    assert stationary_high[PITCH] == RC_MID
    assert stationary_high[TRACKER_ENABLE] == RC_MAX


def test_cli_exposes_tracker_search_timing():
    help_text = manual_tracker.build_parser().format_help()

    assert "--tracker-entry-timeout" in help_text
    assert "--tracking-timeout" in help_text
    assert "--tracker-pulse-duration" in help_text
    assert "--selector-sweep-duration" in help_text
    assert make_scenario().tracker_pulse_duration_s == 0.4


def test_lower_half_search_leg_is_half_the_full_image_sweep():
    scenario = make_scenario()

    assert scenario.selector_sweep_duration_s / 2.0 == 200.0 / 60.0

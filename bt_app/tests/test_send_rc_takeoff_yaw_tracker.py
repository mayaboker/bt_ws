import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_takeoff_yaw_tracker.py"
SPEC = spec_from_file_location("send_rc_takeoff_yaw_tracker", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
yaw_tracker_script = module_from_spec(SPEC)
sys.modules[SPEC.name] = yaw_tracker_script
SPEC.loader.exec_module(yaw_tracker_script)


def make_scenario(*, search_yaw_rc=1900):
    return yaw_tracker_script.TakeoffYawTrackerScenario(
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
        search_yaw_rc=search_yaw_rc,
    )


def test_search_snapshots_preserve_alt_hold_and_apply_yaw():
    scenario = make_scenario(search_yaw_rc=1875)

    for channels in (scenario.search_low, scenario.search_high):
        assert len(channels) == 18
        assert channels[:3] == yaw_tracker_script.ALT_HOLD_18[:3]
        assert channels[yaw_tracker_script.YAW] == 1875
        assert channels[yaw_tracker_script.TRACKER_MODE] == yaw_tracker_script.TRACKER1
    assert scenario.search_low[yaw_tracker_script.TRACKER_ENABLE] == (
        yaw_tracker_script.RC_MIN
    )
    assert scenario.search_high[yaw_tracker_script.TRACKER_ENABLE] == (
        yaw_tracker_script.RC_MAX
    )


def test_search_retries_low_high_with_yaw_then_centers_on_track(monkeypatch):
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
        scenario.search_low,
        scenario.search_high,
        scenario.search_low,
        scenario.search_high,
    ]
    assert all(
        channels[yaw_tracker_script.YAW] == scenario.search_yaw_rc
        for channels, _duration in sent_phases
    )
    assert released == [yaw_tracker_script.TRACKER_SELECTED_LOW]
    assert released[0][yaw_tracker_script.YAW] == yaw_tracker_script.RC_MID


@pytest.mark.parametrize("value", [1500, 2001])
def test_cli_rejects_invalid_search_yaw(value):
    with pytest.raises(SystemExit, match="search-yaw-rc"):
        yaw_tracker_script.main(["--search-yaw-rc", str(value)])


def test_help_describes_yaw_search_transition():
    help_text = yaw_tracker_script.build_parser().format_help()

    assert yaw_tracker_script.SCENARIO_BANNER in help_text
    assert "--search-yaw-rc" in help_text
    assert "ALT_HOLD -> TRACK" in help_text

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_auto_roll.py"
SPEC = spec_from_file_location("send_rc_auto_roll", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
auto_roll = module_from_spec(SPEC)
sys.modules[SPEC.name] = auto_roll
SPEC.loader.exec_module(auto_roll)


def make_scenario(**overrides):
    values = {
        "destination": ("127.0.0.1", 14560),
        "listen": ("0.0.0.0", 14550),
        "rate_hz": 50.0,
        "state_timeout_s": 20.0,
        "landing_timeout_s": 120.0,
        "touchdown_altitude_m": 0.15,
        "alt_hold_duration_s": 0.0,
        "descent_throttle": 1500,
    }
    values.update(overrides)
    return auto_roll.AutoRollScenario(**values)


def test_default_roll_channels_are_conservative_and_symmetric():
    scenario = make_scenario()

    assert scenario.left_channels[auto_roll.ROLL] == 1300
    assert scenario.right_channels[auto_roll.ROLL] == 1700
    assert scenario.center_channels[auto_roll.ROLL] == 1500


def test_roll_commands_preserve_alt_hold_channels():
    scenario = make_scenario()

    for channels in (
        scenario.left_channels,
        scenario.right_channels,
        scenario.center_channels,
    ):
        assert channels[auto_roll.THROTTLE] == auto_roll.RC_MID
        assert channels[auto_roll.PITCH] == auto_roll.RC_MID
        assert channels[auto_roll.YAW] == auto_roll.RC_MID
        assert channels[auto_roll.ARM] == auto_roll.RC_MAX
        assert channels[auto_roll.MANUAL] == auto_roll.RC_MAX
        assert channels[auto_roll.AUTO_TAKEOFF] == auto_roll.RC_MIN


def test_balanced_pattern_uses_one_two_one_timing(monkeypatch):
    scenario = make_scenario(pulse_duration_s=1.25)
    phases = []
    monkeypatch.setattr(
        scenario,
        "_command_roll_phase",
        lambda label, channels, duration: phases.append(
            (label, channels[auto_roll.ROLL], duration)
        ),
    )

    scenario._run_roll_pattern()

    assert phases == [
        ("left", 1300, 1.25),
        ("right", 1700, 2.5),
        ("left recovery", 1300, 1.25),
    ]


def test_roll_safety_rejects_excessive_angle():
    scenario = make_scenario(max_roll_angle_deg=25.0)
    scenario.telemetry.state = auto_roll.STATE_ALT_HOLD
    scenario.telemetry.roll_deg = 26.0

    with pytest.raises(auto_roll.ScenarioError, match="Roll safety limit"):
        scenario._check_roll_safety("test")


def test_roll_safety_rejects_altitude_drift():
    scenario = make_scenario(max_altitude_drift_m=1.0)
    scenario.telemetry.state = auto_roll.STATE_ALT_HOLD
    scenario.telemetry.roll_deg = 0.0
    scenario._maneuver_start_altitude_m = 2.0
    scenario.telemetry.altitude_m = 3.1

    with pytest.raises(auto_roll.ScenarioError, match="Altitude drift safety"):
        scenario._check_roll_safety("test")


def test_recovery_requires_three_fresh_settled_attitude_samples(monkeypatch):
    scenario = make_scenario()
    scenario.telemetry.state = auto_roll.STATE_ALT_HOLD
    scenario.telemetry.roll_deg = 1.0
    scenario.telemetry.pitch_deg = -1.0
    scenario.telemetry.vertical_speed_m_s = 0.1
    scenario.telemetry.altitude_m = 2.0
    scenario._maneuver_start_altitude_m = 2.0
    results = []

    def wait_for(_channels, predicate, _timeout, _expectation):
        for _index in range(3):
            scenario.telemetry.attitude_samples += 1
            results.append(predicate())

    monkeypatch.setattr(scenario, "_wait_for", wait_for)

    scenario._wait_for_roll_recovery()

    assert results == [False, False, True]

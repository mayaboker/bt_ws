from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_auto_pitch.py"
SPEC = spec_from_file_location("send_rc_auto_pitch", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
auto_pitch = module_from_spec(SPEC)
sys.modules[SPEC.name] = auto_pitch
SPEC.loader.exec_module(auto_pitch)


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
    return auto_pitch.AutoPitchScenario(**values)


def test_default_pitch_channels_are_strong_and_symmetric():
    scenario = make_scenario()

    assert scenario.forward_channels[auto_pitch.PITCH] == 1400
    assert scenario.backward_channels[auto_pitch.PITCH] == 1600
    assert scenario.center_channels[auto_pitch.PITCH] == 1500


def test_pitch_commands_preserve_alt_hold_channels():
    scenario = make_scenario()

    for channels in (
        scenario.forward_channels,
        scenario.backward_channels,
        scenario.center_channels,
    ):
        assert channels[auto_pitch.THROTTLE] == auto_pitch.RC_MID
        assert channels[auto_pitch.ROLL] == auto_pitch.RC_MID
        assert channels[auto_pitch.YAW] == auto_pitch.RC_MID
        assert channels[auto_pitch.ARM] == auto_pitch.RC_MAX
        assert channels[auto_pitch.MANUAL] == auto_pitch.RC_MAX
        assert channels[auto_pitch.AUTO_TAKEOFF] == auto_pitch.RC_MIN


def test_smooth_pitch_pattern_hits_balanced_knots():
    scenario = make_scenario(pulse_duration_s=2.0)

    assert scenario._pitch_command_at(0.0) == 1500
    assert scenario._pitch_command_at(2.0) == 1400
    assert scenario._pitch_command_at(4.0) == 1500
    assert scenario._pitch_command_at(8.0) == 1600
    assert scenario._pitch_command_at(12.0) == 1500
    assert scenario._pitch_command_at(14.0) == 1400
    assert scenario._pitch_command_at(16.0) == 1500


def test_smooth_pitch_commands_stay_inside_joystick_limit():
    scenario = make_scenario(pulse_duration_s=2.0)

    commands = [scenario._pitch_command_at(index / 10) for index in range(161)]

    assert min(commands) == 1400
    assert max(commands) == 1600


def test_pitch_amplitude_above_safe_joystick_limit_is_rejected():
    with pytest.raises(ValueError, match="between 1 and 100"):
        make_scenario(pitch_amplitude=101)


def test_pitch_safety_rejects_excessive_angle():
    scenario = make_scenario(max_pitch_angle_deg=25.0)
    scenario.telemetry.state = auto_pitch.STATE_ALT_HOLD
    scenario.telemetry.pitch_deg = -26.0

    with pytest.raises(auto_pitch.ScenarioError, match="Pitch safety limit"):
        scenario._check_pitch_safety("test")


def test_pitch_safety_rejects_altitude_drift():
    scenario = make_scenario(max_altitude_drift_m=1.0)
    scenario.telemetry.state = auto_pitch.STATE_ALT_HOLD
    scenario.telemetry.pitch_deg = 0.0
    scenario._maneuver_start_altitude_m = 2.0
    scenario.telemetry.altitude_m = 0.9

    with pytest.raises(auto_pitch.ScenarioError, match="Altitude drift safety"):
        scenario._check_pitch_safety("test")


def test_pitch_recovery_requires_three_fresh_settled_samples(monkeypatch):
    scenario = make_scenario()
    scenario.telemetry.state = auto_pitch.STATE_ALT_HOLD
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

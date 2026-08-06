from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest

EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_auto_pitch_hold.py"
SPEC = spec_from_file_location("send_rc_auto_pitch_hold", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
pitch_hold = module_from_spec(SPEC)
sys.modules[SPEC.name] = pitch_hold
SPEC.loader.exec_module(pitch_hold)


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
    return pitch_hold.ForwardPitchHoldScenario(**values)


def test_feedback_command_is_aggressive_then_relaxes_near_target():
    scenario = make_scenario()

    assert scenario._pitch_rc_for_attitude(0.0) == 1360
    assert scenario._pitch_rc_for_attitude(-10.0) == 1400
    assert scenario._pitch_rc_for_attitude(-20.0) == 1440


def test_feedback_command_never_requests_backward_pitch():
    scenario = make_scenario()
    commands = [scenario._pitch_rc_for_attitude(angle) for angle in range(-30, 31)]

    assert min(commands) == 1300
    assert max(commands) <= pitch_hold.RC_MID


def test_pitch_channels_leave_alt_hold_throttle_centered():
    channels = pitch_hold.alt_hold_pitch_channels(1360)

    assert channels[pitch_hold.PITCH] == 1360
    assert channels[2] == pitch_hold.RC_MID


def test_forward_target_must_be_negative():
    with pytest.raises(ValueError, match="negative"):
        make_scenario(target_pitch_deg=10.0)


def test_help_contains_runtime_banner(capsys):
    assert pitch_hold.SCENARIO_BANNER in pitch_hold.build_parser().format_help()
    scenario = make_scenario()
    scenario._print_banner()
    output = capsys.readouterr().out
    assert pitch_hold.SCENARIO_BANNER in output
    assert "Diagnostic CSV:" in output


def test_csv_snapshot_contains_altitude_and_pitch_diagnostics(tmp_path):
    scenario = make_scenario(output_path=tmp_path / "pitch.csv")
    scenario.telemetry.state = pitch_hold.STATE_ALT_HOLD
    scenario.telemetry.armed = True
    scenario.telemetry.altitude_setpoint_m = 10.0
    scenario.telemetry.altitude_m = 9.8
    scenario.telemetry.vertical_speed_m_s = 0.1
    scenario.telemetry.pitch_deg = -8.0
    scenario.telemetry.output_channels = (1500, 1390, 1660, 1500, 2000, 2000, 1000, 1000)
    scenario._requested_channels = pitch_hold.alt_hold_pitch_channels(1360)

    scenario._open_recording()
    scenario._write_snapshot("ATTITUDE")
    scenario._close_recording()

    contents = scenario.output_path.read_text()
    assert "altitude_error_m" in contents
    assert "pitch_error_deg" in contents
    assert "9.8" in contents
    assert "-8.0" in contents
    assert "1360" in contents

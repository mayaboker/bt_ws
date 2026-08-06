from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_auto_yaw.py"
SPEC = spec_from_file_location("send_rc_auto_yaw", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
auto_yaw = module_from_spec(SPEC)
sys.modules[SPEC.name] = auto_yaw
SPEC.loader.exec_module(auto_yaw)

from send_rc import ARM, MANUAL, RC_MAX, RC_MID, RC_MIN, THROTTLE, YAW  # noqa: E402


def test_help_and_runtime_use_the_same_scenario_banner(capsys):
    help_text = auto_yaw.build_parser().format_help()

    auto_yaw.AutoYawScenario._print_banner()

    assert auto_yaw.SCENARIO_BANNER in help_text
    assert capsys.readouterr().out.rstrip() == auto_yaw.SCENARIO_BANNER


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
    return auto_yaw.AutoYawScenario(**values)


def test_default_turns_are_full_cw_and_ccw_rotations():
    scenario = make_scenario()

    assert scenario.turn_angle_deg == 360.0
    assert scenario.yaw_rate_dps == 10.0
    assert scenario.turn_duration_s == 36.0
    assert scenario.cw_channels[YAW] == 1900
    assert scenario.ccw_channels[YAW] == 1100


def test_yaw_commands_preserve_alt_hold_channel_pattern():
    scenario = make_scenario()

    for channels in (scenario.cw_channels, scenario.ccw_channels):
        assert channels[THROTTLE] == RC_MID
        assert channels[ARM] == RC_MAX
        assert channels[MANUAL] == RC_MAX


def test_cw_direction_can_be_inverted():
    scenario = make_scenario(cw_yaw_rc=RC_MIN)

    assert scenario.cw_channels[YAW] == RC_MIN
    assert scenario.ccw_channels[YAW] == RC_MAX


def test_turn_helper_uses_calculated_duration(monkeypatch):
    scenario = make_scenario(turn_angle_deg=180.0, yaw_rate_dps=60.0)
    sent = []
    ticks = iter(index / 100 for index in range(100))
    monkeypatch.setattr(auto_yaw.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(auto_yaw.time, "sleep", lambda _duration: None)
    monkeypatch.setattr(
        scenario,
        "_send_rc",
        lambda channels: sent.append(channels),
    )
    scenario.telemetry.state = auto_yaw.STATE_ALT_HOLD
    scenario.telemetry.yaw_deg = 0.0

    def receive():
        scenario.telemetry.attitude_samples += 1
        scenario.telemetry.yaw_deg = (
            scenario.telemetry.yaw_deg + 90.0
        ) % 360.0

    monkeypatch.setattr(scenario, "_receive_pending", receive)

    scenario._command_turn("clockwise", scenario.cw_channels)

    assert sent
    assert all(channels == scenario.cw_channels for channels in sent)


def test_attitude_telemetry_decodes_degrees():
    class AttitudeMessage:
        roll = 0.1
        pitch = -0.2
        yaw = 1.0

        def get_srcSystem(self):
            return 1

        def get_srcComponent(self):
            return 1

        def get_type(self):
            return "ATTITUDE"

    telemetry = auto_yaw.YawTelemetry()

    assert telemetry.consume(AttitudeMessage()) is True
    assert telemetry.roll_deg == pytest.approx(5.73, abs=0.01)
    assert telemetry.pitch_deg == pytest.approx(-11.46, abs=0.01)
    assert telemetry.yaw_deg == pytest.approx(57.30, abs=0.01)


def test_alt_hold_settle_requires_three_fresh_low_speed_samples(monkeypatch):
    scenario = make_scenario()
    scenario.telemetry.altitude_m = 2.0
    scenario.telemetry.vertical_speed_m_s = 0.1
    predicate_results = []

    def wait_for(_channels, predicate, _timeout, _expectation):
        for _index in range(3):
            scenario.telemetry.altitude_samples += 1
            predicate_results.append(predicate())

    monkeypatch.setattr(scenario, "_wait_for", wait_for)

    scenario._wait_for_settled_alt_hold()

    assert predicate_results == [False, False, True]

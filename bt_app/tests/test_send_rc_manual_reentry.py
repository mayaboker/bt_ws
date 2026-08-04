from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_manual_reentry.py"
SPEC = spec_from_file_location("send_rc_manual_reentry", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
manual_reentry = module_from_spec(SPEC)
sys.modules[SPEC.name] = manual_reentry
SPEC.loader.exec_module(manual_reentry)

from send_rc import ARM, MANUAL, RC_MAX, RC_MIN, THROTTLE  # noqa: E402


def make_scenario(**overrides):
    values = {
        "destination": ("127.0.0.1", 14560),
        "listen": ("0.0.0.0", 14550),
        "rate_hz": 50.0,
        "state_timeout_s": 20.0,
        "landing_timeout_s": 120.0,
        "touchdown_altitude_m": 0.15,
        "alt_hold_duration_s": 10.0,
        "descent_throttle": 1550,
    }
    values.update(overrides)
    return manual_reentry.ManualReentryScenario(**values)


def test_reentry_defaults_match_requested_sequence():
    scenario = make_scenario()

    assert scenario.target_altitude_m == 3.0
    assert scenario.first_alt_hold_duration_s == 10.0
    assert scenario.manual_hold_duration_s == 10.0
    assert scenario.manual_hold_channels[THROTTLE] == 1660
    assert scenario.second_alt_hold_duration_s == 30.0
    assert scenario.descent_rate_m_s == 1.0
    assert scenario.descent_velocity_kp == 50.0
    assert scenario.descent_max_throttle == 1800


def test_manual_hold_command_remains_armed_and_manual():
    scenario = make_scenario(manual_hold_throttle=1650)

    assert scenario.manual_hold_channels[THROTTLE] == 1650
    assert scenario.manual_hold_channels[ARM] == RC_MAX
    assert scenario.manual_hold_channels[MANUAL] == RC_MIN


def test_alt_hold_helper_uses_requested_duration(monkeypatch):
    scenario = make_scenario()
    state_waits = []
    sends = []
    monkeypatch.setattr(
        scenario,
        "_wait_for_state",
        lambda channels, state, timeout: state_waits.append(
            (channels, state, timeout)
        ),
    )
    monkeypatch.setattr(
        scenario,
        "_send_for",
        lambda channels, duration: sends.append((channels, duration)),
    )
    scenario.telemetry.state = manual_reentry.STATE_ALT_HOLD

    scenario._enter_and_hold_altitude(30.0, "second")

    assert len(state_waits) == 1
    assert sends[0][1] == 30.0


def test_descent_controller_targets_negative_one_metre_per_second():
    scenario = make_scenario()

    initial = scenario._descent_channels(None)[THROTTLE]
    too_slow = scenario._descent_channels(-0.25)[THROTTLE]
    on_target = scenario._descent_channels(-1.0)[THROTTLE]
    too_fast = scenario._descent_channels(-2.0)[THROTTLE]
    extreme_descent = scenario._descent_channels(-10.0)[THROTTLE]

    assert initial == 1610
    assert too_slow < on_target
    assert on_target == 1660
    assert too_fast == 1710
    assert extreme_descent == 1800
    assert scenario.descent_min_throttle <= too_slow <= scenario.descent_max_throttle


def test_descent_telemetry_derives_upward_positive_vertical_speed(monkeypatch):
    class PositionMessage:
        def __init__(self, altitude_m):
            self.relative_alt = int(altitude_m * 1000)

        def get_srcSystem(self):
            return 1

        def get_srcComponent(self):
            return 1

        def get_type(self):
            return "GLOBAL_POSITION_INT"

    times = iter([10.0, 10.5])
    monkeypatch.setattr(manual_reentry.time, "monotonic", lambda: next(times))
    telemetry = manual_reentry.DescentTelemetry()

    telemetry.consume(PositionMessage(3.0))
    telemetry.consume(PositionMessage(2.5))

    assert telemetry.vertical_speed_m_s == -1.0

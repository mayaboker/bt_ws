from importlib.util import module_from_spec, spec_from_file_location
from itertools import count
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_manual_alt_hold.py"
SPEC = spec_from_file_location("send_rc_manual_alt_hold", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
manual_sitl = module_from_spec(SPEC)
sys.modules[SPEC.name] = manual_sitl
SPEC.loader.exec_module(manual_sitl)

from send_rc import (  # noqa: E402
    ALT_HOLD_ARMED,
    ARM,
    MANUAL,
    RC_MAX,
    RC_MID,
    RC_MIN,
    THROTTLE,
)
from bt_app.common import InternalJoystick, RobotState  # noqa: E402
from bt_app.context import Context  # noqa: E402
from bt_app.sm import Robot_StateMachine  # noqa: E402
from bt_app.vehicle_config import VehicleConfig  # noqa: E402


def test_help_and_runtime_use_the_same_scenario_banner(capsys):
    help_text = manual_sitl.build_parser().format_help()

    manual_sitl.ManualClimbScenario._print_banner()

    assert manual_sitl.SCENARIO_BANNER in help_text
    assert capsys.readouterr().out.rstrip() == manual_sitl.SCENARIO_BANNER


def make_scenario(**overrides):
    values = {
        "destination": ("127.0.0.1", 14560),
        "listen": ("0.0.0.0", 14550),
        "rate_hz": 50.0,
        "state_timeout_s": 20.0,
        "landing_timeout_s": 90.0,
        "touchdown_altitude_m": 0.15,
        "alt_hold_duration_s": 10.0,
        "descent_throttle": 1550,
    }
    values.update(overrides)
    return manual_sitl.ManualClimbScenario(**values)


def test_manual_climb_defaults_match_requested_flight():
    scenario = make_scenario()

    assert scenario.target_altitude_m == 3.0
    assert scenario.alt_hold_duration_s == 10.0
    assert scenario.ascent_start_throttle == 1500
    assert scenario.ascent_max_throttle == 1680
    assert scenario.ascent_ramp_pwm_s == 10.0


def test_climb_increases_manual_throttle_until_target(monkeypatch):
    scenario = make_scenario(
        rate_hz=1.0,
        ascent_start_throttle=1500,
        ascent_max_throttle=1700,
        ascent_ramp_pwm_s=50.0,
    )
    ticks = count(0.0, 0.25)
    monkeypatch.setattr(manual_sitl.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(manual_sitl.time, "sleep", lambda _duration: None)
    sent = []
    monkeypatch.setattr(scenario, "_send_rc", lambda channels: sent.append(channels))

    def receive():
        scenario.telemetry.altitude_m = float(len(sent))

    monkeypatch.setattr(scenario, "_receive_pending", receive)
    scenario._climb_to_target()

    throttles = [channels[THROTTLE] for channels in sent]
    assert throttles == sorted(throttles)
    assert throttles[0] >= 1500
    assert throttles[-1] > throttles[0]
    assert all(channels[ARM] == RC_MAX for channels in sent)
    assert all(channels[MANUAL] == RC_MIN for channels in sent)


def test_descent_configuration_remains_manual_and_armed():
    scenario = make_scenario(descent_throttle=1540)

    assert scenario.manual_descent_channels[THROTTLE] == 1540
    assert scenario.manual_descent_channels[ARM] == RC_MAX
    assert scenario.manual_descent_channels[MANUAL] == RC_MIN


def test_alt_hold_request_uses_centered_throttle():
    assert ALT_HOLD_ARMED[THROTTLE] == RC_MID
    assert ALT_HOLD_ARMED[MANUAL] == RC_MAX
    assert ALT_HOLD_ARMED[ARM] == RC_MAX


def test_centered_alt_hold_request_passes_manual_transition_guard():
    ctx = Context()
    ctx.state = RobotState.MANUAL
    ctx.armed = True
    ctx.joy_fail_safe = False
    ctx.request_rc = InternalJoystick(*ALT_HOLD_ARMED)
    machine = Robot_StateMachine(ctx, VehicleConfig())
    machine.machine.set_state(RobotState.MANUAL)

    machine.resolve()

    assert ctx.request_rc.throttle > 1050
    assert ctx.state == RobotState.ALT_HOLD

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_glide.py"
SPEC = spec_from_file_location("send_rc_glide", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
glide = module_from_spec(SPEC)
sys.modules[SPEC.name] = glide
SPEC.loader.exec_module(glide)


def test_glide_request_reuses_takeoff_switch_with_centered_throttle():
    channels = glide.GLIDE_REQUEST_ARMED

    assert channels[glide.AUTO_TAKEOFF] == glide.RC_MAX
    assert channels[2] == 1500
    assert channels[4] == glide.RC_MAX


def test_glide_diagnostic_has_dedicated_parameters():
    assert "GLIDE_DESC_RATE" in glide.GlideDiagnosticScenario.PARAMETERS
    assert "GLIDE_VEL_KP" in glide.GlideDiagnosticScenario.PARAMETERS
    assert "GLIDE_FLARE_RATE" in glide.GlideDiagnosticScenario.PARAMETERS
    assert "GLIDE_OUT_LIMIT" in glide.GlideDiagnosticScenario.FIELDNAMES


def test_glide_requests_twenty_meter_takeoff_altitude():
    assert glide.REQUEST_TAKEOFF_ALT_M == 20.0


def test_takeoff_altitude_restore_only_clears_saved_value_after_success(
    monkeypatch, tmp_path
):
    scenario = glide.GlideDiagnosticScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=20.0,
        landing_timeout_s=120.0,
        touchdown_altitude_m=0.15,
        alt_hold_duration_s=0.0,
        descent_throttle=1600,
        output_path=tmp_path / "glide.csv",
        parameter_destination=("127.0.0.1", 14551),
        parameter_timeout_s=1.0,
    )
    scenario._original_takeoff_alt = 4.0
    calls = []
    monkeypatch.setattr(
        scenario, "_set_parameter", lambda name, value: calls.append((name, value))
    )
    monkeypatch.setattr(scenario, "_set_phase", lambda *_args, **_kwargs: None)

    scenario._restore_takeoff_alt()

    assert calls == [("TAKEOFF_ALT", 4.0)]
    assert scenario._original_takeoff_alt is None


def test_help_uses_glide_banner():
    assert glide.SCENARIO_BANNER in glide.build_parser().format_help()


def test_glide_snapshot_logs_vertical_speed(monkeypatch, tmp_path):
    scenario = glide.GlideDiagnosticScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=20.0,
        landing_timeout_s=120.0,
        touchdown_altitude_m=0.15,
        alt_hold_duration_s=0.0,
        descent_throttle=1600,
        output_path=tmp_path / "glide.csv",
        parameter_destination=("127.0.0.1", 14551),
        parameter_timeout_s=1.0,
    )
    scenario.telemetry.state = glide.STATE_GLIDE
    scenario.telemetry.vertical_speed_setpoint_m_s = -0.5
    scenario.telemetry.altitude_m = 4.7
    scenario.telemetry.vertical_speed_m_s = -0.5
    scenario.telemetry.output_channels = (1500, 1500, 1600, 1500, 2000, 2000, 1000, 1000)
    scenario.parameter_values["HOV_BASELINE"] = 1660
    messages = []
    monkeypatch.setattr(scenario, "_phase", lambda message, **_: messages.append(message))
    monkeypatch.setattr(glide.time, "monotonic", lambda: 10.0)

    scenario._write_snapshot("GLOBAL_POSITION_INT")

    assert any("vertical_speed=-0.50 m/s" in message for message in messages)
    assert any("velocity_setpoint=-0.50 m/s" in message for message in messages)
    assert any("correction=-60 PWM" in message for message in messages)

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "example" / "send_rc.py"
SPEC = spec_from_file_location("send_rc_sitl", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
send_rc_sitl = module_from_spec(SPEC)
sys.modules[SPEC.name] = send_rc_sitl
SPEC.loader.exec_module(send_rc_sitl)

from send_rc_sitl import (  # noqa: E402
    ARM,
    ARM_IN_MANUAL,
    ALT_HOLD_ARMED,
    AUTO_TAKEOFF,
    AUTO_TAKEOFF_ARMED,
    MANUAL,
    MANUAL_DESCENT_ARMED,
    MANUAL_DISARMED,
    MavlinkRcScenario,
    NEUTRAL_DISARMED,
    RC_MAX,
    RC_MIN,
    SCENARIO_BANNER,
    STATE_ALT_HOLD,
    ScenarioError,
    Telemetry,
)
from pymavlink import mavutil  # noqa: E402


def test_help_and_runtime_use_the_same_scenario_banner(capsys):
    help_text = send_rc_sitl.build_parser().format_help()

    MavlinkRcScenario._print_banner()

    assert SCENARIO_BANNER in help_text
    assert capsys.readouterr().out.rstrip() == SCENARIO_BANNER


def wire_message(encoder, message):
    parser = mavutil.mavlink.MAVLink(None)
    decoded = None
    for byte in message.pack(encoder):
        candidate = parser.parse_char(bytes([byte]))
        if candidate is not None:
            decoded = candidate
    assert decoded is not None
    return decoded


def test_auto_takeoff_channels_arm_with_low_throttle():
    assert AUTO_TAKEOFF_ARMED[2] == RC_MIN
    assert AUTO_TAKEOFF_ARMED[ARM] == RC_MAX
    assert AUTO_TAKEOFF_ARMED[MANUAL] == RC_MAX
    assert AUTO_TAKEOFF_ARMED[AUTO_TAKEOFF] == RC_MAX


def test_arm_stage_requests_manual_before_takeoff():
    assert ARM_IN_MANUAL[2] == RC_MIN
    assert ARM_IN_MANUAL[ARM] == RC_MAX
    assert ARM_IN_MANUAL[MANUAL] == RC_MIN
    assert ARM_IN_MANUAL[AUTO_TAKEOFF] == RC_MIN


def test_manual_descent_stays_armed_and_releases_takeoff():
    assert MANUAL_DESCENT_ARMED[2] == 1600
    assert MANUAL_DESCENT_ARMED[ARM] == RC_MAX
    assert MANUAL_DESCENT_ARMED[MANUAL] == RC_MIN
    assert MANUAL_DESCENT_ARMED[AUTO_TAKEOFF] == RC_MIN
    assert MANUAL_DISARMED[ARM] == RC_MIN


def test_alt_hold_dwell_releases_mode_requests_and_stays_armed():
    assert ALT_HOLD_ARMED[2] == 1500
    assert ALT_HOLD_ARMED[ARM] == RC_MAX
    assert ALT_HOLD_ARMED[MANUAL] == RC_MAX
    assert ALT_HOLD_ARMED[AUTO_TAKEOFF] == RC_MIN


def test_telemetry_filters_listener_heartbeat_and_decodes_app_state():
    telemetry = Telemetry()
    listener = mavutil.mavlink.MAVLink(None, srcSystem=254, srcComponent=0)
    app = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)

    ignored = wire_message(listener, listener.heartbeat_encode(6, 8, 0, 0, 4))
    heartbeat = wire_message(
        app,
        app.heartbeat_encode(
            0,
            0,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
            | mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
            STATE_ALT_HOLD,
            mavutil.mavlink.MAV_STATE_ACTIVE,
        ),
    )

    assert telemetry.consume(ignored) is False
    assert telemetry.state is None
    assert telemetry.consume(heartbeat) is True
    assert telemetry.state == STATE_ALT_HOLD
    assert telemetry.armed is True


def test_telemetry_decodes_relative_altitude_in_metres():
    telemetry = Telemetry()
    app = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    position = wire_message(
        app,
        app.global_position_int_encode(
            0, 0, 0, 2200, 1750, 0, 0, 0, 65535
        ),
    )

    assert telemetry.consume(position) is True
    assert telemetry.altitude_m == 1.75
    assert telemetry.altitude_samples == 1

    assert telemetry.consume(position) is False
    assert telemetry.altitude_samples == 2


def test_wait_timeout_reports_last_telemetry(monkeypatch):
    scenario = MavlinkRcScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=1.0,
        landing_timeout_s=1.0,
        touchdown_altitude_m=0.15,
    )
    ticks = iter(index / 10 for index in range(100))
    monkeypatch.setattr(send_rc_sitl.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(send_rc_sitl.time, "sleep", lambda _duration: None)
    monkeypatch.setattr(scenario, "_send_rc", lambda _channels: None)
    monkeypatch.setattr(scenario, "_receive_pending", lambda: None)

    with pytest.raises(ScenarioError, match="last telemetry: state=None"):
        scenario._wait_for(NEUTRAL_DISARMED, lambda: False, 0.5, "test state")


def test_cleanup_does_not_force_disarm_while_airborne(monkeypatch):
    class FakeSocket:
        closed = False

        def close(self):
            self.closed = True

    scenario = MavlinkRcScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=1.0,
        landing_timeout_s=1.0,
        touchdown_altitude_m=0.15,
    )
    fake_socket = FakeSocket()
    scenario._socket = fake_socket
    scenario._airborne = True
    sent = []
    monkeypatch.setattr(
        scenario,
        "_send_for",
        lambda channels, duration: sent.append((channels, duration)),
    )

    scenario._cleanup()

    assert sent == []
    assert fake_socket.closed is True
    assert scenario._socket is None

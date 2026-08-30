from __future__ import annotations

from dataclasses import replace
import importlib
from io import StringIO
import struct

import pytest
from pymavlink import mavutil

from joy_scenarios import JoystickCommand, ScenarioConfig
from joy_scenarios.console import ConsoleScenarioLogger
from joy_scenarios.models import (
    ColorMode,
    RC_MAX,
    RC_MID,
    RC_MIN,
    ScenarioError,
    TelemetrySnapshot,
)
from joy_scenarios.scenario import JoyScenario
from joy_scenarios.steps import land_manual
from joy_scenarios.telemetry import StateTransition, TelemetryMonitor


scenario_01_basic_takeoff_land = importlib.import_module(
    "joy_scenarios.01_basic_takeoff_land"
)
scenario_02_altitude_steps = importlib.import_module(
    "joy_scenarios.02_altitude_steps"
)
scenario_03_alt_hold_yaw = importlib.import_module(
    "joy_scenarios.03_alt_hold_yaw"
)
scenario_04_tracker_glide = importlib.import_module(
    "joy_scenarios.04_tracker_glide"
)


def wire_message(encoder, message):
    parser = mavutil.mavlink.MAVLink(None)
    decoded = None
    for byte in message.pack(encoder):
        candidate = parser.parse_char(bytes([byte]))
        if candidate is not None:
            decoded = candidate
    assert decoded is not None
    return decoded


def test_named_joystick_snapshots_are_complete_and_immutable():
    manual = JoystickCommand.manual_armed(throttle=1640)
    takeoff = JoystickCommand.automatic_takeoff()
    hold = JoystickCommand.altitude_hold()

    assert manual.channels[:9] == (
        RC_MID,
        RC_MID,
        1640,
        RC_MID,
        RC_MAX,
        RC_MIN,
        RC_MIN,
        RC_MIN,
        RC_MIN,
    )
    assert len(manual.channels) == 18
    assert manual.channels[9:] == (RC_MIN,) * 9
    assert takeoff.arm == RC_MAX
    assert takeoff.auto_takeoff == RC_MAX
    assert hold.throttle == RC_MID
    assert hold.arm == RC_MAX
    assert hold.auto_takeoff == RC_MIN
    assert manual.with_controls(yaw=1700).yaw == 1700
    assert manual.yaw == RC_MID
    tracker = JoystickCommand.tracker_1_selected(enable=True)
    assert tracker.channels[7:9] == (RC_MID, RC_MAX)


def test_joystick_rejects_out_of_range_channel():
    with pytest.raises(ValueError, match="roll"):
        JoystickCommand(roll=999)


def test_telemetry_filters_source_and_reports_only_real_state_transitions():
    monitor = TelemetryMonitor()
    ignored_encoder = mavutil.mavlink.MAVLink(None, srcSystem=254, srcComponent=0)
    app_encoder = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)

    ignored = wire_message(
        ignored_encoder,
        ignored_encoder.heartbeat_encode(6, 8, 0, 0, 4),
    )
    heartbeat = wire_message(
        app_encoder,
        app_encoder.heartbeat_encode(
            0,
            0,
            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
            7,
            mavutil.mavlink.MAV_STATE_ACTIVE,
        ),
    )

    assert monitor.consume(ignored).changed is False
    first = monitor.consume(heartbeat)
    repeated = monitor.consume(heartbeat)

    assert first.transition is not None
    assert first.transition.previous is None
    assert first.transition.current == 7
    assert repeated.transition is None
    assert monitor.snapshot.armed is True


def test_telemetry_counts_fresh_altitude_messages():
    monitor = TelemetryMonitor()
    encoder = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    position = wire_message(
        encoder,
        encoder.global_position_int_encode(
            0, 0, 0, 2200, 1750, 0, 0, 0, 65535
        ),
    )

    monitor.consume(position)
    monitor.consume(position)

    assert monitor.snapshot.altitude_m == 1.75
    assert monitor.snapshot.altitude_samples == 2


def test_telemetry_decodes_altitude_setpoint_named_value():
    monitor = TelemetryMonitor()
    encoder = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    message = wire_message(
        encoder,
        encoder.named_value_float_encode(0, b"alt_sp", 15.0),
    )

    update = monitor.consume(message)

    assert update.changed is True
    assert monitor.snapshot.altitude_setpoint_m == pytest.approx(15.0)


def test_telemetry_decodes_attitude_and_wraps_yaw_to_360_degrees():
    monitor = TelemetryMonitor()
    encoder = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    message = wire_message(
        encoder,
        encoder.attitude_encode(0, 0.1, -0.2, -0.1, 0.0, 0.0, 0.0),
    )

    update = monitor.consume(message)

    assert update.changed is True
    assert monitor.snapshot.roll_deg == pytest.approx(5.73, abs=0.01)
    assert monitor.snapshot.pitch_deg == pytest.approx(-11.46, abs=0.01)
    assert monitor.snapshot.yaw_deg == pytest.approx(354.27, abs=0.01)
    assert monitor.snapshot.attitude_samples == 1


def test_telemetry_decodes_fast_channel_status_state_transition():
    monitor = TelemetryMonitor()
    encoder = mavutil.mavlink.MAVLink(None, srcSystem=1, srcComponent=1)
    payload = struct.pack("<BBBH8H", 1, 0, 8, 0, *(1000,) * 8)
    payload += bytes(249 - len(payload))
    message = wire_message(
        encoder,
        encoder.v2_extension_encode(0, 0, 0, 1, payload),
    )

    update = monitor.consume(message)

    assert update.transition is not None
    assert update.transition.current == 8
    assert monitor.snapshot.state == 8


def test_console_logger_colors_state_transition_when_forced():
    stream = StringIO()
    logger = ConsoleScenarioLogger(
        color=ColorMode.ALWAYS,
        stream=stream,
        wall_clock=lambda: 0.0,
    )
    snapshot = replace(TelemetryMonitor().snapshot, state=7, armed=True)

    logger.state_transition(StateTransition(None, 7, snapshot))

    output = stream.getvalue()
    assert "\033[1;32m" in output
    assert "UNKNOWN -> ALT_HOLD" in output
    assert "armed=True" in output


class FakeTransport:
    def __init__(self):
        self.opened = False
        self.closed = False
        self.sent = []

    def open(self):
        self.opened = True

    def close(self):
        self.closed = True

    def send(self, command):
        self.sent.append(command)

    def receive(self):
        return ()


class FakeLogger:
    def __init__(self):
        self.phases = []
        self.failures = []

    def phase(self, message):
        self.phases.append(message)

    def state_transition(self, transition):
        pass

    def failure(self, message):
        self.failures.append(message)


def test_preflight_cleanup_sends_disarm(monkeypatch):
    transport = FakeTransport()
    logger = FakeLogger()
    scenario = JoyScenario(ScenarioConfig(), transport=transport, logger=logger)
    sent_for = []
    monkeypatch.setattr(
        scenario,
        "send_for",
        lambda command, duration, **kwargs: sent_for.append((command, duration)),
    )

    with pytest.raises(RuntimeError):
        with scenario:
            raise RuntimeError("test failure")

    assert sent_for == [(JoystickCommand.manual_disarmed(), 0.5)]
    assert transport.closed is True


def test_airborne_cleanup_stops_without_disarm(monkeypatch):
    transport = FakeTransport()
    logger = FakeLogger()
    scenario = JoyScenario(ScenarioConfig(), transport=transport, logger=logger)
    sent_for = []
    monkeypatch.setattr(
        scenario,
        "send_for",
        lambda command, duration, **kwargs: sent_for.append((command, duration)),
    )

    with pytest.raises(RuntimeError):
        with scenario:
            scenario.mark_airborne()
            raise RuntimeError("test failure")

    assert sent_for == []
    assert logger.failures == [
        "Stopping RC while airborne; bt-app failsafe must recover"
    ]


def test_wait_timeout_includes_last_telemetry():
    ticks = iter(index / 10 for index in range(100))
    scenario = JoyScenario(
        ScenarioConfig(rate_hz=50.0),
        transport=FakeTransport(),
        logger=FakeLogger(),
        clock=lambda: next(ticks),
        sleep=lambda _duration: None,
    )

    with pytest.raises(ScenarioError, match="last telemetry: state=UNKNOWN"):
        scenario.wait_until(
            JoystickCommand.neutral_disarmed(),
            lambda: False,
            0.5,
            "test condition",
        )


def test_landing_requires_three_consecutive_fresh_touchdown_samples():
    class LandingRuntime:
        config = ScenarioConfig(touchdown_altitude_m=0.15)

        def __init__(self):
            self.telemetry = TelemetrySnapshot(state=1, armed=True)
            self.logger = FakeLogger()
            self.grounded = False

        def wait_for_state(self, command, state, timeout_s, *, armed=None):
            assert state == 1
            assert armed is True

        def wait_until(self, command, predicate, timeout_s, expectation):
            for altitude in (0.10, 0.20, 0.10, 0.09, 0.08):
                self.telemetry = replace(
                    self.telemetry,
                    altitude_m=altitude,
                    altitude_samples=self.telemetry.altitude_samples + 1,
                )
                if predicate():
                    return
            raise AssertionError("touchdown predicate did not become true")

        def mark_grounded(self):
            self.grounded = True

    runtime = LandingRuntime()

    land_manual(runtime, 1640)

    assert runtime.telemetry.altitude_samples == 5
    assert runtime.grounded is True


def test_basic_scenario_composes_operator_steps(monkeypatch):
    calls = []

    class FakeScenario:
        logger = FakeLogger()

        def __init__(self, config):
            calls.append(("init", config))

        def __enter__(self):
            calls.append(("enter",))
            return self

        def __exit__(self, *args):
            calls.append(("exit",))

        def wait_for_telemetry(self):
            calls.append(("telemetry",))

        def arm_manual(self):
            calls.append(("arm",))

        def auto_takeoff(self):
            calls.append(("takeoff",))

        def hold_altitude(self, duration):
            calls.append(("hold", duration))

        def land_manual(self, throttle):
            calls.append(("land", throttle))

        def disarm(self):
            calls.append(("disarm",))

        def complete(self):
            calls.append(("complete",))

    monkeypatch.setattr(scenario_01_basic_takeoff_land, "JoyScenario", FakeScenario)

    scenario_01_basic_takeoff_land.run_scenario(
        ScenarioConfig(), alt_hold_duration_s=10.0, descent_throttle=1640
    )

    assert [call[0] for call in calls] == [
        "init",
        "enter",
        "telemetry",
        "arm",
        "takeoff",
        "hold",
        "land",
        "disarm",
        "complete",
        "exit",
    ]


def test_basic_cli_defaults_and_validation():
    args = scenario_01_basic_takeoff_land.build_parser().parse_args([])
    config = scenario_01_basic_takeoff_land.config_from_args(args)

    assert args.descent_throttle == 1640
    assert args.alt_hold_duration == 15.0
    assert config.landing_timeout_s == 120.0

    args.descent_throttle = 1660
    with pytest.raises(ValueError, match="descent-throttle"):
        scenario_01_basic_takeoff_land.config_from_args(args)


def test_altitude_steps_scenario_composes_expected_profile(monkeypatch):
    calls = []

    class FakeScenario:
        logger = FakeLogger()

        def __init__(self, config):
            calls.append(("init", config))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append(("exit",))

        def wait_for_telemetry(self):
            calls.append(("telemetry",))

        def arm_manual(self):
            calls.append(("arm",))

        def auto_takeoff(self):
            calls.append(("takeoff",))

        def wait_for_altitude(self, target, **kwargs):
            calls.append(("wait_altitude", target))

        def change_altitude(self, target, **kwargs):
            calls.append(("change_altitude", target))

        def hold_altitude(self, duration):
            calls.append(("hold", duration))

        def land_manual(self, throttle):
            calls.append(("land", throttle))

        def disarm(self):
            calls.append(("disarm",))

        def complete(self):
            calls.append(("complete",))

    monkeypatch.setattr(scenario_02_altitude_steps, "JoyScenario", FakeScenario)
    args = scenario_02_altitude_steps.build_parser().parse_args([])

    scenario_02_altitude_steps.run_scenario(
        scenario_02_altitude_steps.config_from_args(args), args
    )

    assert [(call[0], *call[1:]) for call in calls if call[0] != "init"] == [
        ("telemetry",),
        ("arm",),
        ("takeoff",),
        ("wait_altitude", 10.0),
        ("change_altitude", 15.0),
        ("hold", 10.0),
        ("change_altitude", 8.0),
        ("hold", 10.0),
        ("land", 1640),
        ("disarm",),
        ("complete",),
        ("exit",),
    ]


def test_alt_hold_yaw_scenario_composes_expected_turns(monkeypatch):
    calls = []

    class FakeScenario:
        logger = FakeLogger()

        def __init__(self, config):
            calls.append(("init", config))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append(("exit",))

        def wait_for_telemetry(self):
            calls.append(("telemetry",))

        def arm_manual(self):
            calls.append(("arm",))

        def auto_takeoff(self):
            calls.append(("takeoff",))

        def wait_for_altitude(self, target, **kwargs):
            calls.append(("altitude", target))

        def turn_yaw(self, angle, *, clockwise, timeout_s):
            calls.append(("yaw", angle, clockwise))

        def land_manual(self, throttle):
            calls.append(("land", throttle))

        def disarm(self):
            calls.append(("disarm",))

        def complete(self):
            calls.append(("complete",))

    monkeypatch.setattr(scenario_03_alt_hold_yaw, "JoyScenario", FakeScenario)
    args = scenario_03_alt_hold_yaw.build_parser().parse_args([])

    scenario_03_alt_hold_yaw.run_scenario(
        scenario_03_alt_hold_yaw.config_from_args(args), args
    )

    assert [(call[0], *call[1:]) for call in calls if call[0] != "init"] == [
        ("telemetry",),
        ("arm",),
        ("takeoff",),
        ("altitude", 10.0),
        ("yaw", 90.0, False),
        ("yaw", 180.0, True),
        ("yaw", 90.0, False),
        ("land", 1640),
        ("disarm",),
        ("complete",),
        ("exit",),
    ]


def test_tracker_glide_scenario_composes_successful_profile(monkeypatch):
    calls = []

    class FakeScenario:
        logger = FakeLogger()

        def __init__(self, config):
            calls.append(("init", config))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append(("exit",))

        def wait_for_telemetry(self):
            calls.append(("telemetry",))

        def arm_manual(self):
            calls.append(("arm",))

        def auto_takeoff(self):
            calls.append(("takeoff",))

        def wait_for_altitude(self, target, **kwargs):
            calls.append(("altitude", target))

        def enter_tracker_1(self, **kwargs):
            calls.append(("tracker_enter",))

        def move_target_gate(self, **kwargs):
            calls.append(("gate_down", kwargs["pitch"]))

        def wait_for_tracker_exit(self, **kwargs):
            calls.append(("tracker_exit",))

        def land_manual(self, throttle):
            calls.append(("land", throttle))

        def disarm(self):
            calls.append(("disarm",))

        def complete(self):
            calls.append(("complete",))

    monkeypatch.setattr(scenario_04_tracker_glide, "JoyScenario", FakeScenario)
    args = scenario_04_tracker_glide.build_parser().parse_args([])

    scenario_04_tracker_glide.run_scenario(
        scenario_04_tracker_glide.config_from_args(args), args
    )

    assert [call[0] for call in calls if call[0] != "init"] == [
        "telemetry",
        "arm",
        "takeoff",
        "altitude",
        "gate_down",
        "tracker_enter",
        "tracker_exit",
        "land",
        "disarm",
        "complete",
        "exit",
    ]


def test_tracker_timeout_recovers_lands_and_reports_failure(monkeypatch):
    calls = []

    class FakeScenario:
        logger = FakeLogger()

        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            calls.append("exit")

        def wait_for_telemetry(self):
            pass

        def arm_manual(self):
            pass

        def auto_takeoff(self):
            pass

        def wait_for_altitude(self, target, **kwargs):
            pass

        def enter_tracker_1(self, **kwargs):
            pass

        def move_target_gate(self, **kwargs):
            calls.append("gate_down")

        def wait_for_tracker_exit(self, **kwargs):
            raise ScenarioError("tracking timeout")

        def disable_tracker_and_recover(self, **kwargs):
            calls.append("recover")

        def land_manual(self, throttle):
            calls.append("land")

        def disarm(self):
            calls.append("disarm")

        def complete(self):
            calls.append("complete")

    monkeypatch.setattr(scenario_04_tracker_glide, "JoyScenario", FakeScenario)
    args = scenario_04_tracker_glide.build_parser().parse_args([])

    with pytest.raises(ScenarioError, match="tracking timeout"):
        scenario_04_tracker_glide.run_scenario(
            scenario_04_tracker_glide.config_from_args(args), args
        )

    assert calls == [
        "gate_down",
        "recover",
        "land",
        "disarm",
        "complete",
        "exit",
    ]

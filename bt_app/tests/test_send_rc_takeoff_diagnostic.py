import csv
from importlib.util import module_from_spec, spec_from_file_location
import math
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest
from pymavlink import mavutil


EXAMPLE_DIR = Path(__file__).parents[1] / "example"
sys.path.insert(0, str(EXAMPLE_DIR))
SCRIPT_PATH = EXAMPLE_DIR / "send_rc_takeoff_diagnostic.py"
SPEC = spec_from_file_location("send_rc_takeoff_diagnostic", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
diagnostic = module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def make_scenario(tmp_path):
    return diagnostic.TakeoffDiagnosticScenario(
        destination=("127.0.0.1", 14560),
        listen=("0.0.0.0", 14550),
        rate_hz=50.0,
        state_timeout_s=20.0,
        landing_timeout_s=60.0,
        touchdown_altitude_m=0.15,
        alt_hold_duration_s=15.0,
        descent_throttle=1600,
        output_path=tmp_path / "takeoff.csv",
        parameter_destination=("127.0.0.1", 14551),
        parameter_timeout_s=8.0,
    )


class ChannelStatusMessage:
    def __init__(self, channels):
        packed = struct.pack(
            diagnostic.CHANNEL_STATUS_FORMAT,
            diagnostic.CHANNEL_STATUS_VERSION,
            1,
            diagnostic.STATE_TAKEOFF,
            0,
            *channels,
        )
        self.message_type = diagnostic.CHANNEL_STATUS_MESSAGE_TYPE
        self.payload = packed.ljust(249, b"\0")

    @staticmethod
    def get_srcSystem():
        return diagnostic.APP_SYSTEM_ID

    @staticmethod
    def get_srcComponent():
        return diagnostic.APP_COMPONENT_ID

    @staticmethod
    def get_type():
        return "V2_EXTENSION"


class RcChannelsMessage:
    chancount = 8

    def __init__(self, channels):
        for index, value in enumerate(channels, start=1):
            setattr(self, f"chan{index}_raw", value)

    @staticmethod
    def get_srcSystem():
        return diagnostic.APP_SYSTEM_ID

    @staticmethod
    def get_srcComponent():
        return diagnostic.APP_COMPONENT_ID

    @staticmethod
    def get_type():
        return "RC_CHANNELS"


class NamedValueFloatMessage:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    @staticmethod
    def get_srcSystem():
        return diagnostic.APP_SYSTEM_ID

    @staticmethod
    def get_srcComponent():
        return diagnostic.APP_COMPONENT_ID

    @staticmethod
    def get_type():
        return "NAMED_VALUE_FLOAT"


def test_channel_status_decodes_actual_controller_output():
    telemetry = diagnostic.DiagnosticTelemetry()

    telemetry.consume(
        ChannelStatusMessage((1500, 1500, 1725, 1500, 2000, 2000, 1000, 1000))
    )

    assert telemetry.output_state == diagnostic.STATE_TAKEOFF
    assert telemetry.output_channels is not None
    assert telemetry.output_channels[diagnostic.THROTTLE] == 1725


def test_standard_rc_channels_decodes_actual_controller_output():
    telemetry = diagnostic.DiagnosticTelemetry()

    telemetry.consume(
        RcChannelsMessage((1500, 1500, 1710, 1500, 2000, 2000, 1000, 1000))
    )

    assert telemetry.output_channels is not None
    assert telemetry.output_channels[diagnostic.THROTTLE] == 1710


def test_named_value_float_decodes_and_clears_target_distance():
    telemetry = diagnostic.DiagnosticTelemetry()

    telemetry.consume(NamedValueFloatMessage(b"tgt_dist\0\0", 12.34))
    assert telemetry.target_distance_m == pytest.approx(12.34)

    telemetry.consume(NamedValueFloatMessage("tgt_dist", math.nan))
    assert telemetry.target_distance_m is None


def test_named_value_float_decodes_glide_visual_diagnostics():
    telemetry = diagnostic.DiagnosticTelemetry()

    for name, value in (
        ("vis_found", 1.0),
        ("vis_locked", 0.0),
        ("vis_frame", 42.0),
        ("vis_age", 0.03),
        ("vis_ex", 0.25),
        ("vis_ey", -0.10),
        ("obs_valid", 1.0),
        ("obs_reason", 0.0),
        ("acq_count", 4.0),
        ("gld_phase", 1.0),
    ):
        telemetry.consume(NamedValueFloatMessage(name, value))

    assert telemetry.visual_found
    assert not telemetry.visual_locked
    assert telemetry.visual_frame_id == 42
    assert telemetry.visual_age_s == pytest.approx(0.03)
    assert telemetry.visual_error_x == pytest.approx(0.25)
    assert telemetry.visual_error_y == pytest.approx(-0.10)
    assert telemetry.observation_valid
    assert telemetry.observation_reason_code == 0
    assert telemetry.acquisition_count == 4
    assert telemetry.glide_phase_code == 1


def test_parameter_decoder_reads_real32_directly():
    message = SimpleNamespace(
        param_type=mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
        param_value=2.5,
    )

    assert diagnostic.decode_parameter_value(message) == pytest.approx(2.5)


def test_parameter_decoder_reinterprets_bytewise_int32():
    wire_value = struct.unpack("<f", struct.pack("<i", 1660))[0]
    message = SimpleNamespace(
        param_type=mavutil.mavlink.MAV_PARAM_TYPE_INT32,
        param_value=wire_value,
    )

    assert diagnostic.decode_parameter_value(message) == 1660


def test_parameter_decoder_reinterprets_bytewise_uint8():
    wire_value = struct.unpack("<f", struct.pack("<I", 1))[0]
    message = SimpleNamespace(
        param_type=mavutil.mavlink.MAV_PARAM_TYPE_UINT8,
        param_value=wire_value,
    )

    assert diagnostic.decode_parameter_value(message) == 1


def test_snapshot_records_correction_and_saturation(tmp_path):
    scenario = make_scenario(tmp_path)
    scenario.parameter_values.update(
        {
            "HOV_BASELINE": 1660.0,
            "ALT_OUT_LIMIT": 100.0,
            "TAKEOFF_ALT": 4.0,
        }
    )
    scenario.telemetry.state = diagnostic.STATE_TAKEOFF
    scenario.telemetry.armed = True
    scenario.telemetry.altitude_m = 1.5
    scenario.telemetry.output_channels = (
        1500,
        1500,
        1760,
        1500,
        2000,
        2000,
        1000,
        1000,
    )

    scenario._open_recording()
    scenario._write_snapshot()
    scenario._close_recording()

    with scenario.output_path.open(newline="", encoding="utf-8") as stream:
        row = next(csv.DictReader(stream))
    assert row["state"] == "TAKEOFF"
    assert row["sample_source"] == "test"
    assert row["output_throttle_pwm"] == "1760"
    assert row["output_correction_pwm"] == "100.0"
    assert row["output_saturated"] == "1"


def test_help_contains_diagnostic_banner():
    assert diagnostic.SCENARIO_BANNER in diagnostic.build_parser().format_help()


def test_runtime_banner_prints_resolved_csv_path(tmp_path, capsys):
    scenario = make_scenario(tmp_path)

    scenario._print_banner()

    output = capsys.readouterr().out
    assert diagnostic.SCENARIO_BANNER in output
    assert f"CSV output: {scenario.output_path.resolve()}" in output

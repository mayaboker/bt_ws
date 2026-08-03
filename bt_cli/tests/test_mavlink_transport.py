import pytest
from pymavlink import mavutil
from bti_cli.transport import MavlinkParameterTransport, MavlinkTransportError


@pytest.mark.parametrize(
    ("raw_value", "parameter_type", "expected"),
    [
        ("1400", mavutil.mavlink.MAV_PARAM_TYPE_INT32, 1400),
        ("0.55", mavutil.mavlink.MAV_PARAM_TYPE_REAL32, 0.55),
        ("true", mavutil.mavlink.MAV_PARAM_TYPE_UINT8, True),
        ("0", mavutil.mavlink.MAV_PARAM_TYPE_UINT8, False),
    ],
)
def test_parameter_value_codec(raw_value, parameter_type, expected):
    parsed = MavlinkParameterTransport._parse_cli_value(raw_value, parameter_type)
    encoded = MavlinkParameterTransport._encode_value(parsed, parameter_type)
    decoded = MavlinkParameterTransport._decode_value(encoded, parameter_type)

    assert decoded == pytest.approx(expected)


def test_parameter_value_codec_rejects_invalid_int():
    with pytest.raises(MavlinkTransportError, match="Invalid parameter value"):
        MavlinkParameterTransport._parse_cli_value(
            "not-an-int",
            mavutil.mavlink.MAV_PARAM_TYPE_INT32,
        )

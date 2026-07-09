import struct

import pytest

from bt_app.msp.bt_v2 import (
    MSP_BATTERY_STATE,
    RCChannel,
    RCChannel_alias,
    parse_battery_state,
)


def test_rc_channel_count_is_8():
    assert len(RCChannel) == 8


def test_rc_channel_alias_count_is_8():
    assert len(RCChannel_alias) == 8


def test_parse_battery_state_decodes_betaflight_payload():
    payload = struct.pack(
        "<BHBHhBH",
        4,
        1500,
        161,
        375,
        1234,
        2,
        1610,
    )

    battery = parse_battery_state(payload)

    assert battery == {
        "cell_count": 4,
        "capacity_mah": 1500,
        "legacy_voltage_deci_volts": 161,
        "consumed_mah": 375,
        "current_ca": 1234,
        "current_a": 12.34,
        "battery_state": 2,
        "voltage_cv": 1610,
        "voltage_v": 16.1,
        "voltage_mv": 16100,
        "remaining_percent": 75,
    }


def test_parse_battery_state_handles_unknown_capacity():
    payload = struct.pack("<BHBHhBH", 0, 0, 0, 0, 0, 0, 0)

    battery = parse_battery_state(payload)

    assert battery["remaining_percent"] == -1


def test_parse_battery_state_rejects_short_payload():
    with pytest.raises(ValueError, match="MSP_BATTERY_STATE payload too short"):
        parse_battery_state(b"\x00" * 10)


def test_read_battery_state_requests_msp_battery_state():
    class FakeTransport:
        def __init__(self):
            self.writes = []
            self.response = bytearray(
                b"$M>"
                + bytes([11, MSP_BATTERY_STATE])
                + struct.pack("<BHBHhBH", 3, 1000, 126, 250, -50, 1, 1260)
            )
            checksum = 0
            for byte in self.response[3:]:
                checksum ^= byte
            self.response.append(checksum)

        def write(self, data):
            self.writes.append(data)

        def read(self, size, timeout):
            data = bytes(self.response[:size])
            del self.response[:size]
            return data

    from bt_app.msp.bt_v2 import BetaflightMspClient

    transport = FakeTransport()
    client = BetaflightMspClient(transport)

    battery = client.read_battery_state()

    assert transport.writes
    assert transport.writes[0][4] == MSP_BATTERY_STATE
    assert battery["cell_count"] == 3
    assert battery["voltage_mv"] == 12600
    assert battery["current_ca"] == -50

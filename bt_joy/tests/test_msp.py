import struct
import unittest

from bt_joy.server.msp import (
    MSP_ALTITUDE,
    MSP_RC,
    MSP_SET_RAW_RC,
    MSP_STATUS_EX,
    MspCodec,
    decode_arming_disabled_flags,
    normalize_rc_channels,
    parse_altitude,
    parse_api_version,
    parse_board_info,
    parse_build_info,
    parse_fc_version,
    parse_status_ex,
    unpack_u16_list,
)


class MspTest(unittest.TestCase):
    def test_encodes_set_raw_rc_request(self) -> None:
        codec = MspCodec()
        payload = struct.pack("<8H", *[1000, 1500, 2000, 1500, 1000, 2000, 1500, 1500])
        frame = codec.encode_request(MSP_SET_RAW_RC, payload)

        self.assertEqual(frame[:3], b"$M<")
        self.assertEqual(frame[3], 16)
        self.assertEqual(frame[4], MSP_SET_RAW_RC)
        self.assertEqual(frame[5:21], payload)
        checksum = 16 ^ MSP_SET_RAW_RC
        for byte in payload:
            checksum ^= byte
        self.assertEqual(frame[-1], checksum)

    def test_normalizes_rc_channels_to_eight_values(self) -> None:
        self.assertEqual(
            normalize_rc_channels([1000, 2000, 3000]),
            [1000, 2000, 3000, 1500, 1500, 1500, 1500, 1500],
        )

    def test_status_ex_command_id(self) -> None:
        frame = MspCodec().encode_request(MSP_STATUS_EX)

        self.assertEqual(frame[:3], b"$M<")
        self.assertEqual(frame[4], 150)

    def test_rc_command_id(self) -> None:
        frame = MspCodec().encode_request(MSP_RC)

        self.assertEqual(frame[:3], b"$M<")
        self.assertEqual(frame[4], 105)

    def test_altitude_command_id(self) -> None:
        frame = MspCodec().encode_request(MSP_ALTITUDE)

        self.assertEqual(frame[:3], b"$M<")
        self.assertEqual(frame[4], 109)

    def test_unpack_u16_list(self) -> None:
        payload = struct.pack("<4H", 1000, 1500, 2000, 1200)

        self.assertEqual(unpack_u16_list(payload), [1000, 1500, 2000, 1200])

    def test_parse_altitude(self) -> None:
        payload = struct.pack("<ih", 1234, -56)

        altitude = parse_altitude(payload)

        self.assertEqual(altitude.altitude_m, 12.34)
        self.assertEqual(altitude.vertical_speed_m_s, -0.56)

    def test_parse_status_ex(self) -> None:
        arming_disabled_flags = (1 << 7) | (1 << 16)
        payload = (
            struct.pack("<HHHIBHBBB", 250, 2, 0x13, 0xAABBCCDD, 1, 42, 3, 2, 0)
            + struct.pack("<BI", 29, arming_disabled_flags)
            + struct.pack("<BH", 1, 55)
        )

        status = parse_status_ex(payload)

        self.assertEqual(status.cycle_time_us, 250)
        self.assertEqual(status.i2c_errors, 2)
        self.assertEqual(status.sensors_mask, 0x13)
        self.assertEqual(status.box_mode_flags, 0xAABBCCDD)
        self.assertEqual(status.config_profile, 1)
        self.assertEqual(status.average_system_load_percent, 42)
        self.assertEqual(status.pid_profile_count, 3)
        self.assertEqual(status.control_rate_profile, 2)
        self.assertEqual(status.arming_disabled_flags_count, 29)
        self.assertEqual(status.arming_disabled_flags, arming_disabled_flags)
        self.assertEqual(status.arming_disabled_flag_names, ("THROTTLE", "MSP"))
        self.assertEqual(status.config_state_flags, 1)
        self.assertEqual(status.cpu_temp_celsius, 55)

    def test_decode_arming_disabled_flags(self) -> None:
        self.assertEqual(
            decode_arming_disabled_flags((1 << 13) | (1 << 16)),
            ("CLI", "MSP"),
        )

    def test_parse_api_version(self) -> None:
        api_version = parse_api_version(bytes([0, 1, 48]))

        self.assertEqual(api_version.protocol, 0)
        self.assertEqual(api_version.major, 1)
        self.assertEqual(api_version.minor, 48)
        self.assertEqual(str(api_version), "1.48 protocol=0")

    def test_parse_fc_version(self) -> None:
        fc_version = parse_fc_version(bytes([4, 5, 2]))

        self.assertEqual(fc_version.major, 4)
        self.assertEqual(fc_version.minor, 5)
        self.assertEqual(fc_version.patch, 2)
        self.assertEqual(str(fc_version), "4.5.2")

    def test_parse_board_info(self) -> None:
        board_info = parse_board_info(b"S405" + struct.pack("<H", 3) + b"\x01\x02")

        self.assertEqual(board_info.identifier, "S405")
        self.assertEqual(board_info.hardware_revision, 3)
        self.assertEqual(board_info.raw, b"S405\x03\x00\x01\x02")

    def test_parse_build_info(self) -> None:
        build_info = parse_build_info(b"May 18 2026" + b"12:34:56" + b"abcdef0")

        self.assertEqual(build_info.date, "May 18 2026")
        self.assertEqual(build_info.time, "12:34:56")
        self.assertEqual(build_info.revision, "abcdef0")


if __name__ == "__main__":
    unittest.main()

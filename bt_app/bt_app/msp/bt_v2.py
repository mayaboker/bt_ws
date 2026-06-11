from __future__ import annotations

import struct
from typing import Sequence

from bt_app.msp.protocol import MspCodec, MspFrame, MspProtocolError
from bt_app.msp.transport import MspTransport
from enum import IntEnum


class RCChannel(IntEnum):
    ROLL = 0
    PITCH = 1
    THROTTLE = 2
    YAW = 3
    AUX1 = 4
    AUX2 = 5
    AUX3 = 6
    AUX4 = 7

class RCChannel_alias(IntEnum):
    ROLL = 0
    PITCH = 1
    THROTTLE = 2
    YAW = 3
    ARM = 4
    ANGLE = 5
    AUX3 = 6
    AUX4 = 7

RC_MIN = 1000
RC_MAX = 2000
RC_MID = 1500
RC_MID_RANGE = 500

MSP_API_VERSION = 1
MSP_STATUS = 101
MSP_RAW_IMU = 102
MSP_MOTOR = 104
MSP_RC = 105
MSP_ATTITUDE = 108
MSP_ALTITUDE = 109
MSP_STATUS_EX = 150
MSP_SET_RAW_RC = 200


ARMING_DISABLE_FLAGS = {
    0: "NO_GYRO",
    1: "FAILSAFE",
    2: "RX_FAILSAFE",
    3: "NOT_DISARMED",
    4: "BOXFAILSAFE",
    5: "RUNAWAY_TAKEOFF",
    6: "CRASH_DETECTED",
    7: "THROTTLE",
    8: "ANGLE",
    9: "BOOT_GRACE_TIME",
    10: "NOPREARM",
    11: "LOAD",
    12: "CALIBRATING",
    13: "CLI",
    14: "CMS_MENU",
    15: "BST",
    16: "MSP",
    17: "PARALYZE",
    18: "GPS",
    19: "RESCUE_SW",
    20: "RPMFILTER",
    21: "REBOOT_REQUIRED",
    22: "DSHOT_BITBANG",
    23: "ACC_CALIBRATION",
    24: "MOTOR_PROTOCOL",
    25: "ARMING_DISABLED_ARM_SWITCH",
    26: "ALTITUDE",
    27: "POSITION",
    28: "ARM_SWITCH",
}


class BetaflightMspClient:
    def __init__(self, transport: MspTransport, codec: MspCodec | None = None) -> None:
        self.transport = transport
        self.codec = codec or MspCodec()

    def open(self) -> None:
        self.transport.open()

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "BetaflightMspClient":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def encode(self, command: int, payload: bytes = b"", version: int | None = None) -> bytes:
        return self.codec.encode_request(command, payload, version=version)

    def decode(self, timeout: float = 0.5) -> MspFrame:
        return self.codec.read_frame(self.transport, timeout=timeout)

    def send(self, command: int, payload: bytes = b"", version: int | None = None) -> None:
        self.transport.write(self.encode(command, payload, version=version))

    def request(
        self,
        command: int,
        payload: bytes = b"",
        timeout: float = 0.5,
        version: int | None = None,
    ) -> bytes:
        self.send(command, payload, version=version)

        while True:
            frame = self.decode(timeout=timeout)
            if frame.command != command:
                continue

            if frame.is_error:
                raise MspProtocolError(f"MSP error response for command {command}")

            return frame.payload

    def send_raw_rc(self, channels: Sequence[int], timeout: float = 0.005) -> None:
        if len(channels) != 8:
            raise ValueError("MSP_SET_RAW_RC expects exactly 8 channels")

        payload = struct.pack("<8H", *channels)
        self.send(MSP_SET_RAW_RC, payload)

        try:
            self.decode(timeout=timeout)
        except TimeoutError:
            pass

    def read_rc(self, timeout: float = 0.5) -> list[int]:
        payload = self.request(MSP_RC, timeout=timeout)
        return unpack_u16_list(payload)

    def read_motors(self, timeout: float = 0.5) -> list[int]:
        payload = self.request(MSP_MOTOR, timeout=timeout)
        return unpack_u16_list(payload)

    def read_attitude(self, timeout: float = 0.5) -> dict[str, float | int]:
        payload = self.request(MSP_ATTITUDE, timeout=timeout)
        roll_x10, pitch_x10, heading = struct.unpack_from("<hhh", payload)
        return {
            "roll_deg": roll_x10 / 10.0,
            "pitch_deg": pitch_x10 / 10.0,
            "heading_deg": heading,
        }

    def read_altitude(self, timeout: float = 0.5) -> dict[str, float]:
        payload = self.request(MSP_ALTITUDE, timeout=timeout)
        altitude_cm, vario_cm_s = struct.unpack_from("<ih", payload)
        return {
            "altitude_m": altitude_cm / 100.0,
            "vertical_speed_m_s": vario_cm_s / 100.0,
        }

    def read_raw_imu(self, timeout: float = 0.5) -> dict[str, tuple[int, ...]]:
        payload = self.request(MSP_RAW_IMU, timeout=timeout)
        values = struct.unpack_from("<9h", payload)
        return {
            "acc": values[0:3],
            "gyro": values[3:6],
            "mag": values[6:9],
        }

    def read_state(self, timeout: float = 0.5) -> dict[str, object]:
        payload = self.request(MSP_STATUS_EX, timeout=timeout)
        return parse_status_ex(payload)


def unpack_u16_list(payload: bytes) -> list[int]:
    count = len(payload) // 2
    return list(struct.unpack_from("<" + "H" * count, payload))


def decode_arming_mask(mask: int) -> list[str]:
    return [
        name
        for bit, name in ARMING_DISABLE_FLAGS.items()
        if mask & (1 << bit)
    ]


def parse_status_ex(payload: bytes) -> dict[str, object]:
    if len(payload) < 16:
        raise ValueError(f"MSP_STATUS_EX payload too short: {len(payload)} bytes")

    cycle_time_us = struct.unpack_from("<H", payload, 0)[0]
    i2c_errors = struct.unpack_from("<H", payload, 2)[0]
    sensors_mask = struct.unpack_from("<H", payload, 4)[0]
    box_mode_flags = struct.unpack_from("<I", payload, 6)[0]
    pid_profile = payload[10]
    cpu_load = struct.unpack_from("<H", payload, 11)[0]
    pid_profile_count = payload[13]
    rate_profile = payload[14]

    flight_mode_byte_count = payload[15]
    arming_offset = 16 + flight_mode_byte_count

    if len(payload) < arming_offset + 5:
        raise ValueError(
            f"Cannot decode arming flags. payload_len={len(payload)}, "
            f"flight_mode_byte_count={flight_mode_byte_count}"
        )

    arming_disable_flag_count = payload[arming_offset]
    arming_disable_mask = struct.unpack_from("<I", payload, arming_offset + 1)[0]
    arming_disable_flags = decode_arming_mask(arming_disable_mask)

    return {
        "cycle_time_us": cycle_time_us,
        "i2c_errors": i2c_errors,
        "sensors_mask": sensors_mask,
        "sensors_mask_hex": f"0x{sensors_mask:04x}",
        "box_mode_flags": box_mode_flags,
        "box_mode_flags_hex": f"0x{box_mode_flags:08x}",
        "pid_profile": pid_profile,
        "pid_profile_count": pid_profile_count,
        "rate_profile": rate_profile,
        "cpu_load_raw": cpu_load,
        "flight_mode_byte_count": flight_mode_byte_count,
        "arming_disable_flag_count": arming_disable_flag_count,
        "arming_disable_mask": arming_disable_mask,
        "arming_disable_mask_hex": f"0x{arming_disable_mask:08x}",
        "arming_disable_flags": arming_disable_flags,
        "arming_disabled": bool(arming_disable_flags),
        "armable": not arming_disable_flags,
        "calibrating": "CALIBRATING" in arming_disable_flags,
        "failsafe": "FAILSAFE" in arming_disable_flags
        or "RX_FAILSAFE" in arming_disable_flags,
        "throttle_blocking_arm": "THROTTLE" in arming_disable_flags,
        "arm_switch_blocking_arm": "ARM_SWITCH" in arming_disable_flags
        or "ARMING_DISABLED_ARM_SWITCH" in arming_disable_flags,
        "not_disarmed": "NOT_DISARMED" in arming_disable_flags,
    }

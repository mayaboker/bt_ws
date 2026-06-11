#!/usr/bin/env python3

"""
feature RX_MSP
set receiver_type = MSP
save

set small_angle = 180
save

"""
from __future__ import annotations

import argparse
import json
import struct
import time


DEFAULT_DEVICE = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 115200
MSP_STATUS_EX = 150
MSP_SET_RAW_RC = 200
RC_MIN = 1000
RC_MID = 1500
RC_MAX = 2000
ARM_LOW = 1000
ARM_HIGH = 1900

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


def msp_v1_request(command: int, payload: bytes = b"") -> bytes:
    size = len(payload)
    checksum = size ^ command
    for byte in payload:
        checksum ^= byte
    return b"$M<" + bytes([size, command]) + payload + bytes([checksum])


def crc8_dvb_s2(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0xD5) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def msp_v2_request(command: int, payload: bytes = b"") -> bytes:
    flags = 0
    body = (
        bytes([flags])
        + command.to_bytes(2, "little")
        + len(payload).to_bytes(2, "little")
        + payload
    )
    return b"$X<" + body + bytes([crc8_dvb_s2(body)])


def read_exact(serial_port, size: int, timeout: float) -> bytes:
    serial_port.timeout = timeout
    data = serial_port.read(size)
    if len(data) != size:
        raise TimeoutError(f"Timeout while reading {size} serial bytes")
    return data


def read_msp_response(serial_port, timeout: float) -> tuple[int, bytes]:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        remaining = max(0.001, deadline - time.monotonic())
        if read_exact(serial_port, 1, remaining) != b"$":
            continue
        protocol = read_exact(serial_port, 1, remaining)

        if protocol == b"M":
            return read_msp_v1_response_after_header(serial_port, deadline)
        if protocol == b"X":
            return read_msp_v2_response_after_header(serial_port, deadline)

    raise TimeoutError("No MSP response")


def read_msp_v1_response_after_header(serial_port, deadline: float) -> tuple[int, bytes]:
    remaining = max(0.001, deadline - time.monotonic())
    direction = read_exact(serial_port, 1, remaining)
    if direction not in (b">", b"!"):
        raise ValueError(f"Invalid MSP v1 direction: {direction!r}")

    size = read_exact(serial_port, 1, remaining)[0]
    command = read_exact(serial_port, 1, remaining)[0]
    payload = read_exact(serial_port, size, remaining)
    received_checksum = read_exact(serial_port, 1, remaining)[0]

    checksum = size ^ command
    for byte in payload:
        checksum ^= byte
    if checksum != received_checksum:
        raise ValueError(
            f"Bad MSP v1 checksum: got 0x{received_checksum:02x}, "
            f"expected 0x{checksum:02x}"
        )
    if direction == b"!":
        raise RuntimeError(f"MSP error response for command {command}")

    return command, payload


def read_msp_v2_response_after_header(serial_port, deadline: float) -> tuple[int, bytes]:
    remaining = max(0.001, deadline - time.monotonic())
    direction = read_exact(serial_port, 1, remaining)
    if direction not in (b">", b"!"):
        raise ValueError(f"Invalid MSP v2 direction: {direction!r}")

    flags = read_exact(serial_port, 1, remaining)
    command_bytes = read_exact(serial_port, 2, remaining)
    size_bytes = read_exact(serial_port, 2, remaining)
    size = int.from_bytes(size_bytes, "little")
    payload = read_exact(serial_port, size, remaining)
    received_checksum = read_exact(serial_port, 1, remaining)[0]

    checksum_data = flags + command_bytes + size_bytes + payload
    checksum = crc8_dvb_s2(checksum_data)
    if checksum != received_checksum:
        raise ValueError(
            f"Bad MSP v2 checksum: got 0x{received_checksum:02x}, "
            f"expected 0x{checksum:02x}"
        )

    command = int.from_bytes(command_bytes, "little")
    if direction == b"!":
        raise RuntimeError(f"MSP error response for command {command}")

    return command, payload


def request_msp(
    serial_port,
    command: int,
    timeout: float,
    version: int = 1,
    payload: bytes = b"",
) -> bytes:
    if version == 1:
        request = msp_v1_request(command, payload)
    elif version == 2:
        request = msp_v2_request(command, payload)
    else:
        raise ValueError(f"Unsupported MSP version: {version}")

    serial_port.write(request)
    serial_port.flush()

    while True:
        response_command, payload = read_msp_response(serial_port, timeout)
        if response_command == command:
            return payload


def send_msp(
    serial_port,
    command: int,
    payload: bytes,
    version: int = 1,
) -> None:
    if version == 1:
        request = msp_v1_request(command, payload)
    elif version == 2:
        request = msp_v2_request(command, payload)
    else:
        raise ValueError(f"Unsupported MSP version: {version}")

    serial_port.write(request)
    serial_port.flush()


def clamp(value: float, lower: int, upper: int) -> int:
    return int(max(lower, min(upper, value)))


def make_channels(throttle: int, armed: bool) -> list[int]:
    return [
        RC_MID,
        RC_MID,
        clamp(throttle, RC_MIN, RC_MAX),
        RC_MID,
        ARM_HIGH if armed else ARM_LOW,
        ARM_LOW,
        ARM_LOW,
        ARM_LOW,
    ]


def send_raw_rc(
    serial_port,
    channels: list[int],
    version: int = 1,
) -> None:
    if len(channels) != 8:
        raise ValueError("MSP_SET_RAW_RC expects exactly 8 channels")

    send_msp(serial_port, MSP_SET_RAW_RC, struct.pack("<8H", *channels), version)


def send_rc_for(
    serial_port,
    channels: list[int],
    duration_s: float,
    rate_hz: float,
    version: int,
    status_interval_s: float,
    status_timeout_s: float,
    phase: str,
) -> None:
    interval_s = 1.0 / rate_hz
    end = time.monotonic() + duration_s
    next_status = time.monotonic()
    while time.monotonic() < end:
        started = time.monotonic()
        send_raw_rc(serial_port, channels, version)
        if status_interval_s > 0 and started >= next_status:
            print_status(serial_port, version, status_timeout_s, phase, channels[2])
            next_status = started + status_interval_s
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval_s - elapsed))


def ramp_throttle(
    serial_port,
    start_throttle: int,
    end_throttle: int,
    duration_s: float,
    rate_hz: float,
    version: int,
    status_interval_s: float,
    status_timeout_s: float,
) -> None:
    steps = max(1, int(duration_s * rate_hz))
    interval_s = 1.0 / rate_hz
    next_status = time.monotonic()

    for step in range(steps + 1):
        started = time.monotonic()
        ratio = step / steps
        throttle = round(start_throttle + (end_throttle - start_throttle) * ratio)
        send_raw_rc(serial_port, make_channels(throttle, armed=True), version)
        print(f"armed throttle={throttle}", flush=True)
        if status_interval_s > 0 and started >= next_status:
            print_status(serial_port, version, status_timeout_s, "ramp", throttle)
            next_status = started + status_interval_s
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval_s - elapsed))


def print_status(
    serial_port,
    version: int,
    timeout_s: float,
    phase: str,
    throttle: int,
) -> None:
    try:
        payload = request_msp(
            serial_port,
            MSP_STATUS_EX,
            timeout_s,
            version=version,
        )
        status = parse_status_ex(payload)
        status["phase"] = phase
        status["throttle"] = throttle
        status["timestamp_s"] = time.time()
        print(json.dumps(status, separators=(",", ":"), sort_keys=True), flush=True)
    except TimeoutError as exc:
        print(f"status timeout phase={phase} throttle={throttle}: {exc}", flush=True)


def arm_and_ramp_throttle(serial_port, args: argparse.Namespace) -> None:
    disarmed = make_channels(RC_MIN, armed=False)
    armed_low_throttle = make_channels(RC_MIN, armed=True)

    print("sending disarmed neutral", flush=True)
    send_rc_for(
        serial_port,
        disarmed,
        args.disarmed_duration,
        args.rc_rate_hz,
        args.msp_version,
        args.arm_status_interval,
        args.arm_status_timeout,
        "disarmed",
    )

    print("arming at low throttle", flush=True)
    send_rc_for(
        serial_port,
        armed_low_throttle,
        args.arm_duration,
        args.rc_rate_hz,
        args.msp_version,
        args.arm_status_interval,
        args.arm_status_timeout,
        "arming",
    )

    print(f"ramping throttle to {args.throttle_percent:.0f}%", flush=True)
    ramp_throttle(
        serial_port,
        RC_MIN,
        clamp(RC_MIN + (RC_MAX - RC_MIN) * args.throttle_percent / 100.0, RC_MIN, RC_MAX),
        args.ramp_duration,
        args.rc_rate_hz,
        args.msp_version,
        args.arm_status_interval,
        args.arm_status_timeout,
    )

    if args.hold_duration > 0:
        target_throttle = clamp(
            RC_MIN + (RC_MAX - RC_MIN) * args.throttle_percent / 100.0,
            RC_MIN,
            RC_MAX,
        )
        print(f"holding throttle={target_throttle}", flush=True)
        send_rc_for(
            serial_port,
            make_channels(target_throttle, armed=True),
            args.hold_duration,
            args.rc_rate_hz,
            args.msp_version,
            args.arm_status_interval,
            args.arm_status_timeout,
            "hold",
        )

    if not args.keep_armed:
        print("disarming", flush=True)
        send_rc_for(
            serial_port,
            disarmed,
            args.disarm_duration,
            args.rc_rate_hz,
            args.msp_version,
            args.arm_status_interval,
            args.arm_status_timeout,
            "disarm",
        )


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
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Betaflight MSP status telemetry from a serial device."
    )
    parser.add_argument("--mode", default="status", choices=("status", "arm-ramp"))
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--baudrate", default=DEFAULT_BAUDRATE, type=int)
    parser.add_argument("--rate-hz", default=2.0, type=float)
    parser.add_argument("--timeout", default=0.5, type=float)
    parser.add_argument("--count", default=0, type=int, help="0 means run forever")
    parser.add_argument("--msp-version", default=1, choices=(1, 2), type=int)
    parser.add_argument("--rc-rate-hz", default=50.0, type=float)
    parser.add_argument("--throttle-percent", default=40.0, type=float)
    parser.add_argument("--disarmed-duration", default=2.0, type=float)
    parser.add_argument("--arm-duration", default=3.0, type=float)
    parser.add_argument("--ramp-duration", default=5.0, type=float)
    parser.add_argument("--hold-duration", default=2.0, type=float)
    parser.add_argument("--disarm-duration", default=1.0, type=float)
    parser.add_argument("--arm-status-interval", default=0.25, type=float)
    parser.add_argument("--arm-status-timeout", default=0.1, type=float)
    parser.add_argument("--keep-armed", action="store_true")
    return parser.parse_args()


def main() -> None:
    import serial

    args = parse_args()
    interval_s = 1.0 / args.rate_hz if args.rate_hz > 0 else 0.0

    with serial.Serial(
        port=args.device,
        baudrate=args.baudrate,
        timeout=0,
        write_timeout=1,
    ) as serial_port:
        if args.mode == "arm-ramp":
            arm_and_ramp_throttle(serial_port, args)
            return

        reads = 0
        while args.count <= 0 or reads < args.count:
            started = time.monotonic()
            payload = request_msp(
                serial_port,
                MSP_STATUS_EX,
                args.timeout,
                version=args.msp_version,
            )
            telemetry = parse_status_ex(payload)
            telemetry["timestamp_s"] = time.time()
            print(json.dumps(telemetry, indent=2, sort_keys=True), flush=True)

            reads += 1

            if interval_s:
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, interval_s - elapsed))


if __name__ == "__main__":
    main()

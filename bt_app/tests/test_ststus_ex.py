#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time

from test_serial_port import (
    DEFAULT_BAUDRATE,
    DEFAULT_DEVICE,
    MSP_STATUS_EX,
    parse_status_ex,
    request_msp,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read MSP_STATUS_EX from ttyUSB0.")
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--baudrate", default=DEFAULT_BAUDRATE, type=int)
    parser.add_argument("--timeout", default=0.5, type=float)
    return parser.parse_args()


def main() -> None:
    import serial

    args = parse_args()

    with serial.Serial(
        port=args.device,
        baudrate=args.baudrate,
        timeout=0,
        write_timeout=1,
    ) as serial_port:
        payload = request_msp(serial_port, MSP_STATUS_EX, args.timeout)
        status = parse_status_ex(payload)
        status["timestamp_s"] = time.time()
        print(json.dumps(status, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

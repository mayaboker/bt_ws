#!/usr/bin/env python3

import os
import select
import termios
import time

PORT = "/dev/ttyUSB0"
BAUD_RATE = termios.B115200
TIMEOUT_SECONDS = 1.0

TEST_DATA = b"UART_LOOPBACK_TEST_123456789\r\n"


def configure_uart(fd: int) -> None:
    attributes = termios.tcgetattr(fd)

    # Raw UART mode
    attributes[0] = 0  # Input flags
    attributes[1] = 0  # Output flags
    attributes[2] = (
        termios.CLOCAL
        | termios.CREAD
        | termios.CS8
    )
    attributes[3] = 0  # Local flags: no echo, no canonical mode

    # Input and output baud rates
    attributes[4] = BAUD_RATE
    attributes[5] = BAUD_RATE

    # Return immediately when no data is available
    attributes[6][termios.VMIN] = 0
    attributes[6][termios.VTIME] = 0

    termios.tcsetattr(fd, termios.TCSANOW, attributes)
    termios.tcflush(fd, termios.TCIOFLUSH)


def read_exact(fd: int, expected_size: int, timeout: float) -> bytes:
    received = bytearray()
    deadline = time.monotonic() + timeout

    while len(received) < expected_size:
        remaining_time = deadline - time.monotonic()

        if remaining_time <= 0:
            break

        readable, _, _ = select.select([fd], [], [], remaining_time)

        if not readable:
            break

        chunk = os.read(fd, expected_size - len(received))

        if chunk:
            received.extend(chunk)

    return bytes(received)


def main() -> None:
    fd = os.open(
        PORT,
        os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK,
    )

    try:
        configure_uart(fd)

        print(f"Testing {PORT} at 115200 baud")
        print(f"Sending:  {TEST_DATA!r}")

        os.write(fd, TEST_DATA)
        termios.tcdrain(fd)

        received = read_exact(
            fd,
            expected_size=len(TEST_DATA),
            timeout=TIMEOUT_SECONDS,
        )

        print(f"Received: {received!r}")

        if received == TEST_DATA:
            print("PASS: UART TX and RX loopback works")
        elif not received:
            print("FAIL: No data received")
        else:
            print("FAIL: Received data does not match sent data")
            print("Sent hex:    ", TEST_DATA.hex(" "))
            print("Received hex:", received.hex(" "))

    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
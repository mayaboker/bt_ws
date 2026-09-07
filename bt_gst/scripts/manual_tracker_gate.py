#!/usr/bin/env python3
"""Control the bt-gst target gate directly, without bt_app dependencies."""

from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
import tty

import msgpack
import zmq


DISABLED = 0
SELECTING = 1
LOCKED = 2
ARROWS = {
    b"\x1b[A": (0.0, -1.0),
    b"\x1b[B": (0.0, 1.0),
    b"\x1b[C": (1.0, 0.0),
    b"\x1b[D": (-1.0, 0.0),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Move the bt-gst selector with arrow keys and press Space to request tracking."
        )
    )
    parser.add_argument("--endpoint", default="tcp://127.0.0.1:5557")
    parser.add_argument(
        "--connect", action="store_true", help="connect instead of bind"
    )
    parser.add_argument(
        "--step", type=float, default=0.025, help="normalized movement per key"
    )
    parser.add_argument("--rate-hz", type=float, default=20.0)
    parser.add_argument("--start-x", type=float, default=0.5)
    parser.add_argument("--start-y", type=float, default=0.5)
    parser.add_argument("--start-width", type=int, default=60)
    parser.add_argument("--start-height", type=int, default=90)
    parser.add_argument(
        "--size-step", type=int, default=5, help="ROI pixels per resize key"
    )
    args = parser.parse_args()
    if args.step <= 0 or args.step > 1:
        parser.error("--step must be greater than 0 and at most 1")
    if args.rate_hz <= 0:
        parser.error("--rate-hz must be greater than 0")
    if not 0 <= args.start_x <= 1 or not 0 <= args.start_y <= 1:
        parser.error("--start-x and --start-y must be between 0 and 1")
    if args.start_width <= 0 or args.start_height <= 0 or args.size_step <= 0:
        parser.error("gate dimensions and --size-step must be positive")
    return args


def encode_command(
    center_x: float, center_y: float, state: int, width: int, height: int
) -> bytes:
    return msgpack.packb(
        {
            "timestamp_ns": time.monotonic_ns(),
            "center_x": float(center_x),
            "center_y": float(center_y),
            "state": state,
            "roi_width": width,
            "roi_height": height,
        },
        use_bin_type=True,
    )


def read_key(fd: int, timeout_s: float) -> str | None:
    ready, _, _ = select.select([fd], [], [], timeout_s)
    if not ready:
        return None
    first = os.read(fd, 1)
    if first == b"\x1b":
        sequence = bytearray(first)
        for _ in range(2):
            ready, _, _ = select.select([fd], [], [], 0.01)
            if not ready:
                break
            sequence.extend(os.read(fd, 1))
        movement = ARROWS.get(bytes(sequence))
        if movement is not None:
            return bytes(sequence).decode("ascii")
    if first == b" ":
        return "lock"
    if first.lower() == b"r":
        return "resume"
    if first.lower() == b"q":
        return "quit"
    if first.lower() in (b"a", b"d", b"w", b"s"):
        return first.lower().decode("ascii")
    return None


def run(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty():
        print("ERROR: an interactive terminal is required", file=sys.stderr)
        return 2

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.setsockopt(zmq.LINGER, 0)
    try:
        if args.connect:
            socket.connect(args.endpoint)
            action = "Connected to"
        else:
            socket.bind(args.endpoint)
            action = "Bound"
    except zmq.ZMQError as exc:
        socket.close(linger=0)
        context.term()
        print(f"ERROR: cannot open {args.endpoint}: {exc}", file=sys.stderr)
        return 1

    fd = sys.stdin.fileno()
    saved_terminal = termios.tcgetattr(fd)
    center_x = args.start_x
    center_y = args.start_y
    state = SELECTING
    width = args.start_width
    height = args.start_height
    period_s = 1.0 / args.rate_hz
    print(f"{action} selector endpoint {args.endpoint}")
    print(
        "Arrows: move | A/D: width -/+ | S/W: height -/+ | Space: track | R: realign | Q: exit"
    )
    print(f"Gate center: x={center_x:.3f} y={center_y:.3f} size={width}x{height}")

    try:
        tty.setcbreak(fd)
        while True:
            socket.send(encode_command(center_x, center_y, state, width, height))
            key = read_key(fd, period_s)
            if key in ("\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D"):
                if state == LOCKED:
                    continue
                dx, dy = ARROWS[key.encode("ascii")]
                center_x = min(1.0, max(0.0, center_x + dx * args.step))
                center_y = min(1.0, max(0.0, center_y + dy * args.step))
                print(
                    f"\rGate center: x={center_x:.3f} y={center_y:.3f}   ",
                    end="",
                    flush=True,
                )
            elif key in ("a", "d", "w", "s") and state != LOCKED:
                if key == "a":
                    width = max(1, width - args.size_step)
                elif key == "d":
                    width += args.size_step
                elif key == "s":
                    height = max(1, height - args.size_step)
                else:
                    height += args.size_step
                print(
                    f"\rGate center: x={center_x:.3f} y={center_y:.3f} size={width}x{height}   ",
                    end="",
                    flush=True,
                )
            elif key == "lock":
                state = LOCKED
                print("\nTracking requested; press R to realign or Q to stop")
            elif key == "resume":
                state = SELECTING
                print("Alignment resumed")
            elif key == "quit":
                return 0
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    finally:
        for _ in range(3):
            try:
                socket.send(encode_command(center_x, center_y, DISABLED, width, height))
                time.sleep(period_s)
            except zmq.ZMQError:
                break
        termios.tcsetattr(fd, termios.TCSADRAIN, saved_terminal)
        socket.close(linger=0)
        context.term()


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

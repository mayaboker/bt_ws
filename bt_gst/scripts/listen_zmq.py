#!/usr/bin/env python3

import argparse

import zmq
from bt_msgs import TrackerResultMessage

DEFAULT_ENDPOINT = "tcp://127.0.0.1:5556"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print tracker-result messages published by bt-gst."
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"ZMQ PUB endpoint to connect to (default: {DEFAULT_ENDPOINT})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt(zmq.LINGER, 0)
    subscriber.setsockopt(zmq.RCVHWM, 1)
    subscriber.setsockopt(zmq.SUBSCRIBE, b"")
    subscriber.connect(args.endpoint)

    print(f"Listening for bt-gst tracker results on {args.endpoint}")
    try:
        while True:
            payload = subscriber.recv()
            try:
                message = TrackerResultMessage.decode(payload)
            except (TypeError, ValueError, KeyError) as exc:
                print(f"Ignored invalid message: {exc}")
                continue
            print(
                f"frame_id={message.frame_id} "
                f"timestamp={message.timestamp}"
            )
    except KeyboardInterrupt:
        print("Stopped")
        return 0
    finally:
        subscriber.close(linger=0)
        context.term()


if __name__ == "__main__":
    raise SystemExit(main())

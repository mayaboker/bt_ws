#!/usr/bin/env python3

import argparse

import zmq
from loguru import logger

from bt_app.common import ZMQ_TRACKER_RESULT_ENDPOINT, ZMQ_TRACKER_RESULT_TOPIC
from bt_app.msgs import unpack_tracker_result


class TrackerResultClient:
    """Simple ZMQ SUB client that prints TrackerResult payloads."""

    def __init__(
        self,
        *,
        result_endpoint=ZMQ_TRACKER_RESULT_ENDPOINT,
        result_topic=ZMQ_TRACKER_RESULT_TOPIC,
        context=None,
    ):
        self.result_endpoint = result_endpoint
        self.result_topic = result_topic
        self.context = context or zmq.Context.instance()
        self.subscriber = None

    def start(self):
        if self.subscriber is not None:
            return

        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.setsockopt(zmq.LINGER, 0)
        self.subscriber.setsockopt(zmq.RCVHWM, 2)
        self.subscriber.setsockopt(zmq.SUBSCRIBE, self.result_topic)
        self.subscriber.connect(self.result_endpoint)
        logger.info(
            "Subscribed to tracker results from {} on topic {}",
            self.result_endpoint,
            self.result_topic.decode("utf-8", errors="replace"),
        )

    def spin(self, timeout_ms=100):
        self.start()
        poller = zmq.Poller()
        poller.register(self.subscriber, zmq.POLLIN)

        try:
            while True:
                events = dict(poller.poll(timeout_ms))
                if self.subscriber not in events:
                    continue

                _topic, payload = self.subscriber.recv_multipart()
                result = unpack_tracker_result(payload)
                print(result)
        finally:
            self.close()

    def close(self):
        if self.subscriber is not None:
            self.subscriber.close(linger=0)
            self.subscriber = None


def parse_args():
    parser = argparse.ArgumentParser(description="Print tracker results from ZMQ.")
    parser.add_argument("--result-endpoint", default=ZMQ_TRACKER_RESULT_ENDPOINT)
    return parser.parse_args()


def main():
    args = parse_args()
    TrackerResultClient(result_endpoint=args.result_endpoint).spin()


if __name__ == "__main__":
    main()

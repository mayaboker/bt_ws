#!/usr/bin/env python3

import argparse
import json
import queue
import signal

import gz.transport13 as gz_transport
import zmq
from gz.msgs10 import laserscan_pb2
from loguru import logger

from bt_app.common import (
    GAZEBO_ULTRASONIC_LIDAR_TOPIC,
    ZMQ_ULTRASONIC_LIDAR_ENDPOINT,
    ZMQ_ULTRASONIC_LIDAR_TOPIC,
)


class GazeboLidarPublisher:
    """Bridge Gazebo LaserScan messages to a ZMQ PUB socket."""

    def __init__(
        self,
        *,
        gazebo_topic=GAZEBO_ULTRASONIC_LIDAR_TOPIC,
        zmq_endpoint=ZMQ_ULTRASONIC_LIDAR_ENDPOINT,
        zmq_topic=ZMQ_ULTRASONIC_LIDAR_TOPIC,
        context=None,
    ):
        self.gazebo_topic = gazebo_topic
        self.zmq_endpoint = zmq_endpoint
        self.zmq_topic = zmq_topic
        self.context = context or zmq.Context.instance()
        self.node = gz_transport.Node()
        self.publisher = None
        self.scans = queue.Queue(maxsize=1)
        self.scan_count = 0
        self.started = False

    def start(self):
        if self.started:
            return

        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.setsockopt(zmq.SNDHWM, 1)
        self.publisher.bind(self.zmq_endpoint)
        self.node.subscribe(laserscan_pb2.LaserScan, self.gazebo_topic, self._on_scan)
        self.started = True
        logger.info(
            "Publishing Gazebo lidar {} to ZMQ {} on topic {}",
            self.gazebo_topic,
            self.zmq_endpoint,
            self.zmq_topic.decode("utf-8", errors="replace"),
        )

    def close(self):
        if self.publisher is not None:
            self.publisher.close(linger=0)
            self.publisher = None
        self.started = False

    def spin(
        self,
        poll_interval_s=0.01,
        install_signal_handlers=True,
        stop_event=None,
    ):
        stop = False

        def stop_handler(signum, _frame):
            nonlocal stop
            logger.info("Stopping lidar publisher after signal {}", signum)
            stop = True

        if install_signal_handlers:
            signal.signal(signal.SIGINT, stop_handler)
            signal.signal(signal.SIGTERM, stop_handler)

        self.start()
        try:
            while not stop and not (stop_event is not None and stop_event.is_set()):
                self.publish_pending(timeout_s=poll_interval_s)
        finally:
            self.close()

    def publish_pending(self, timeout_s=0.0):
        if self.publisher is None:
            raise RuntimeError("GazeboLidarPublisher.start() must be called before publish")

        try:
            latest = self.scans.get(timeout=timeout_s)
        except queue.Empty:
            return

        while True:
            try:
                latest = self.scans.get_nowait()
            except queue.Empty:
                break

        metadata, measurement = latest
        try:
            self.publisher.send_multipart(
                [
                    self.zmq_topic,
                    json.dumps(metadata).encode("utf-8"),
                    json.dumps(measurement).encode("utf-8"),
                ],
                flags=zmq.DONTWAIT,
            )
        except zmq.Again:
            logger.debug("Dropped lidar scan {} because ZMQ send queue is full", metadata["scan"])

    def _on_scan(self, msg):
        metadata = {
            "frame": msg.frame,
            "scan": self.scan_count,
            "angle_min": msg.angle_min,
            "angle_max": msg.angle_max,
            "angle_step": msg.angle_step,
            "range_min": msg.range_min,
            "range_max": msg.range_max,
        }
        self.scan_count += 1

        measurement = {
            "range": float(msg.ranges[0]) if msg.ranges else None,
        }
        scan = (metadata, measurement)
        try:
            self.scans.put_nowait(scan)
        except queue.Full:
            try:
                self.scans.get_nowait()
            except queue.Empty:
                pass
            try:
                self.scans.put_nowait(scan)
            except queue.Full:
                pass


def parse_args():
    parser = argparse.ArgumentParser(
        description="Publish Gazebo Harmonic lidar scans to a ZMQ PUB socket."
    )
    parser.add_argument("--gazebo-topic", default=GAZEBO_ULTRASONIC_LIDAR_TOPIC)
    parser.add_argument("--zmq-endpoint", default=ZMQ_ULTRASONIC_LIDAR_ENDPOINT)
    return parser.parse_args()


def main():
    args = parse_args()
    publisher = GazeboLidarPublisher(
        gazebo_topic=args.gazebo_topic,
        zmq_endpoint=args.zmq_endpoint,
    )
    publisher.spin()


if __name__ == "__main__":
    main()

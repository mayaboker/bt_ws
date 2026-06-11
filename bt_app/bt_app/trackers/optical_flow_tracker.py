#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import json
import math
import threading

import cv2
import numpy as np
import zmq
from loguru import logger

from bt_app.common import (
    GAZEBO_CAMERA_TOPIC,
    ZMQ_CAMERA_ENDPOINT,
    ZMQ_CAMERA_TOPIC,
    ZMQ_TRACKER_RESULT_ENDPOINT,
    ZMQ_TRACKER_RESULT_TOPIC,
)
from bt_app.msgs import TrackerResult, pack_tracker_result
from bt_app.sensors.gz_camera import GazeboCameraPublisher
from bt_app.trackers.red_box_tracker import (
    CAMERA_HORIZONTAL_FOV_RAD,
    TRACKER_STATE_LOST,
    TRACKER_STATE_TRACKING,
    clamp,
    draw_crosshair,
    image_to_bgr,
    vertical_fov_from_horizontal,
)


DEFAULT_OPTICAL_FLOW_TRACKER_WINDOW = "Optical Flow Tracker"
TRACKER_ID = "optical_flow"


@dataclass(frozen=True)
class OpticalFlowDetection:
    center_px: tuple[int, int]
    feature_count: int
    error_px: tuple[float, float]
    tracker_result: TrackerResult
    error_angle_rad: tuple[float, float]
    error_angle_deg: tuple[float, float]


class OpticalFlowTracker:
    """Track good image features with Lucas-Kanade optical flow."""

    def __init__(
        self,
        *,
        zmq_endpoint=ZMQ_CAMERA_ENDPOINT,
        zmq_topic=ZMQ_CAMERA_TOPIC,
        result_endpoint=ZMQ_TRACKER_RESULT_ENDPOINT,
        result_topic=ZMQ_TRACKER_RESULT_TOPIC,
        horizontal_fov_rad=CAMERA_HORIZONTAL_FOV_RAD,
        max_corners=80,
        quality_level=0.01,
        min_distance_px=10,
        min_features=8,
        display=True,
        window_name=DEFAULT_OPTICAL_FLOW_TRACKER_WINDOW,
        context=None,
    ):
        self.zmq_endpoint = zmq_endpoint
        self.zmq_topic = zmq_topic
        self.result_endpoint = result_endpoint
        self.result_topic = result_topic
        self.horizontal_fov_rad = horizontal_fov_rad
        self.max_corners = max_corners
        self.quality_level = quality_level
        self.min_distance_px = min_distance_px
        self.min_features = min_features
        self.display = display
        self.window_name = window_name
        self.context = context or zmq.Context.instance()
        self.subscriber = self.context.socket(zmq.SUB)
        self.subscriber.setsockopt(zmq.RCVHWM, 1)
        self.subscriber.setsockopt(zmq.SUBSCRIBE, self.zmq_topic)
        self.result_publisher = None
        self.prev_gray = None
        self.prev_points = None

    def start(self):
        self.result_publisher = self.context.socket(zmq.PUB)
        self.result_publisher.setsockopt(zmq.SNDHWM, 2)
        self.result_publisher.bind(self.result_endpoint)
        self.subscriber.connect(self.zmq_endpoint)
        logger.info(
            "Optical flow tracker subscribed to {} on topic {}",
            self.zmq_endpoint,
            self.zmq_topic.decode("utf-8", errors="replace"),
        )
        logger.info(
            "Optical flow tracker publishing results to {} on topic {}",
            self.result_endpoint,
            self.result_topic.decode("utf-8", errors="replace"),
        )

    def close(self):
        self.subscriber.close(linger=0)
        if self.result_publisher is not None:
            self.result_publisher.close(linger=0)
            self.result_publisher = None
        if self.display:
            cv2.destroyAllWindows()

    def spin(self, timeout_ms=100):
        self.start()
        poller = zmq.Poller()
        poller.register(self.subscriber, zmq.POLLIN)

        try:
            while True:
                events = dict(poller.poll(timeout_ms))
                if self.subscriber in events:
                    _topic, metadata_bytes, image_bytes = self.recv_latest_frame()
                    metadata = json.loads(metadata_bytes.decode("utf-8"))
                    frame = image_to_bgr(metadata, image_bytes)
                    detection = self.update_flow(frame)
                    self.handle_detection(frame, detection)

                if self.display:
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        logger.info("Stopping optical flow tracker")
                        break
        finally:
            self.close()

    def update_flow(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None or self.prev_points is None:
            self.reset_features(gray)
            return None

        next_points, status, _error = cv2.calcOpticalFlowPyrLK(
            self.prev_gray,
            gray,
            self.prev_points,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(
                cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                30,
                0.01,
            ),
        )

        if next_points is None or status is None:
            self.reset_features(gray)
            return None

        good_points = next_points[status.reshape(-1) == 1]
        self.prev_gray = gray
        self.prev_points = good_points.reshape(-1, 1, 2)

        if len(good_points) < self.min_features:
            self.reset_features(gray)
            return None

        return optical_flow_detection_from_points(
            good_points,
            frame.shape[1],
            frame.shape[0],
            self.horizontal_fov_rad,
            self.max_corners,
        )

    def reset_features(self, gray):
        self.prev_gray = gray
        self.prev_points = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=self.max_corners,
            qualityLevel=self.quality_level,
            minDistance=self.min_distance_px,
            blockSize=7,
        )

    def handle_detection(self, frame, detection):
        if detection is None:
            self.publish_tracker_result(
                TrackerResult(
                    error_x=0.0,
                    error_y=0.0,
                    state=TRACKER_STATE_LOST,
                    score=0,
                    tracker_id=TRACKER_ID,
                )
            )
            logger.debug("No optical flow result")
            if self.display:
                draw_crosshair(frame)
                cv2.imshow(self.window_name, frame)
            return

        self.publish_tracker_result(detection.tracker_result)
        logger.debug(
            "optical_flow center_px={} features={} error_px=({:.1f}, {:.1f}) "
            "error_angle_deg=({:.2f}, {:.2f})",
            detection.center_px,
            detection.feature_count,
            detection.error_px[0],
            detection.error_px[1],
            detection.error_angle_deg[0],
            detection.error_angle_deg[1],
        )

        if self.display:
            draw_detection(frame, detection, self.prev_points)
            cv2.imshow(self.window_name, frame)

    def publish_tracker_result(self, tracker_result):
        if self.result_publisher is None:
            raise RuntimeError("OpticalFlowTracker.start() must be called before publish")

        payload = pack_tracker_result(tracker_result)
        self.result_publisher.send_multipart([self.result_topic, payload])
        logger.debug("Published tracker result {}", tracker_result)

    def recv_latest_frame(self):
        latest = self.subscriber.recv_multipart()

        while True:
            try:
                latest = self.subscriber.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                return latest


def optical_flow_detection_from_points(
    points,
    width,
    height,
    horizontal_fov_rad,
    max_corners,
):
    center_x = float(np.mean(points[:, 0]))
    center_y = float(np.mean(points[:, 1]))
    error_x_px = center_x - (width / 2.0)
    error_y_px = (height / 2.0) - center_y

    vertical_fov_rad = vertical_fov_from_horizontal(
        horizontal_fov_rad,
        width,
        height,
    )
    error_x_rad = (error_x_px / (width / 2.0)) * (horizontal_fov_rad / 2.0)
    error_y_rad = (error_y_px / (height / 2.0)) * (vertical_fov_rad / 2.0)

    return OpticalFlowDetection(
        center_px=(int(round(center_x)), int(round(center_y))),
        feature_count=len(points),
        error_px=(error_x_px, error_y_px),
        tracker_result=TrackerResult(
            error_x=error_x_rad,
            error_y=error_y_rad,
            state=TRACKER_STATE_TRACKING,
            score=int(
                round(
                    clamp(
                        len(points) / max(max_corners, 1) * 100.0,
                        0.0,
                        100.0,
                    )
                )
            ),
            tracker_id=TRACKER_ID,
        ),
        error_angle_rad=(error_x_rad, error_y_rad),
        error_angle_deg=(math.degrees(error_x_rad), math.degrees(error_y_rad)),
    )


def draw_detection(frame, detection, points):
    draw_crosshair(frame)
    if points is not None:
        for point in points.reshape(-1, 2):
            cv2.circle(
                frame,
                (int(round(point[0])), int(round(point[1]))),
                2,
                (0, 255, 0),
                -1,
            )

    cx, cy = detection.center_px
    cv2.circle(frame, (cx, cy), 5, (0, 255, 255), -1)
    cv2.putText(
        frame,
        (
            f"err deg x={detection.error_angle_deg[0]:.2f} "
            f"y={detection.error_angle_deg[1]:.2f} n={detection.feature_count} "
            f"score={detection.tracker_result.score}"
        ),
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Track good image features with optical flow in the Gazebo camera stream."
    )
    parser.add_argument("--zmq-endpoint", default=ZMQ_CAMERA_ENDPOINT)
    parser.add_argument("--result-endpoint", default=ZMQ_TRACKER_RESULT_ENDPOINT)
    parser.add_argument("--gazebo-topic", default=GAZEBO_CAMERA_TOPIC)
    parser.add_argument("--window", default=DEFAULT_OPTICAL_FLOW_TRACKER_WINDOW)
    parser.add_argument("--horizontal-fov", type=float, default=CAMERA_HORIZONTAL_FOV_RAD)
    parser.add_argument("--max-corners", type=int, default=80)
    parser.add_argument("--quality-level", type=float, default=0.01)
    parser.add_argument("--min-distance", type=float, default=10.0)
    parser.add_argument("--min-features", type=int, default=8)
    parser.add_argument("--no-display", action="store_true")
    parser.add_argument(
        "--no-camera-publisher",
        action="store_true",
        help="Only subscribe to ZMQ. Use this when another publisher is already running.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    context = zmq.Context.instance()
    publisher_stop = None
    publisher_thread = None

    if not args.no_camera_publisher:
        publisher_stop = threading.Event()
        publisher = GazeboCameraPublisher(
            gazebo_topic=args.gazebo_topic,
            zmq_endpoint=args.zmq_endpoint,
            context=context,
        )
        publisher_thread = threading.Thread(
            target=publisher.spin,
            kwargs={
                "install_signal_handlers": False,
                "stop_event": publisher_stop,
            },
            daemon=True,
        )
        publisher_thread.start()

    tracker = OpticalFlowTracker(
        zmq_endpoint=args.zmq_endpoint,
        result_endpoint=args.result_endpoint,
        horizontal_fov_rad=args.horizontal_fov,
        max_corners=args.max_corners,
        quality_level=args.quality_level,
        min_distance_px=args.min_distance,
        min_features=args.min_features,
        display=not args.no_display,
        window_name=args.window,
        context=context,
    )

    try:
        tracker.spin()
    finally:
        if publisher_stop is not None:
            publisher_stop.set()
        if publisher_thread is not None:
            publisher_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()

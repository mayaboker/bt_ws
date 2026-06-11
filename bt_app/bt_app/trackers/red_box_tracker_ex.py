#!/usr/bin/env python3

import argparse
import json
import math
import threading
import time
from dataclasses import dataclass
from typing import NamedTuple

from gz.msgs10 import image_pb2
import cv2
import numpy as np
import zmq
from loguru import logger
from collections import deque
import gz.transport13 as gz_transport


from bt_app.common import (
    GAZEBO_CAMERA_TOPIC,
    ZMQ_TRACKER_RESULT_ENDPOINT,
    ZMQ_TRACKER_RESULT_TOPIC,
)
from bt_app.msgs import TrackerResult, pack_tracker_result
from bt_app.trackers.red_box_tracker import (
    TRACKER_ID,
    TRACKER_STATE_LOST,
    TRACKER_STATE_TRACKING,
    detection_quality_score,
)
from bt_app.trackers.tracker_result_client import TrackerResultClient


DEFAULT_RED_BOX_TRACKER_WINDOW = "Red Box Tracker"
CAMERA_HORIZONTAL_FOV_RAD = 1.570796  # 90 degrees

PIXEL_FORMAT_NAMES = {
    value.number: value.name
    for value in image_pb2.PixelFormatType.DESCRIPTOR.values
}

#region Image processing and detection
def image_buffer(data, height, width, step, channels):
    row_bytes = width * channels
    step = step or row_bytes

    if step < row_bytes:
        raise ValueError(
            f"Image step {step} is smaller than row size {row_bytes}"
        )

    expected_size = step * height
    if len(data) < expected_size:
        raise ValueError(
            f"Image data too short: got {len(data)} bytes, need {expected_size}"
        )

    image = np.frombuffer(data, dtype=np.uint8, count=expected_size)
    image = image.reshape((height, step))[:, :row_bytes]
    return image.reshape((height, width, channels))

def image_to_bgr(metadata, data):
    width = metadata["width"]
    height = metadata["height"]
    step = metadata["step"]
    pixel_format = metadata["pixel_format_type"]

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid image size: {width}x{height}")

    if pixel_format == image_pb2.RGB_INT8:
        image = image_buffer(data, height, width, step, 3)
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    if pixel_format == image_pb2.BGR_INT8:
        return image_buffer(data, height, width, step, 3)

    if pixel_format == image_pb2.RGBA_INT8:
        image = image_buffer(data, height, width, step, 4)
        return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)

    if pixel_format == image_pb2.BGRA_INT8:
        image = image_buffer(data, height, width, step, 4)
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    if pixel_format == image_pb2.L_INT8:
        gray = image_buffer(data, height, width, step, 1).reshape((height, width))
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    name = PIXEL_FORMAT_NAMES.get(pixel_format, f"UNKNOWN({pixel_format})")
    raise ValueError(f"Unsupported Gazebo image pixel format: {name}")

def vertical_fov_from_horizontal(horizontal_fov_rad, width, height):
    aspect_height_over_width = height / width
    return 2.0 * math.atan(
        math.tan(horizontal_fov_rad / 2.0) * aspect_height_over_width
    )

def detect_red_box(frame, *, horizontal_fov_rad, min_area_px):
    height, width = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    lower_red_1 = np.array([0, 80, 60], dtype=np.uint8)
    upper_red_1 = np.array([10, 255, 255], dtype=np.uint8)
    lower_red_2 = np.array([170, 80, 60], dtype=np.uint8)
    upper_red_2 = np.array([179, 255, 255], dtype=np.uint8)

    mask_1 = cv2.inRange(hsv, lower_red_1, upper_red_1)
    mask_2 = cv2.inRange(hsv, lower_red_2, upper_red_2)
    mask = cv2.bitwise_or(mask_1, mask_2)

    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _hierarchy = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(contour)
    if area < min_area_px:
        return None

    x, y, w, h = cv2.boundingRect(contour)
    center_x = x + w // 2
    center_y = y + h // 2
    error_x_px = center_x - (width / 2.0)
    error_y_px = (height / 2.0) - center_y

    vertical_fov_rad = vertical_fov_from_horizontal(
        horizontal_fov_rad,
        width,
        height,
    )
    error_x_rad = (error_x_px / (width / 2.0)) * (horizontal_fov_rad / 2.0)
    error_y_rad = (error_y_px / (height / 2.0)) * (vertical_fov_rad / 2.0)
    score = detection_quality_score(
        area_px=area,
        min_area_px=min_area_px,
        error_px=(error_x_px, error_y_px),
        width=width,
        height=height,
    )

    return RedBoxDetection(
        center_px=(center_x, center_y),
        bbox=(x, y, w, h),
        area_px=area,
        error_px=(error_x_px, error_y_px),
        tracker_result=TrackerResult(
            error_x=error_x_rad,
            error_y=error_y_rad,
            state=TRACKER_STATE_TRACKING,
            score=score,
            tracker_id=TRACKER_ID,
        ),
        error_angle_rad=(error_x_rad, error_y_rad),
        error_angle_deg=(math.degrees(error_x_rad), math.degrees(error_y_rad)),
    )


@dataclass(frozen=True)
class RedBoxDetection:
    center_px: tuple[int, int]
    bbox: tuple[int, int, int, int]
    area_px: float
    error_px: tuple[float, float]
    tracker_result: TrackerResult
    error_angle_rad: tuple[float, float]
    error_angle_deg: tuple[float, float]
# endregion

class CameraFrame(NamedTuple):
    metadata: dict
    data: bytes


class ImageTransport:
    """Own ZMQ sockets and camera/result serialization."""

    def __init__(
        self,
        *,
        gazebo_topic=GAZEBO_CAMERA_TOPIC,
    ):
        self.gazebo_topic = gazebo_topic
        self.node = None
        self.frame_count = 0
        self.img_queue = deque(maxlen=1)
        self.data_event = threading.Event()
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.start_error = None

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return

        self.stop_event.clear()
        self.ready_event.clear()
        self.start_error = None
        self.thread = threading.Thread(
            target=self._run,
            name="image-transport",
            daemon=True,
        )
        self.thread.start()

        if not self.ready_event.wait(timeout=2.0):
            self.close()
            raise RuntimeError("Timed out waiting for image transport thread to start")
        if self.start_error is not None:
            self.close()
            raise self.start_error

    def _run(self):
        try:
            self.node = gz_transport.Node()
            subscribed = self.node.subscribe(
                image_pb2.Image,
                self.gazebo_topic,
                self._on_image,
            )
            if subscribed is False:
                raise RuntimeError(f"Failed to subscribe to {self.gazebo_topic}")
        except Exception as exc:
            self.start_error = exc
            self.ready_event.set()
            return

        self.ready_event.set()
        while not self.stop_event.is_set():
            self.stop_event.wait(timeout=0.1)

    def _on_image(self, msg):
        logger.info("Received image on thread {}", threading.current_thread().name)
        self.frame_count += 1
        metadata = {
            "width": msg.width,
            "height": msg.height,
            "step": msg.step,
            "pixel_format_type": msg.pixel_format_type,
            "frame": self.frame_count,
        }

        with self.lock:
            self.img_queue.append(CameraFrame(metadata=metadata, data=msg.data))
        self.data_event.set()

    def get_latest_frame(self, timeout=1.0):
        if not self.data_event.wait(timeout=timeout):
            return None

        self.data_event.clear()
        with self.lock:
            if not self.img_queue:
                return None
            return self.img_queue.pop()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
            if self.thread.is_alive():
                logger.warning("Image transport thread did not stop cleanly")
            else:
                self.thread = None
        self.node = None


class TrackerResultTransport:
    """Own the ZMQ PUB socket and TrackerResult serialization."""

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
        self.publisher = None

    def start(self):
        if self.publisher is not None:
            return

        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.setsockopt(zmq.LINGER, 0)
        self.publisher.setsockopt(zmq.SNDHWM, 2)
        self.publisher.bind(self.result_endpoint)
        logger.info(
            "Publishing tracker results to {} on topic {}",
            self.result_endpoint,
            self.result_topic.decode("utf-8", errors="replace"),
        )

    def publish(self, tracker_result):
        if self.publisher is None:
            raise RuntimeError("TrackerResultTransport.start() must be called before publish")

        payload = pack_tracker_result(tracker_result)
        try:
            self.publisher.send_multipart(
                [self.result_topic, payload],
                flags=zmq.DONTWAIT,
            )
        except zmq.Again:
            logger.debug("Dropped tracker result because ZMQ send queue is full")

    def close(self):
        if self.publisher is not None:
            self.publisher.close(linger=0)
            self.publisher = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Track a red box in the Gazebo camera stream."
    )
    parser.add_argument("--result-endpoint", default=ZMQ_TRACKER_RESULT_ENDPOINT)
    parser.add_argument("--gazebo-topic", default=GAZEBO_CAMERA_TOPIC)
    parser.add_argument(
        "--print-results",
        action="store_true",
        help="Subscribe to tracker results and print them to the console.",
    )
    
    return parser.parse_args()

def image_buffer(data, height, width, step, channels):
    row_bytes = width * channels
    step = step or row_bytes

    if step < row_bytes:
        raise ValueError(
            f"Image step {step} is smaller than row size {row_bytes}"
        )

    expected_size = step * height
    if len(data) < expected_size:
        raise ValueError(
            f"Image data too short: got {len(data)} bytes, need {expected_size}"
        )

    image = np.frombuffer(data, dtype=np.uint8, count=expected_size)
    image = image.reshape((height, step))[:, :row_bytes]
    return image.reshape((height, width, channels))

def draw_fps(frame, fps):
    cv2.putText(
        frame,
        f"FPS: {fps:.1f}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
def draw_crosshair(frame):
    height, width = frame.shape[:2]
    center = (width // 2, height // 2)
    cv2.drawMarker(
        frame,
        center,
        (255, 255, 255),
        markerType=cv2.MARKER_CROSS,
        markerSize=24,
        thickness=1,
    )

def draw_detection(frame, detection):
    draw_crosshair(frame)
    x, y, w, h = detection.bbox
    cx, cy = detection.center_px
    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.circle(frame, (cx, cy), 4, (0, 255, 255), -1)
    cv2.putText(
        frame,
        f"err deg x={detection.error_angle_deg[0]:.2f} y={detection.error_angle_deg[1]:.2f}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )

def main():
    args = parse_args()

    if args.print_results:
        TrackerResultClient(result_endpoint=args.result_endpoint).spin()
        return

    img_transport = ImageTransport(gazebo_topic = args.gazebo_topic)
    result_transport = TrackerResultTransport(result_endpoint=args.result_endpoint)
    img_transport.start()
    result_transport.start()
    last_frame_time = None
    fps = 0.0

    try:
        while True:
            camera_frame = img_transport.get_latest_frame(timeout=1.0)
            if camera_frame is None:
                logger.warning("No image received in 1 second, still waiting...")
                continue

            frame = image_to_bgr(camera_frame.metadata, camera_frame.data)
            now = time.monotonic()
            if last_frame_time is not None:
                dt = now - last_frame_time
                if dt > 0.0:
                    current_fps = 1.0 / dt
                    fps = current_fps if fps == 0.0 else (0.9 * fps) + (0.1 * current_fps)
            last_frame_time = now

            draw_fps(frame, fps)
            logger.info(f"Processing frame {camera_frame.metadata['frame']}")
            result = detect_red_box(frame, horizontal_fov_rad=CAMERA_HORIZONTAL_FOV_RAD, min_area_px=500)
            if result is not None:
                result_transport.publish(result.tracker_result)
                draw_detection(frame, result)
            else:
                result_transport.publish(
                    TrackerResult(
                        error_x=0.0,
                        error_y=0.0,
                        state=TRACKER_STATE_LOST,
                        score=0,
                        tracker_id=TRACKER_ID,
                    )
                )
                draw_crosshair(frame)
            if True:
                cv2.imshow("test", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    logger.info("Stopping red box tracker")
                    break
    finally:
        result_transport.close()
        img_transport.close()
        cv2.destroyAllWindows()




if __name__ == "__main__":
    main()

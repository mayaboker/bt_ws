# subscribe to gz camera topic and publish the image data to zmq image topic
# the topic is /iris/camera/image
# 

#!/usr/bin/env python3

from __future__ import annotations

import click
import json
import signal
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque
import zmq
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image
from gz.msgs10 import image_pb2

from loguru import logger

from bt_app.common import (
    GAZEBO_CAMERA_TOPIC,
    ZMQ_CAMERA_ENDPOINT,
    ZMQ_CAMERA_TOPIC,
)


@dataclass(frozen=True)
class CameraFrame:
    metadata: dict
    data: bytes


PIXEL_FORMAT_NAMES = {
    value.number: value.name
    for value in image_pb2.PixelFormatType.DESCRIPTOR.values
}


def image_buffer(data, height, width, step, channels):
    import numpy as np

    row_bytes = width * channels
    step = step or row_bytes

    if step < row_bytes:
        raise ValueError(f"Image step {step} is smaller than row size {row_bytes}")

    expected_size = step * height
    if len(data) < expected_size:
        raise ValueError(
            f"Image data too short: got {len(data)} bytes, need {expected_size}"
        )

    image = np.frombuffer(data, dtype=np.uint8, count=expected_size)
    image = image.reshape((height, step))[:, :row_bytes]
    return image.reshape((height, width, channels))


def image_to_bgr(metadata, data):
    import cv2

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


class GazeboCameraSource:
    """Subscribe to Gazebo camera images and push parsed frames into a queue."""

    def __init__(
        self,
        *,
        gazebo_topic=GAZEBO_CAMERA_TOPIC,
        frames: Deque[CameraFrame] | None = None,
        lock: threading.Lock | None = None,
    ):
        self.gazebo_topic = gazebo_topic
        self.frames = frames if frames is not None else deque(maxlen=1)
        self.lock = lock or threading.Lock()
        self.node = None
        self.frame_count = 0
        self.started = False
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = None

    def start(self):
        if self.started:
            return

        self._stop_event.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            name="gazebo-camera-source",
            daemon=True,
        )
        self._thread.start()

        if not self._ready.wait(timeout=2.0):
            self.close()
            raise RuntimeError("Timed out waiting for Gazebo camera source to start")
        if self._error is not None:
            self.close()
            raise self._error

        self.started = True
        logger.info("Subscribed to Gazebo camera {}", self.gazebo_topic)

    def close(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("Gazebo camera source thread did not stop cleanly")
            else:
                self._thread = None
        self.node = None
        self.started = False

    def wait(self, timeout: float) -> bool:
        return self._stop_event.wait(timeout=timeout)

    def _run(self):
        try:
            self.node = Node()
            subscribed = self.node.subscribe(
                image_pb2.Image,
                self.gazebo_topic,
                self._on_image,
            )
            if subscribed is False:
                raise RuntimeError(f"Failed to subscribe to {self.gazebo_topic}")
        except Exception as exc:
            self._error = exc
            self._ready.set()
            return

        self._ready.set()
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=0.1)

    def _on_image(self, msg):
        frame = self._parse_image(msg)
        with self.lock:
            self.frames.append(frame)

    def _parse_image(self, msg) -> CameraFrame:
        metadata = {
            "width": msg.width,
            "height": msg.height,
            "step": msg.step,
            "pixel_format_type": msg.pixel_format_type,
            "frame": self.frame_count,
        }
        self.frame_count += 1
        return CameraFrame(metadata=metadata, data=bytes(msg.data))


class ZmqCameraPublisher:
    """Publish the latest queued camera frame to ZMQ."""

    def __init__(
        self,
        *,
        zmq_endpoint=ZMQ_CAMERA_ENDPOINT,
        zmq_topic=ZMQ_CAMERA_TOPIC,
        frames: Deque[CameraFrame] | None = None,
        lock: threading.Lock | None = None,
        context=None,
    ):
        self.zmq_endpoint = zmq_endpoint
        self.zmq_topic = zmq_topic
        self.frames = frames if frames is not None else deque(maxlen=1)
        self.lock = lock or threading.Lock()
        self.context = context or zmq.Context.instance()
        self.publisher = None
        self.started = False
        self._stop_event = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = None

    def start(self):
        if self.started:
            return

        self._stop_event.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._publish_loop,
            name="gazebo-camera-zmq-publisher",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=2.0):
            self._stop_event.set()
            self._thread.join(timeout=1.0)
            self._thread = None
            raise RuntimeError("Timed out waiting for camera ZMQ publisher to start")
        if self._error is not None:
            self._stop_event.set()
            self._thread.join(timeout=1.0)
            self._thread = None
            raise self._error

        self.started = True
        logger.info(
            "Publishing camera frames to ZMQ {} on topic {}",
            self.zmq_endpoint,
            self.zmq_topic.decode("utf-8", errors="replace"),
        )

    def close(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("Camera publisher thread did not stop cleanly")
            else:
                self._thread = None
        self.started = False

    def wait(self, timeout: float) -> bool:
        return self._stop_event.wait(timeout=timeout)

    def publish_pending(self):
        if self.publisher is None:
            raise RuntimeError("ZmqCameraPublisher.start() must be called before publish")

        with self.lock:
            if not self.frames:
                return
            latest = self.frames.pop()
            self.frames.clear()

        if latest is None:
            return

        try:
            self.publisher.send_multipart(
                [
                    self.zmq_topic,
                    json.dumps(latest.metadata).encode("utf-8"),
                    latest.data,
                ],
                flags=zmq.DONTWAIT,
            )
        except zmq.Again:
            logger.debug(
                "Dropped camera frame {} because ZMQ send queue is full",
                latest.metadata["frame"],
            )

    def _publish_loop(self):
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.setsockopt(zmq.LINGER, 0)
        self.publisher.setsockopt(zmq.SNDHWM, 1)

        try:
            self.publisher.bind(self.zmq_endpoint)
        except zmq.ZMQError as exc:
            self._error = exc
            self._ready.set()
            self.publisher.close(linger=0)
            self.publisher = None
            return

        self._ready.set()
        try:
            while not self._stop_event.is_set():
                self.publish_pending()
                self._stop_event.wait(timeout=0.01)
        finally:
            if self.publisher is not None:
                self.publisher.close(linger=0)
                self.publisher = None


class OpenCvCameraViewer:
    """Display the latest queued camera frame without publishing it to ZMQ."""

    def __init__(
        self,
        *,
        frames: Deque[CameraFrame] | None = None,
        lock: threading.Lock | None = None,
        window_name="Gazebo Camera",
    ):
        self.frames = frames if frames is not None else deque(maxlen=1)
        self.lock = lock or threading.Lock()
        self.window_name = window_name

    def display_pending(self) -> bool:
        import cv2

        with self.lock:
            if not self.frames:
                return True
            latest = self.frames.pop()
            self.frames.clear()

        frame = image_to_bgr(latest.metadata, latest.data)
        cv2.imshow(self.window_name, frame)
        logger.debug("Displayed Gazebo camera frame {}", latest.metadata["frame"])

        key = cv2.waitKey(1) & 0xFF
        return key not in (ord("q"), 27)

    def close(self):
        import cv2

        try:
            cv2.destroyWindow(self.window_name)
        except cv2.error:
            pass


class GazeboCameraPublisher:
    """Coordinate Gazebo camera subscription and ZMQ publishing."""

    def __init__(
        self,
        *,
        gazebo_topic=GAZEBO_CAMERA_TOPIC,
        zmq_endpoint=ZMQ_CAMERA_ENDPOINT,
        zmq_topic=ZMQ_CAMERA_TOPIC,
        context=None,
    ):
        logger.info("gz camera bridge")
        self.frames = deque(maxlen=1)
        self.lock = threading.Lock()
        self.source = GazeboCameraSource(
            gazebo_topic=gazebo_topic,
            frames=self.frames,
            lock=self.lock,
        )
        self.publisher = ZmqCameraPublisher(
            zmq_endpoint=zmq_endpoint,
            zmq_topic=zmq_topic,
            frames=self.frames,
            lock=self.lock,
            context=context,
        )
        self.gazebo_topic = gazebo_topic
        self.zmq_endpoint = zmq_endpoint
        self.zmq_topic = zmq_topic
        self.started = False

    def start(self):
        if self.started:
            return

        self.publisher.start()
        try:
            self.source.start()
        except Exception:
            self.publisher.close()
            raise

        self.started = True
        logger.info(
            "Bridging Gazebo camera {} to ZMQ {} on topic {}",
            self.gazebo_topic,
            self.zmq_endpoint,
            self.zmq_topic.decode("utf-8", errors="replace"),
        )

    def close(self):
        self.source.close()
        self.publisher.close()
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
            logger.info("Stopping camera publisher after signal {}", signum)
            stop = True

        if install_signal_handlers:
            signal.signal(signal.SIGINT, stop_handler)
            signal.signal(signal.SIGTERM, stop_handler)

        self.start()
        try:
            while not stop and not (stop_event is not None and stop_event.is_set()):
                self.publisher.wait(timeout=poll_interval_s)
        finally:
            self.close()


class GazeboCameraViewer:
    """Coordinate Gazebo camera subscription and direct OpenCV display."""

    def __init__(
        self,
        *,
        gazebo_topic=GAZEBO_CAMERA_TOPIC,
        window_name="Gazebo Camera",
    ):
        logger.info("gz camera direct viewer")
        self.frames = deque(maxlen=1)
        self.lock = threading.Lock()
        self.source = GazeboCameraSource(
            gazebo_topic=gazebo_topic,
            frames=self.frames,
            lock=self.lock,
        )
        self.viewer = OpenCvCameraViewer(
            frames=self.frames,
            lock=self.lock,
            window_name=window_name,
        )
        self.gazebo_topic = gazebo_topic
        self.started = False

    def start(self):
        if self.started:
            return

        self.source.start()
        self.started = True
        logger.info("Viewing Gazebo camera {} directly", self.gazebo_topic)

    def close(self):
        self.source.close()
        self.viewer.close()
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
            logger.info("Stopping camera viewer after signal {}", signum)
            stop = True

        if install_signal_handlers:
            signal.signal(signal.SIGINT, stop_handler)
            signal.signal(signal.SIGTERM, stop_handler)

        self.start()
        try:
            while not stop and not (stop_event is not None and stop_event.is_set()):
                if not self.viewer.display_pending():
                    break
                self.source.wait(timeout=poll_interval_s)
        finally:
            self.close()




@click.command()
@click.option("--gazebo-topic", default=GAZEBO_CAMERA_TOPIC, help="Gazebo topic to subscribe to")
@click.option("--zmq-endpoint", default=ZMQ_CAMERA_ENDPOINT, help="ZMQ endpoint to publish to")
@click.option(
    "--view",
    "--viewer",
    "view",
    is_flag=True,
    help="Display images directly instead of publishing to ZMQ",
)
@click.option("--window", default="Gazebo Camera", help="OpenCV window name for --view")
def cli(gazebo_topic, zmq_endpoint, view, window):
    if view:
        viewer = GazeboCameraViewer(
            gazebo_topic=gazebo_topic,
            window_name=window,
        )
        viewer.spin()
        return

    publisher = GazeboCameraPublisher(
        gazebo_topic=gazebo_topic,
        zmq_endpoint=zmq_endpoint,
    )
    publisher.spin()


if __name__ == "__main__":
    cli()

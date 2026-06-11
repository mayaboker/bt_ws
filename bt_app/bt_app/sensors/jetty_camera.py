"""
jetty example
"""
import argparse
import signal
import threading
from collections import deque

import cv2
import numpy as np
from gz.msgs import image_pb2
from gz.msgs.image_pb2 import Image
from gz.transport import Node


DEFAULT_TOPIC = "/camera"
DEFAULT_WINDOW = "Gazebo Camera"


def image_buffer(data, height, width, step, channels):
    row_bytes = width * channels
    step = step or row_bytes

    if step < row_bytes:
        raise ValueError(f"image step {step} is smaller than row size {row_bytes}")

    expected_size = step * height
    if len(data) < expected_size:
        raise ValueError(f"image data too short: got {len(data)}, need {expected_size}")

    image = np.frombuffer(data, dtype=np.uint8, count=expected_size)
    image = image.reshape((height, step))[:, :row_bytes]
    return image.reshape((height, width, channels))


def image_to_bgr(msg: Image):
    if msg.width <= 0 or msg.height <= 0:
        raise ValueError(f"invalid image size: {msg.width}x{msg.height}")

    if msg.pixel_format_type == image_pb2.RGB_INT8:
        image = image_buffer(msg.data, msg.height, msg.width, msg.step, 3)
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    if msg.pixel_format_type == image_pb2.BGR_INT8:
        return image_buffer(msg.data, msg.height, msg.width, msg.step, 3)

    if msg.pixel_format_type == image_pb2.RGBA_INT8:
        image = image_buffer(msg.data, msg.height, msg.width, msg.step, 4)
        return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)

    if msg.pixel_format_type == image_pb2.BGRA_INT8:
        image = image_buffer(msg.data, msg.height, msg.width, msg.step, 4)
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    if msg.pixel_format_type == image_pb2.L_INT8:
        gray = image_buffer(msg.data, msg.height, msg.width, msg.step, 1)
        return cv2.cvtColor(gray.reshape((msg.height, msg.width)), cv2.COLOR_GRAY2BGR)

    raise ValueError(f"unsupported pixel format: {msg.pixel_format_type}")


def main():
    parser = argparse.ArgumentParser(description="View a Gazebo camera topic with OpenCV.")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="Gazebo camera topic")
    parser.add_argument("--window", default=DEFAULT_WINDOW, help="OpenCV window name")
    args = parser.parse_args()

    node = Node()
    frames = deque(maxlen=1)
    lock = threading.Lock()
    stop_event = threading.Event()
    frame_count = 0

    def stop(_signum, _frame):
        stop_event.set()

    def cb(msg: Image):
        nonlocal frame_count
        frame_count += 1
        with lock:
            frames.append(msg)
        print("image:", msg.width, msg.height, "bytes:", len(msg.data), flush=True)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    if node.subscribe(Image, args.topic, cb) is False:
        raise RuntimeError(f"failed to subscribe to {args.topic}")

    print(f"listening on {args.topic}...", flush=True)
    print("press q, Esc, or Ctrl+C to stop", flush=True)

    try:
        while not stop_event.is_set():
            with lock:
                msg = frames.pop() if frames else None
                frames.clear()

            if msg is not None:
                try:
                    cv2.imshow(args.window, image_to_bgr(msg))
                except Exception as exc:
                    print(f"failed to display image: {exc}", flush=True)

            key = cv2.waitKey(10) & 0xFF
            if key in (ord("q"), 27):
                break

            if msg is None and frame_count == 0:
                stop_event.wait(timeout=0.05)
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

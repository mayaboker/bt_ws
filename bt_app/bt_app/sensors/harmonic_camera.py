"""
harmonic example
"""
import signal
import threading
from collections import deque
from dataclasses import dataclass, field

import click
import cv2
import numpy as np
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image
from gz.msgs10 import image_pb2


DEFAULT_TOPIC = "/camera"
DEFAULT_WINDOW = "Gazebo Camera"


@dataclass
class CameraState:
    frames: deque = field(default_factory=lambda: deque(maxlen=1))
    lock: threading.Lock = field(default_factory=threading.Lock)
    frame_count: int = 0


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
    print(threading.current_thread().name)
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


def cb(msg: Image, state: CameraState):
    state.frame_count += 1
    with state.lock:
        state.frames.append(msg)
    print("image:", msg.width, msg.height, "bytes:", len(msg.data), flush=True)


def display_frame_loop(state: CameraState, stop_event: threading.Event, window: str):
    try:
        while not stop_event.is_set():
            with state.lock:
                msg = state.frames.pop() if state.frames else None
                state.frames.clear()

            if msg is not None:
                try:
                    cv2.imshow(window, image_to_bgr(msg))
                except Exception as exc:
                    print(f"failed to display image: {exc}", flush=True)

            key = cv2.waitKey(10) & 0xFF
            if key in (ord("q"), 27):
                break

            if msg is None and state.frame_count == 0:
                stop_event.wait(timeout=0.05)
    finally:
        cv2.destroyAllWindows()


@click.command(help="View a Gazebo camera topic with OpenCV.")
@click.option("--topic", default=DEFAULT_TOPIC, show_default=True, help="Gazebo camera topic")
@click.option("--window", default=DEFAULT_WINDOW, show_default=True, help="OpenCV window name")
def main(topic, window):
    node = Node()
    state = CameraState()
    stop_event = threading.Event()

    def stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    if node.subscribe(Image, topic, lambda msg: cb(msg, state)) is False:
        raise RuntimeError(f"failed to subscribe to {topic}")

    print(f"listening on {topic}...", flush=True)
    print("press q, Esc, or Ctrl+C to stop", flush=True)

    display_frame_loop(state, stop_event, window)


if __name__ == "__main__":
    main()

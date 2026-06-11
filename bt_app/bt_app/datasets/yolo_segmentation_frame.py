#!/usr/bin/env python3
"""Capture one Gazebo RGB + segmentation frame and write YOLO labels."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import math
from pathlib import Path
import subprocess
import threading
import time

import numpy as np
from gz.msgs10.boolean_pb2 import Boolean
from gz.msgs10 import image_pb2
from gz.msgs10.image_pb2 import Image
from gz.msgs10.pose_pb2 import Pose
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.transport13 import Node


DEFAULT_RGB_TOPIC = "/yolo/rgb"
DEFAULT_LABEL_TOPIC = "/yolo/semantic/labels_map"
DEFAULT_OUTPUT_DIR = "yolo_frame"
DEFAULT_WORLD_NAME = "yolo_car_targets"
DEFAULT_CAMERA_NAME = "yolo_dataset_camera"

LABEL_TO_CLASS = {
    1: 0,  # Evata -> YOLO class car
    2: 1,  # SUV -> YOLO class suv
}


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    step: int
    pixel_format: int
    data: bytes


class OneFrameSubscriber:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.node = Node()
        self.frames: deque[Frame] = deque(maxlen=1)
        self.ready = threading.Event()
        self.started = False

    def start(self) -> None:
        subscribed = self.node.subscribe(Image, self.topic, self._on_image)
        if subscribed is False:
            raise RuntimeError(f"Failed to subscribe to {self.topic}")
        self.started = True

    def close(self) -> None:
        if not self.started:
            return
        try:
            self.node.unsubscribe(self.topic)
        finally:
            self.started = False

    def wait_for_frame(self, timeout: float) -> Frame:
        if not self.ready.wait(timeout=timeout):
            raise TimeoutError(f"Timed out waiting for {self.topic}")
        if not self.frames:
            raise TimeoutError(f"Timed out waiting for {self.topic}")
        return self.frames[-1]

    def clear(self) -> None:
        self.ready.clear()
        self.frames.clear()

    def _on_image(self, msg: Image) -> None:
        self.frames.append(
            Frame(
                width=msg.width,
                height=msg.height,
                step=msg.step,
                pixel_format=msg.pixel_format_type,
                data=bytes(msg.data),
            )
        )
        self.ready.set()


class OnePoseInfoSubscriber:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.node = Node()
        self.message: Pose_V | None = None
        self.ready = threading.Event()
        self.started = False

    def start(self) -> None:
        subscribed = self.node.subscribe(Pose_V, self.topic, self._on_pose_info)
        if subscribed is False:
            raise RuntimeError(f"Failed to subscribe to {self.topic}")
        self.started = True

    def close(self) -> None:
        if not self.started:
            return
        try:
            self.node.unsubscribe(self.topic)
        finally:
            self.started = False

    def wait_for_message(self, timeout: float) -> Pose_V:
        if not self.ready.wait(timeout=timeout):
            raise TimeoutError(f"Timed out waiting for {self.topic}")
        if self.message is None:
            raise RuntimeError(f"No pose info received from {self.topic}")
        return self.message

    def _on_pose_info(self, msg: Pose_V) -> None:
        self.message = msg
        self.ready.set()


@dataclass(frozen=True)
class CameraPose:
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float


@dataclass(frozen=True)
class CaptureStats:
    saved: int = 0
    skipped_empty: int = 0
    skipped_missing_class: int = 0
    skipped_pose_error: int = 0
    skipped_capture_error: int = 0
    attempted: int = 0
    car_instances: int = 0
    suv_instances: int = 0

    def add_saved(self, boxes: list[tuple[int, float, float, float, float]]) -> "CaptureStats":
        car_instances = sum(1 for box in boxes if box[0] == 0)
        suv_instances = sum(1 for box in boxes if box[0] == 1)
        return CaptureStats(
            saved=self.saved + 1,
            skipped_empty=self.skipped_empty,
            skipped_missing_class=self.skipped_missing_class,
            skipped_pose_error=self.skipped_pose_error,
            skipped_capture_error=self.skipped_capture_error,
            attempted=self.attempted + 1,
            car_instances=self.car_instances + car_instances,
            suv_instances=self.suv_instances + suv_instances,
        )

    def add_skipped_empty(self) -> "CaptureStats":
        return CaptureStats(
            saved=self.saved,
            skipped_empty=self.skipped_empty + 1,
            skipped_missing_class=self.skipped_missing_class,
            skipped_pose_error=self.skipped_pose_error,
            skipped_capture_error=self.skipped_capture_error,
            attempted=self.attempted + 1,
            car_instances=self.car_instances,
            suv_instances=self.suv_instances,
        )

    def add_skipped_missing_class(self) -> "CaptureStats":
        return CaptureStats(
            saved=self.saved,
            skipped_empty=self.skipped_empty,
            skipped_missing_class=self.skipped_missing_class + 1,
            skipped_pose_error=self.skipped_pose_error,
            skipped_capture_error=self.skipped_capture_error,
            attempted=self.attempted + 1,
            car_instances=self.car_instances,
            suv_instances=self.suv_instances,
        )

    def add_skipped_pose_error(self) -> "CaptureStats":
        return CaptureStats(
            saved=self.saved,
            skipped_empty=self.skipped_empty,
            skipped_missing_class=self.skipped_missing_class,
            skipped_pose_error=self.skipped_pose_error + 1,
            skipped_capture_error=self.skipped_capture_error,
            attempted=self.attempted + 1,
            car_instances=self.car_instances,
            suv_instances=self.suv_instances,
        )

    def add_skipped_capture_error(self) -> "CaptureStats":
        return CaptureStats(
            saved=self.saved,
            skipped_empty=self.skipped_empty,
            skipped_missing_class=self.skipped_missing_class,
            skipped_pose_error=self.skipped_pose_error,
            skipped_capture_error=self.skipped_capture_error + 1,
            attempted=self.attempted + 1,
            car_instances=self.car_instances,
            suv_instances=self.suv_instances,
        )


def label_image_to_array(frame: Frame) -> np.ndarray:
    if frame.pixel_format == image_pb2.L_INT8:
        dtype = np.uint8
        channels = 1
    elif frame.pixel_format == image_pb2.L_INT16:
        dtype = np.uint16
        channels = 1
    elif frame.pixel_format == image_pb2.RGB_INT8:
        # Some Gazebo builds publish labels as RGB where label ids are stored in the first byte.
        dtype = np.uint8
        channels = 3
    else:
        name = image_pb2.PixelFormatType.Name(frame.pixel_format)
        raise ValueError(f"Unsupported label map pixel format: {name}")

    item_size = np.dtype(dtype).itemsize
    row_bytes = frame.width * channels * item_size
    step = frame.step or row_bytes
    expected_size = step * frame.height
    if len(frame.data) < expected_size:
        raise ValueError(
            f"Label image data too short: got {len(frame.data)} bytes, need {expected_size}"
        )

    raw = np.frombuffer(frame.data, dtype=np.uint8, count=expected_size)
    rows = raw.reshape((frame.height, step))[:, :row_bytes]
    labels = np.frombuffer(rows.tobytes(), dtype=dtype).reshape(
        (frame.height, frame.width, channels)
    )
    if channels == 1:
        return labels[:, :, 0].astype(np.int32)
    return labels[:, :, 0].astype(np.int32)


def rgb_image_to_array(frame: Frame) -> np.ndarray:
    if frame.pixel_format == image_pb2.RGB_INT8:
        channels = 3
    elif frame.pixel_format == image_pb2.RGBA_INT8:
        channels = 4
    else:
        name = image_pb2.PixelFormatType.Name(frame.pixel_format)
        raise ValueError(f"Unsupported RGB image pixel format: {name}")

    row_bytes = frame.width * channels
    step = frame.step or row_bytes
    expected_size = step * frame.height
    if len(frame.data) < expected_size:
        raise ValueError(
            f"RGB image data too short: got {len(frame.data)} bytes, need {expected_size}"
        )

    image = np.frombuffer(frame.data, dtype=np.uint8, count=expected_size)
    image = image.reshape((frame.height, step))[:, :row_bytes]
    image = image.reshape((frame.height, frame.width, channels))
    return image[:, :, :3]


def yolo_boxes_from_labels(
    label_image: np.ndarray,
    label_to_class: dict[int, int],
    min_area_px: int,
) -> list[tuple[int, float, float, float, float]]:
    height, width = label_image.shape
    boxes = []
    for label_id, class_id in label_to_class.items():
        mask = (label_image == label_id).astype(np.uint8)
        for x_min, y_min, x_max, y_max, area in connected_bounding_boxes(mask):
            if area < min_area_px:
                continue

            box_width = x_max - x_min + 1
            box_height = y_max - y_min + 1
            if box_width * box_height < min_area_px:
                continue

            x_center = (x_min + x_max + 1) / 2.0 / width
            y_center = (y_min + y_max + 1) / 2.0 / height
            norm_width = box_width / width
            norm_height = box_height / height
            boxes.append((class_id, x_center, y_center, norm_width, norm_height))
    return boxes


def connected_bounding_boxes(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    try:
        import cv2
    except ImportError:
        return [single_bounding_box(mask)] if mask.any() else []

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for component_id in range(1, count):
        x = int(stats[component_id, cv2.CC_STAT_LEFT])
        y = int(stats[component_id, cv2.CC_STAT_TOP])
        width = int(stats[component_id, cv2.CC_STAT_WIDTH])
        height = int(stats[component_id, cv2.CC_STAT_HEIGHT])
        area = int(stats[component_id, cv2.CC_STAT_AREA])
        boxes.append((x, y, x + width - 1, y + height - 1, area))
    return boxes


def single_bounding_box(mask: np.ndarray) -> tuple[int, int, int, int, int]:
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()), int(xs.size)


def write_yolo_labels(path: Path, boxes: list[tuple[int, float, float, float, float]]) -> None:
    lines = [
        f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
        for class_id, x_center, y_center, width, height in boxes
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_rgb_png(path: Path, rgb: np.ndarray) -> None:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Install python3-opencv or opencv-python to save PNG images") from exc

    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def capture_frame_from_topics(
    rgb_topic: str,
    label_topic: str,
    timeout: float,
    min_area_px: int,
) -> tuple[np.ndarray, list[tuple[int, float, float, float, float]]]:
    rgb_sub = OneFrameSubscriber(rgb_topic)
    label_sub = OneFrameSubscriber(label_topic)
    try:
        rgb_sub.start()
        label_sub.start()

        # Give Gazebo transport callbacks a short window to receive both topics.
        deadline = time.monotonic() + timeout
        rgb_frame = rgb_sub.wait_for_frame(timeout)
        label_frame = label_sub.wait_for_frame(max(0.1, deadline - time.monotonic()))

        rgb = rgb_image_to_array(rgb_frame)
        labels = label_image_to_array(label_frame)
        boxes = yolo_boxes_from_labels(labels, LABEL_TO_CLASS, min_area_px)
        return rgb, boxes
    finally:
        label_sub.close()
        rgb_sub.close()


def capture_frame_from_subscribers(
    rgb_sub: OneFrameSubscriber,
    label_sub: OneFrameSubscriber,
    timeout: float,
    min_area_px: int,
) -> tuple[np.ndarray, list[tuple[int, float, float, float, float]]]:
    rgb_sub.clear()
    label_sub.clear()
    deadline = time.monotonic() + timeout
    rgb_frame = rgb_sub.wait_for_frame(timeout)
    label_frame = label_sub.wait_for_frame(max(0.1, deadline - time.monotonic()))

    rgb = rgb_image_to_array(rgb_frame)
    labels = label_image_to_array(label_frame)
    boxes = yolo_boxes_from_labels(labels, LABEL_TO_CLASS, min_area_px)
    return rgb, boxes


def save_dataset_frame(
    output_dir: Path,
    frame_index: int,
    rgb: np.ndarray,
    boxes: list[tuple[int, float, float, float, float]],
) -> tuple[Path, Path]:
    images_dir = output_dir / "images"
    labels_dir = output_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    stem = f"frame_{frame_index:06d}"
    image_path = images_dir / f"{stem}.png"
    label_path = labels_dir / f"{stem}.txt"
    write_rgb_png(image_path, rgb)
    write_yolo_labels(label_path, boxes)
    return image_path, label_path


def write_data_yaml(output_dir: Path) -> None:
    data_yaml = (
        f"path: {output_dir.resolve()}\n"
        "train: images\n"
        "val: images\n"
        "names:\n"
        "  0: car\n"
        "  1: suv\n"
    )
    (output_dir / "data.yaml").write_text(data_yaml, encoding="utf-8")


def capture_one_frame(
    rgb_topic: str,
    label_topic: str,
    output_dir: Path,
    timeout: float,
    min_area_px: int,
) -> None:
    rgb, boxes = capture_frame_from_topics(rgb_topic, label_topic, timeout, min_area_px)
    image_path, label_path = save_dataset_frame(output_dir, 1, rgb, boxes)
    write_data_yaml(output_dir)

    print(f"wrote {image_path}")
    print(f"wrote {label_path}")
    print(f"boxes: {len(boxes)}")
    for box in boxes:
        print("{} {:.6f} {:.6f} {:.6f} {:.6f}".format(*box))


def orbit_trajectory(
    count: int,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    start_angle: float,
    end_angle: float,
) -> list[CameraPose]:
    if count <= 0:
        raise ValueError("count must be greater than zero")

    center_x, center_y, center_z = center
    if count == 1:
        angles = [math.radians(start_angle)]
    else:
        start = math.radians(start_angle)
        end = math.radians(end_angle)
        angles = [start + (end - start) * index / count for index in range(count)]

    poses = []
    for angle in angles:
        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        z = height
        yaw = math.atan2(center_y - y, center_x - x)
        horizontal_distance = math.hypot(center_x - x, center_y - y)
        pitch = math.atan2(center_z - z, horizontal_distance)
        poses.append(CameraPose(x=x, y=y, z=z, roll=0.0, pitch=pitch, yaw=yaw))
    return poses


def grid_orbit_trajectory(
    radii: list[float],
    heights: list[float],
    angles_per_orbit: int,
    center: tuple[float, float, float],
    start_angle: float,
    end_angle: float,
) -> list[CameraPose]:
    poses = []
    for radius in radii:
        for height in heights:
            poses.extend(
                orbit_trajectory(
                    count=angles_per_orbit,
                    center=center,
                    radius=radius,
                    height=height,
                    start_angle=start_angle,
                    end_angle=end_angle,
                )
            )
    return poses


def parse_float_list(value: str) -> list[float]:
    values = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("value must contain at least one number")
    return values


def has_required_classes(
    boxes: list[tuple[int, float, float, float, float]],
    required_classes: set[int],
) -> bool:
    if not required_classes:
        return True
    present = {box[0] for box in boxes}
    return required_classes.issubset(present)


def set_camera_pose(
    node: Node,
    world_name: str,
    camera_name: str,
    pose: CameraPose,
    timeout_ms: int,
    camera_id: int | None = None,
) -> None:
    request = Pose()
    if camera_id is None:
        request.name = camera_name
    else:
        request.id = camera_id
    request.position.x = pose.x
    request.position.y = pose.y
    request.position.z = pose.z
    request.orientation.x, request.orientation.y, request.orientation.z, request.orientation.w = (
        euler_to_quaternion(pose.roll, pose.pitch, pose.yaw)
    )

    service = f"/world/{world_name}/set_pose"
    last_result = False
    last_response = None
    for attempt in range(1, 4):
        last_result, last_response = node.request(service, request, Pose, Boolean, timeout_ms)
        if last_result and last_response.data:
            return
        time.sleep(0.1 * attempt)

    if set_camera_pose_with_gz_service(service, request, timeout_ms):
        return

    response_text = None if last_response is None else last_response.data
    raise RuntimeError(
        f"Failed to set camera pose through {service}: result={last_result} response={response_text}"
    )


def set_camera_pose_with_gz_service(service: str, request: Pose, timeout_ms: int) -> bool:
    proto = pose_to_text_proto(request)
    completed = subprocess.run(
        [
            "gz",
            "service",
            "-s",
            service,
            "--reqtype",
            "gz.msgs.Pose",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            str(timeout_ms),
            "--req",
            proto,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and "data: true" in completed.stdout


def pose_to_text_proto(request: Pose) -> str:
    identity = f"id: {request.id}" if request.id else f'name: "{request.name}"'
    return (
        f"{identity} "
        f"position {{ x: {request.position.x:.9f} y: {request.position.y:.9f} z: {request.position.z:.9f} }} "
        "orientation { "
        f"x: {request.orientation.x:.12f} "
        f"y: {request.orientation.y:.12f} "
        f"z: {request.orientation.z:.12f} "
        f"w: {request.orientation.w:.12f} "
        "}"
    )


def get_entity_id_by_name(
    node: Node,
    world_name: str,
    entity_name: str,
    timeout_ms: int,
) -> int:
    del node
    subscriber = OnePoseInfoSubscriber(f"/world/{world_name}/pose/info")
    try:
        subscriber.start()
        response = subscriber.wait_for_message(timeout_ms / 1000.0)
        for pose in response.pose:
            if pose.name == entity_name:
                return pose.id
    finally:
        subscriber.close()
    raise RuntimeError(f"Entity not found in pose info: {entity_name}")


def euler_to_quaternion(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return x, y, z, w


def capture_trajectory(
    rgb_topic: str,
    label_topic: str,
    output_dir: Path,
    timeout: float,
    min_area_px: int,
    world_name: str,
    camera_name: str,
    count: int,
    center: tuple[float, float, float],
    radius: float,
    height: float,
    radii: list[float],
    heights: list[float],
    angles_per_orbit: int,
    require_any_box: bool,
    require_classes: set[int],
    start_angle: float,
    end_angle: float,
    settle_s: float,
) -> CaptureStats:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_data_yaml(output_dir)
    node = Node()
    rgb_sub = OneFrameSubscriber(rgb_topic)
    label_sub = OneFrameSubscriber(label_topic)
    if radii and heights:
        poses = grid_orbit_trajectory(radii, heights, angles_per_orbit, center, start_angle, end_angle)
    else:
        poses = orbit_trajectory(count, center, radius, height, start_angle, end_angle)

    stats = CaptureStats()
    saved_index = 1

    try:
        rgb_sub.start()
        label_sub.start()
        camera_id = get_entity_id_by_name(
            node,
            world_name,
            camera_name,
            timeout_ms=int(timeout * 1000),
        )
        for pose_index, pose in enumerate(poses, start=1):
            if stats.saved >= count:
                break
            try:
                set_camera_pose(
                    node,
                    world_name,
                    camera_name,
                    pose,
                    timeout_ms=int(timeout * 1000),
                    camera_id=camera_id,
                )
            except RuntimeError as exc:
                stats = stats.add_skipped_pose_error()
                print(f"skip pose={pose_index} reason=pose_error error={exc}")
                continue
            time.sleep(settle_s)
            try:
                rgb, boxes = capture_frame_from_subscribers(rgb_sub, label_sub, timeout, min_area_px)
            except (TimeoutError, ValueError) as exc:
                stats = stats.add_skipped_capture_error()
                print(f"skip pose={pose_index} reason=capture_error error={exc}")
                continue

            if require_any_box and not boxes:
                stats = stats.add_skipped_empty()
                print(f"skip pose={pose_index} reason=empty")
                continue
            if not has_required_classes(boxes, require_classes):
                stats = stats.add_skipped_missing_class()
                print(f"skip pose={pose_index} reason=missing_required_class boxes={len(boxes)}")
                continue

            image_path, label_path = save_dataset_frame(output_dir, saved_index, rgb, boxes)
            stats = stats.add_saved(boxes)
            print(
                "frame={} pose={} pose_xyz=({:.2f},{:.2f},{:.2f},pitch={:.3f},yaw={:.3f}) boxes={} image={} label={}".format(
                    saved_index,
                    pose_index,
                    pose.x,
                    pose.y,
                    pose.z,
                    pose.pitch,
                    pose.yaw,
                    len(boxes),
                    image_path,
                    label_path,
                )
            )
            saved_index += 1
    finally:
        label_sub.close()
        rgb_sub.close()

    print(
        "summary saved={} attempted={} skipped_empty={} skipped_missing_class={} skipped_pose_error={} skipped_capture_error={} car_instances={} suv_instances={}".format(
            stats.saved,
            stats.attempted,
            stats.skipped_empty,
            stats.skipped_missing_class,
            stats.skipped_pose_error,
            stats.skipped_capture_error,
            stats.car_instances,
            stats.suv_instances,
        )
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture one Gazebo segmentation frame and convert it to YOLO labels."
    )
    parser.add_argument("--rgb-topic", default=DEFAULT_RGB_TOPIC)
    parser.add_argument("--label-topic", default=DEFAULT_LABEL_TOPIC)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--min-area-px", type=int, default=25)
    parser.add_argument("--mode", choices=["one", "trajectory"], default="one")
    parser.add_argument("--world-name", default=DEFAULT_WORLD_NAME)
    parser.add_argument("--camera-name", default=DEFAULT_CAMERA_NAME)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--center-x", type=float, default=3.0)
    parser.add_argument("--center-y", type=float, default=0.0)
    parser.add_argument("--center-z", type=float, default=0.8)
    parser.add_argument("--radius", type=float, default=14.0)
    parser.add_argument("--height", type=float, default=4.0)
    parser.add_argument("--radii", type=parse_float_list, default=parse_float_list("12,16,22,30"))
    parser.add_argument("--heights", type=parse_float_list, default=parse_float_list("1.5,3,5"))
    parser.add_argument("--angles-per-orbit", type=int, default=45)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--require-both-classes", action="store_true")
    parser.add_argument("--start-angle", type=float, default=0.0)
    parser.add_argument("--end-angle", type=float, default=360.0)
    parser.add_argument("--settle-s", type=float, default=0.2)
    args = parser.parse_args()

    if args.mode == "one":
        capture_one_frame(
            rgb_topic=args.rgb_topic,
            label_topic=args.label_topic,
            output_dir=Path(args.output_dir),
            timeout=args.timeout,
            min_area_px=args.min_area_px,
        )
        return

    capture_trajectory(
        rgb_topic=args.rgb_topic,
        label_topic=args.label_topic,
        output_dir=Path(args.output_dir),
        timeout=args.timeout,
        min_area_px=args.min_area_px,
        world_name=args.world_name,
        camera_name=args.camera_name,
        count=args.count,
        center=(args.center_x, args.center_y, args.center_z),
        radius=args.radius,
        height=args.height,
        radii=args.radii,
        heights=args.heights,
        angles_per_orbit=args.angles_per_orbit,
        require_any_box=not args.allow_empty,
        require_classes={0, 1} if args.require_both_classes else set(),
        start_angle=args.start_angle,
        end_angle=args.end_angle,
        settle_s=args.settle_s,
    )


if __name__ == "__main__":
    main()

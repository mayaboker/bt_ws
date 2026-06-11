import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from bt_app.datasets.yolo_segmentation_frame import (
    CaptureStats,
    euler_to_quaternion,
    grid_orbit_trajectory,
    has_required_classes,
    orbit_trajectory,
    pose_to_text_proto,
    save_dataset_frame,
    write_data_yaml,
    yolo_boxes_from_labels,
)
from gz.msgs10.pose_pb2 import Pose


class YoloSegmentationFrameTest(unittest.TestCase):
    def test_orbit_trajectory_creates_ten_poses_looking_at_center(self) -> None:
        poses = orbit_trajectory(
            count=10,
            center=(3.0, 0.0, 0.8),
            radius=14.0,
            height=4.0,
            start_angle=0.0,
            end_angle=360.0,
        )

        self.assertEqual(len(poses), 10)
        self.assertAlmostEqual(poses[0].x, 17.0)
        self.assertAlmostEqual(poses[0].y, 0.0)
        self.assertAlmostEqual(poses[0].yaw, math.pi)
        self.assertLess(poses[0].pitch, 0.0)

    def test_grid_orbit_trajectory_combines_radii_heights_and_angles(self) -> None:
        poses = grid_orbit_trajectory(
            radii=[8.0, 12.0],
            heights=[2.0, 4.0],
            angles_per_orbit=5,
            center=(3.0, 0.0, 0.8),
            start_angle=0.0,
            end_angle=360.0,
        )

        self.assertEqual(len(poses), 20)
        self.assertAlmostEqual(poses[0].x, 11.0)
        self.assertAlmostEqual(poses[5].z, 4.0)
        self.assertAlmostEqual(poses[10].x, 15.0)

    def test_required_class_filter(self) -> None:
        self.assertTrue(has_required_classes([(0, 0.5, 0.5, 0.1, 0.1)], {0}))
        self.assertFalse(has_required_classes([(0, 0.5, 0.5, 0.1, 0.1)], {0, 1}))

    def test_capture_stats_counts_instances(self) -> None:
        stats = CaptureStats().add_saved(
            [(0, 0.5, 0.5, 0.1, 0.1), (1, 0.6, 0.5, 0.1, 0.1)]
        )

        self.assertEqual(stats.saved, 1)
        self.assertEqual(stats.attempted, 1)
        self.assertEqual(stats.car_instances, 1)
        self.assertEqual(stats.suv_instances, 1)

    def test_pose_to_text_proto_uses_id_and_orientation(self) -> None:
        request = Pose()
        request.id = 143
        request.position.x = 1.0
        request.position.y = 2.0
        request.position.z = 3.0
        request.orientation.x, request.orientation.y, request.orientation.z, request.orientation.w = (
            euler_to_quaternion(0.0, 0.1, 0.2)
        )

        text = pose_to_text_proto(request)

        self.assertIn("id: 143", text)
        self.assertIn("position { x: 1.000000000 y: 2.000000000 z: 3.000000000 }", text)
        self.assertIn("orientation {", text)

    def test_yolo_boxes_from_labels_splits_multiple_components(self) -> None:
        labels = np.zeros((10, 20), dtype=np.int32)
        labels[1:4, 2:5] = 1
        labels[6:9, 12:16] = 1
        labels[2:5, 15:19] = 2

        boxes = yolo_boxes_from_labels(labels, {1: 0, 2: 1}, min_area_px=1)

        self.assertEqual(len(boxes), 3)
        self.assertEqual([box[0] for box in boxes], [0, 0, 1])

    def test_save_dataset_frame_and_data_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            rgb = np.zeros((2, 3, 3), dtype=np.uint8)
            boxes = [(0, 0.5, 0.5, 0.25, 0.25)]

            image_path, label_path = save_dataset_frame(output_dir, 1, rgb, boxes)
            write_data_yaml(output_dir)

            self.assertTrue(image_path.exists())
            self.assertEqual(label_path.read_text(encoding="utf-8"), "0 0.500000 0.500000 0.250000 0.250000\n")
            self.assertIn("0: car", (output_dir / "data.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

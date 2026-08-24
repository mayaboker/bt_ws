from __future__ import annotations

import numpy as np
import pytest

from bt_app.diagnostics.pitch_rotation_effect import (
    CameraIntrinsics,
    apply_pitch_rotation,
    compose_comparison,
    generate_calibration_scene,
    generate_outputs,
    pitch_homography,
    project_pixel,
)


def test_calibration_scene_has_camera_shape_and_expected_features():
    intrinsics = CameraIntrinsics()
    image = generate_calibration_scene(intrinsics)

    assert image.shape == (480, 640, 3)
    assert image.dtype == np.uint8
    assert tuple(image[240, 320]) != tuple(image[20, 20])
    assert np.any(image[:, :, 2] > 200)


def test_zero_pitch_preserves_baseline_exactly():
    intrinsics = CameraIntrinsics()
    image = generate_calibration_scene(intrinsics)

    rotated = apply_pitch_rotation(image, 0.0, intrinsics)

    assert np.array_equal(rotated, image)


def test_negative_forward_pitch_moves_fixed_scene_pixel_upward():
    intrinsics = CameraIntrinsics()
    pixel = (intrinsics.cx, intrinsics.cy + 80.0)
    zero = project_pixel(pixel, pitch_homography(0.0, intrinsics))
    forward = project_pixel(pixel, pitch_homography(-10.0, intrinsics))

    assert forward[1] < zero[1]


def test_comparison_sheet_contains_four_labeled_panels():
    intrinsics = CameraIntrinsics()
    image = generate_calibration_scene(intrinsics)
    angles = (0.0, -5.0, -10.0, -15.0)
    rotated = [apply_pitch_rotation(image, angle, intrinsics) for angle in angles]

    sheet = compose_comparison(rotated, angles)

    assert sheet.shape == (1040, 1280, 3)
    assert np.any(sheet[:40, :, :])


def test_pitch_rotation_uses_black_for_unknown_pixels():
    intrinsics = CameraIntrinsics()
    image = generate_calibration_scene(intrinsics)

    rotated = apply_pitch_rotation(image, -15.0, intrinsics)

    assert np.all(rotated[-1, intrinsics.width // 2] == 0)


def test_generate_outputs_writes_base_and_comparison(tmp_path):
    base_path, comparison_path = generate_outputs(
        intrinsics=CameraIntrinsics(),
        angles_deg=(0.0, -5.0, -10.0, -15.0),
        base_output=tmp_path / "base.png",
        comparison_output=tmp_path / "comparison.png",
    )

    assert base_path.is_file()
    assert comparison_path.is_file()


@pytest.mark.parametrize(
    "kwargs",
    (
        {"width": 0},
        {"height": -1},
        {"fx": 0.0},
        {"fy": float("nan")},
        {"cx": 640.0},
    ),
)
def test_invalid_intrinsics_are_rejected(kwargs):
    with pytest.raises(ValueError):
        CameraIntrinsics(**kwargs)


def test_comparison_requires_exactly_four_angles(tmp_path):
    with pytest.raises(ValueError, match="exactly four"):
        generate_outputs(
            intrinsics=CameraIntrinsics(),
            angles_deg=(0.0, -5.0),
            base_output=tmp_path / "base.png",
            comparison_output=tmp_path / "comparison.png",
        )

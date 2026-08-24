"""Generate a synthetic camera scene and visualize pure pitch rotation."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np


DEFAULT_ANGLES_DEG = (0.0, -5.0, -10.0, -15.0)
LABEL_HEIGHT_PX = 40


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    width: int = 640
    height: int = 480
    fx: float = 320.0
    fy: float = 320.0
    cx: float = 320.0
    cy: float = 240.0

    def __post_init__(self) -> None:
        values = (self.fx, self.fy, self.cx, self.cy)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image dimensions must be positive")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("camera intrinsics must be finite")
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("camera focal lengths must be positive")
        if not 0.0 <= self.cx < self.width or not 0.0 <= self.cy < self.height:
            raise ValueError("camera principal point must be inside the image")

    @property
    def matrix(self) -> np.ndarray:
        return np.array(
            ((self.fx, 0.0, self.cx), (0.0, self.fy, self.cy), (0.0, 0.0, 1.0)),
            dtype=np.float64,
        )


def generate_calibration_scene(intrinsics: CameraIntrinsics) -> np.ndarray:
    """Draw a deterministic horizon, ground grid, crosshair, and red target."""
    height, width = intrinsics.height, intrinsics.width
    image = np.empty((height, width, 3), dtype=np.uint8)
    horizon_y = int(round(intrinsics.cy))

    for y in range(height):
        if y < horizon_y:
            fraction = y / max(horizon_y - 1, 1)
            image[y, :, :] = (
                round(185 - 35 * fraction),
                round(220 - 25 * fraction),
                round(250 - 15 * fraction),
            )
        else:
            fraction = (y - horizon_y) / max(height - horizon_y - 1, 1)
            image[y, :, :] = (
                round(115 - 45 * fraction),
                round(150 - 55 * fraction),
                round(105 - 35 * fraction),
            )

    horizon_color = (255, 255, 255)
    grid_color = (195, 195, 195)
    cv2.line(image, (0, horizon_y), (width - 1, horizon_y), horizon_color, 2)

    for index in range(-8, 9):
        bottom_x = int(round(intrinsics.cx + index * width / 8))
        cv2.line(
            image,
            (int(round(intrinsics.cx)), horizon_y),
            (bottom_x, height - 1),
            grid_color,
            1,
            cv2.LINE_AA,
        )
    for index in range(1, 11):
        fraction = (index / 10.0) ** 1.8
        y = horizon_y + int(round(fraction * (height - 1 - horizon_y)))
        cv2.line(image, (0, y), (width - 1, y), grid_color, 1, cv2.LINE_AA)

    target_width = max(40, width // 7)
    target_height = max(55, height // 5)
    target_center_x = int(round(intrinsics.cx + width * 0.10))
    target_bottom = min(height - 25, int(round(intrinsics.cy + height * 0.36)))
    target_left = target_center_x - target_width // 2
    target_top = target_bottom - target_height
    cv2.rectangle(
        image,
        (target_left, target_top),
        (target_left + target_width, target_bottom),
        (35, 35, 215),
        thickness=-1,
    )
    cv2.rectangle(
        image,
        (target_left, target_top),
        (target_left + target_width, target_bottom),
        (255, 255, 255),
        thickness=2,
    )
    cv2.putText(
        image,
        "TARGET",
        (target_left + 5, target_top + 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    center = (int(round(intrinsics.cx)), int(round(intrinsics.cy)))
    cv2.line(image, (center[0] - 18, center[1]), (center[0] + 18, center[1]), (0, 255, 255), 2)
    cv2.line(image, (center[0], center[1] - 18), (center[0], center[1] + 18), (0, 255, 255), 2)
    cv2.circle(image, center, 7, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(
        image,
        "0 deg baseline",
        (18, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (40, 40, 40),
        2,
        cv2.LINE_AA,
    )
    return image


def pitch_homography(
    pitch_deg: float,
    intrinsics: CameraIntrinsics,
) -> np.ndarray:
    """Return old-image to pitched-image homography.

    Project convention: negative pitch is forward / nose-down. Therefore a
    negative pitch applies a positive optical-x rotation to fixed scene rays,
    moving the horizon and target upward in the output image.
    """
    pitch = float(pitch_deg)
    if not math.isfinite(pitch):
        raise ValueError("pitch angle must be finite")
    theta = math.radians(-pitch)
    cosine = math.cos(theta)
    sine = math.sin(theta)
    rotation = np.array(
        ((1.0, 0.0, 0.0), (0.0, cosine, -sine), (0.0, sine, cosine)),
        dtype=np.float64,
    )
    camera_matrix = intrinsics.matrix
    homography = camera_matrix @ rotation @ np.linalg.inv(camera_matrix)
    return homography / homography[2, 2]


def project_pixel(pixel: tuple[float, float], homography: np.ndarray) -> tuple[float, float]:
    point = np.array((pixel[0], pixel[1], 1.0), dtype=np.float64)
    projected = homography @ point
    if abs(projected[2]) < 1e-12:
        raise ValueError("pixel projects to infinity")
    return float(projected[0] / projected[2]), float(projected[1] / projected[2])


def apply_pitch_rotation(
    image: np.ndarray,
    pitch_deg: float,
    intrinsics: CameraIntrinsics,
) -> np.ndarray:
    if image.shape != (intrinsics.height, intrinsics.width, 3):
        raise ValueError(
            "image shape must match camera intrinsics: "
            f"expected {(intrinsics.height, intrinsics.width, 3)}, got {image.shape}"
        )
    return cv2.warpPerspective(
        image,
        pitch_homography(pitch_deg, intrinsics),
        (intrinsics.width, intrinsics.height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def compose_comparison(
    images: Sequence[np.ndarray],
    angles_deg: Sequence[float],
) -> np.ndarray:
    if not images or len(images) != len(angles_deg):
        raise ValueError("one image is required for every pitch angle")
    if len(images) != 4:
        raise ValueError("the comparison sheet requires exactly four images")
    shape = images[0].shape
    if any(image.shape != shape for image in images):
        raise ValueError("all comparison images must have the same shape")

    panels: list[np.ndarray] = []
    for image, angle in zip(images, angles_deg, strict=True):
        panel = np.zeros((shape[0] + LABEL_HEIGHT_PX, shape[1], 3), dtype=np.uint8)
        panel[LABEL_HEIGHT_PX:, :, :] = image
        label = f"Pitch {float(angle):+.1f} deg"
        cv2.putText(
            panel,
            label,
            (16, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        panels.append(panel)
    return np.vstack((np.hstack(panels[:2]), np.hstack(panels[2:])))


def write_png(path: str | Path, image: np.ndarray) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), image):
        raise OSError(f"failed to write image: {output}")
    return output


def generate_outputs(
    *,
    intrinsics: CameraIntrinsics,
    angles_deg: Sequence[float],
    base_output: str | Path,
    comparison_output: str | Path,
) -> tuple[Path, Path]:
    if len(angles_deg) != 4:
        raise ValueError("exactly four pitch angles are required")
    base = generate_calibration_scene(intrinsics)
    rotated = [apply_pitch_rotation(base, angle, intrinsics) for angle in angles_deg]
    comparison = compose_comparison(rotated, angles_deg)
    return write_png(base_output, base), write_png(comparison_output, comparison)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic camera pitch-rotation comparison."
    )
    parser.add_argument("--angles", nargs=4, type=float, default=DEFAULT_ANGLES_DEG)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fx", type=float, default=320.0)
    parser.add_argument("--fy", type=float, default=320.0)
    parser.add_argument("--cx", type=float, default=320.0)
    parser.add_argument("--cy", type=float, default=240.0)
    parser.add_argument("--base-output", type=Path, default=Path("logs/pitch_rotation_base.png"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("logs/pitch_rotation_comparison.png"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    intrinsics = CameraIntrinsics(
        width=args.width,
        height=args.height,
        fx=args.fx,
        fy=args.fy,
        cx=args.cx,
        cy=args.cy,
    )
    base_path, comparison_path = generate_outputs(
        intrinsics=intrinsics,
        angles_deg=args.angles,
        base_output=args.base_output,
        comparison_output=args.output,
    )
    print(f"wrote {base_path}")
    print(f"wrote {comparison_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tracker-result distance and target-velocity service."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from bt_msgs import TrackerResultMessage

from bt_app.estimators import (
    CameraIntrinsics,
    PinholeDistanceEstimator,
    TargetVelocityEstimator,
)
from bt_app.parameters import Parameters
from bt_app.parameters.generated import ParameterKey


@dataclass(frozen=True, slots=True)
class TargetEstimate:
    frame_id: int
    timestamp_ns: int | None
    received_at_s: float
    depth_m: float | None
    slant_range_m: float | None
    vx_m_s: float
    vy_m_s: float
    valid: bool
    reason: str | None = None


class DistanceEstimatorService:
    """Synchronously turn tracker results into a latest target estimate."""

    def __init__(
        self,
        *,
        distance_estimator: PinholeDistanceEstimator,
        velocity_estimator: TargetVelocityEstimator,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._distance_estimator = distance_estimator
        self._velocity_estimator = velocity_estimator
        self._clock = clock
        self._lock = threading.Lock()
        self._latest_estimate: TargetEstimate | None = None
        self._last_frame_id: int | None = None

    @classmethod
    def from_parameters(
        cls,
        parameters: Parameters,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> "DistanceEstimatorService":
        distance = PinholeDistanceEstimator(
            CameraIntrinsics(
                fx_px=parameters.get(ParameterKey.CAM_FX_PX),
                fy_px=parameters.get(ParameterKey.CAM_FY_PX),
                cx_px=parameters.get(ParameterKey.CAM_CX_PX),
                cy_px=parameters.get(ParameterKey.CAM_CY_PX),
                image_width_px=parameters.get(ParameterKey.CAM_WIDTH_PX),
                image_height_px=parameters.get(ParameterKey.CAM_HEIGHT_PX),
            ),
            target_width_m=parameters.get(ParameterKey.OBJ_WIDTH_M),
            target_height_m=parameters.get(ParameterKey.OBJ_HEIGHT_M),
        )
        velocity = TargetVelocityEstimator(
            target_speed_m_s=parameters.get(ParameterKey.VIS_SPEED_MPS),
        )
        return cls(
            distance_estimator=distance,
            velocity_estimator=velocity,
            clock=clock,
        )

    @property
    def latest_estimate(self) -> TargetEstimate | None:
        with self._lock:
            return self._latest_estimate

    def process_tracker_result(self, message: TrackerResultMessage) -> TargetEstimate:
        received_at = self._clock()
        with self._lock:
            if (
                self._last_frame_id is not None
                and message.frame_id <= self._last_frame_id
                and self._latest_estimate is not None
            ):
                return self._latest_estimate
            self._last_frame_id = message.frame_id
            try:
                distance = self._distance_estimator.estimate(message)
                velocity = self._velocity_estimator.estimate(
                    depth_m=distance.depth_m,
                    vertical_offset_m=distance.vertical_offset_m,
                )
                estimate = TargetEstimate(
                    frame_id=message.frame_id,
                    timestamp_ns=message.timestamp_ns,
                    received_at_s=received_at,
                    depth_m=distance.depth_m,
                    slant_range_m=distance.slant_range_m,
                    vx_m_s=velocity.vx_m_s,
                    vy_m_s=velocity.vy_m_s,
                    valid=True,
                )
            except ValueError as exc:
                estimate = TargetEstimate(
                    frame_id=message.frame_id,
                    timestamp_ns=message.timestamp_ns,
                    received_at_s=received_at,
                    depth_m=None,
                    slant_range_m=None,
                    vx_m_s=0.0,
                    vy_m_s=0.0,
                    valid=False,
                    reason=str(exc),
                )
            self._latest_estimate = estimate
            return estimate

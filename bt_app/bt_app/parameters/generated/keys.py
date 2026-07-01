"""Auto-generated parameter key constants."""

from __future__ import annotations

from typing import Final, Literal


class ParameterKey:
    """Parameter keys generated from bt_app/config/parameters.yaml."""
    ALTITUDE_KD: Final[Literal['altitude.kd']] = 'altitude.kd'
    ALTITUDE_KI: Final[Literal['altitude.ki']] = 'altitude.ki'
    ALTITUDE_KP: Final[Literal['altitude.kp']] = 'altitude.kp'
    ALTITUDE_OUTPUT_LIMITS: Final[Literal['altitude.output_limits']] = 'altitude.output_limits'
    BETAFLIGHT_YAW_RATE_FULL_STICK_DPS: Final[Literal['betaflight_yaw_rate_full_stick_dps']] = 'betaflight_yaw_rate_full_stick_dps'
    FAIL_SHAPE_ALT: Final[Literal['fail_shape.alt']] = 'fail_shape.alt'
    FLIGHT_MODE: Final[Literal['flight.mode']] = 'flight.mode'
    HOVER_YAW_ALTITUDE: Final[Literal['hover_yaw.altitude']] = 'hover_yaw.altitude'
    HOVER_YAW_YAW_RATE: Final[Literal['hover_yaw.yaw_rate']] = 'hover_yaw.yaw_rate'
    TAKEOFF_ALTITUDE: Final[Literal['takeoff_altitude']] = 'takeoff_altitude'
    VISUAL_FINAL_TRACKING_DISTANCE: Final[Literal['visual.final_tracking_distance']] = 'visual.final_tracking_distance'
    VISUAL_FORWARD_PITCH_DEG: Final[Literal['visual.forward_pitch_deg']] = 'visual.forward_pitch_deg'
    VISUAL_HOVER_THROTTLE: Final[Literal['visual.hover_throttle']] = 'visual.hover_throttle'
    VISUAL_KP_PITCH_Y: Final[Literal['visual.kp_pitch_y']] = 'visual.kp_pitch_y'
    VISUAL_KP_THROTTLE_Y: Final[Literal['visual.kp_throttle_y']] = 'visual.kp_throttle_y'
    VISUAL_KP_YAW: Final[Literal['visual.kp_yaw']] = 'visual.kp_yaw'
    VISUAL_MAX_PITCH_DEG: Final[Literal['visual.max_pitch_deg']] = 'visual.max_pitch_deg'
    VISUAL_MAX_THROTTLE: Final[Literal['visual.max_throttle']] = 'visual.max_throttle'


ALL_PARAMETER_KEYS: Final[tuple[str, ...]] = (
    'altitude.kd',
    'altitude.ki',
    'altitude.kp',
    'altitude.output_limits',
    'betaflight_yaw_rate_full_stick_dps',
    'fail_shape.alt',
    'flight.mode',
    'hover_yaw.altitude',
    'hover_yaw.yaw_rate',
    'takeoff_altitude',
    'visual.final_tracking_distance',
    'visual.forward_pitch_deg',
    'visual.hover_throttle',
    'visual.kp_pitch_y',
    'visual.kp_throttle_y',
    'visual.kp_yaw',
    'visual.max_pitch_deg',
    'visual.max_throttle',
)

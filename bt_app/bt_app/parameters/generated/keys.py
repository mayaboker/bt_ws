"""Auto-generated parameter key constants."""

from __future__ import annotations

from typing import Final, Literal


class ParameterKey:
    """Parameter keys generated from bt_app/parameters.yaml."""
    ALTITUDE_KD: Final[Literal['altitude.kd']] = 'altitude.kd'
    ALTITUDE_KI: Final[Literal['altitude.ki']] = 'altitude.ki'
    ALTITUDE_KP: Final[Literal['altitude.kp']] = 'altitude.kp'
    ALTITUDE_OUTPUT_LIMITS: Final[Literal['altitude.output_limits']] = 'altitude.output_limits'
    BETAFLIGHT_YAW_RATE_FULL_STICK_DPS: Final[Literal['betaflight_yaw_rate_full_stick_dps']] = 'betaflight_yaw_rate_full_stick_dps'
    FAIL_SHAPE_ALT: Final[Literal['fail_shape.alt']] = 'fail_shape.alt'
    FAILSAFE_DESCENT_RATE_M_S: Final[Literal['failsafe.descent_rate_m_s']] = 'failsafe.descent_rate_m_s'
    FAILSAFE_HOLD_TIME_S: Final[Literal['failsafe.hold_time_s']] = 'failsafe.hold_time_s'
    FAILSAFE_LAND_ALTITUDE_M: Final[Literal['failsafe.land_altitude_m']] = 'failsafe.land_altitude_m'
    FAILSAFE_LAND_CONFIRM_S: Final[Literal['failsafe.land_confirm_s']] = 'failsafe.land_confirm_s'
    FAILSAFE_LAND_VERTICAL_SPEED_M_S: Final[Literal['failsafe.land_vertical_speed_m_s']] = 'failsafe.land_vertical_speed_m_s'
    FAILSAFE_MIN_ALTITUDE: Final[Literal['failsafe.min_altitude']] = 'failsafe.min_altitude'
    FLIGHT_MODE: Final[Literal['flight.mode']] = 'flight.mode'
    HOVER_ALTITUDE_RATE_M_S: Final[Literal['hover.altitude_rate_m_s']] = 'hover.altitude_rate_m_s'
    HOVER_KD: Final[Literal['hover.kd']] = 'hover.kd'
    HOVER_KI: Final[Literal['hover.ki']] = 'hover.ki'
    HOVER_KP: Final[Literal['hover.kp']] = 'hover.kp'
    HOVER_MIN_ALTITUDE: Final[Literal['hover.min_altitude']] = 'hover.min_altitude'
    HOVER_OUTPUT_LIMITS: Final[Literal['hover.output_limits']] = 'hover.output_limits'
    HOVER_THROTTLE_DEADBAND: Final[Literal['hover.throttle_deadband']] = 'hover.throttle_deadband'
    HOVER_YAW_ALTITUDE: Final[Literal['hover_yaw.altitude']] = 'hover_yaw.altitude'
    HOVER_YAW_YAW_RATE: Final[Literal['hover_yaw.yaw_rate']] = 'hover_yaw.yaw_rate'
    MANUAL_IDLE_LAND_CONFIRM_S: Final[Literal['manual_idle.land_confirm_s']] = 'manual_idle.land_confirm_s'
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
    'failsafe.descent_rate_m_s',
    'failsafe.hold_time_s',
    'failsafe.land_altitude_m',
    'failsafe.land_confirm_s',
    'failsafe.land_vertical_speed_m_s',
    'failsafe.min_altitude',
    'flight.mode',
    'hover.altitude_rate_m_s',
    'hover.kd',
    'hover.ki',
    'hover.kp',
    'hover.min_altitude',
    'hover.output_limits',
    'hover.throttle_deadband',
    'hover_yaw.altitude',
    'hover_yaw.yaw_rate',
    'manual_idle.land_confirm_s',
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

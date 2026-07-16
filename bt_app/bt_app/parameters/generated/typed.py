"""Auto-generated typed parameter accessors."""

from __future__ import annotations

from typing import Any, Literal, Protocol, cast

from bt_app.parameters.generated.keys import ParameterKey


class SupportsParameterGet(Protocol):
    def get(self, name: str) -> Any:
        ...


class TypedParameters:
    """Typed parameter accessors generated from bt_app/parameters.yaml."""

    def __init__(self, parameters: SupportsParameterGet) -> None:
        self._parameters = parameters

    @property
    def altitude_kd(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALTITUDE_KD))

    @property
    def altitude_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALTITUDE_KI))

    @property
    def altitude_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALTITUDE_KP))

    @property
    def altitude_output_limits(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALTITUDE_OUTPUT_LIMITS))

    @property
    def betaflight_yaw_rate_full_stick_dps(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.BETAFLIGHT_YAW_RATE_FULL_STICK_DPS))

    @property
    def fail_shape_alt(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.FAIL_SHAPE_ALT))

    @property
    def failsafe_descent_rate_m_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FAILSAFE_DESCENT_RATE_M_S))

    @property
    def failsafe_hold_time_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FAILSAFE_HOLD_TIME_S))

    @property
    def failsafe_land_altitude_m(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FAILSAFE_LAND_ALTITUDE_M))

    @property
    def failsafe_land_confirm_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FAILSAFE_LAND_CONFIRM_S))

    @property
    def failsafe_land_vertical_speed_m_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FAILSAFE_LAND_VERTICAL_SPEED_M_S))

    @property
    def failsafe_min_altitude(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FAILSAFE_MIN_ALTITUDE))

    @property
    def flight_mode(self) -> Literal['stabilize', 'altitude', 'position']:
        return cast(Literal['stabilize', 'altitude', 'position'], self._parameters.get(ParameterKey.FLIGHT_MODE))

    @property
    def hover_altitude_rate_m_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_ALTITUDE_RATE_M_S))

    @property
    def hover_kd(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_KD))

    @property
    def hover_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_KI))

    @property
    def hover_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_KP))

    @property
    def hover_min_altitude(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_MIN_ALTITUDE))

    @property
    def hover_output_limits(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_OUTPUT_LIMITS))

    @property
    def hover_throttle_deadband(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HOVER_THROTTLE_DEADBAND))

    @property
    def hover_yaw_altitude(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_YAW_ALTITUDE))

    @property
    def hover_yaw_deadband(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HOVER_YAW_DEADBAND))

    @property
    def hover_yaw_expo(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_YAW_EXPO))

    @property
    def hover_yaw_max_rate_dps(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_YAW_MAX_RATE_DPS))

    @property
    def hover_yaw_yaw_rate(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HOVER_YAW_YAW_RATE))

    @property
    def manual_idle_land_confirm_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.MANUAL_IDLE_LAND_CONFIRM_S))

    @property
    def takeoff_altitude(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TAKEOFF_ALTITUDE))

    @property
    def visual_final_tracking_distance(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_FINAL_TRACKING_DISTANCE))

    @property
    def visual_forward_pitch_deg(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_FORWARD_PITCH_DEG))

    @property
    def visual_hover_throttle(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_HOVER_THROTTLE))

    @property
    def visual_kp_pitch_y(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_KP_PITCH_Y))

    @property
    def visual_kp_throttle_y(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_KP_THROTTLE_Y))

    @property
    def visual_kp_yaw(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_KP_YAW))

    @property
    def visual_max_pitch_deg(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_MAX_PITCH_DEG))

    @property
    def visual_max_throttle(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VISUAL_MAX_THROTTLE))

"""Auto-generated typed parameter accessors."""

from __future__ import annotations

from typing import Any, Literal, Protocol, cast

from bt_app.parameters.generated.keys import ParameterKey


class SupportsParameterGet(Protocol):
    def get(self, name: str) -> Any:
        ...


class TypedParameters:
    """Typed parameter accessors generated from bt_app/config/parameters.yaml."""

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
    def flight_mode(self) -> Literal['stabilize', 'altitude', 'position']:
        return cast(Literal['stabilize', 'altitude', 'position'], self._parameters.get(ParameterKey.FLIGHT_MODE))

    @property
    def hover_yaw_altitude(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOVER_YAW_ALTITUDE))

    @property
    def hover_yaw_yaw_rate(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HOVER_YAW_YAW_RATE))

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

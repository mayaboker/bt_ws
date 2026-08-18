"""Auto-generated typed parameter accessors."""

from __future__ import annotations

from typing import Any, Protocol, cast

from bt_app.parameters.generated.keys import ParameterKey


class SupportsParameterGet(Protocol):
    def get(self, name: str) -> Any:
        ...


class TypedParameters:
    """Typed parameter accessors generated from bt_app/parameters.yaml."""

    def __init__(self, parameters: SupportsParameterGet) -> None:
        self._parameters = parameters

    @property
    def fs_hold_time(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FS_HOLD_TIME))

    @property
    def fs_desc_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FS_DESC_RATE))

    @property
    def fs_min_alt(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FS_MIN_ALT))

    @property
    def fs_land_alt(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FS_LAND_ALT))

    @property
    def fs_land_vspeed(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FS_LAND_VSPEED))

    @property
    def fs_land_confirm(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.FS_LAND_CONFIRM))

    @property
    def mi_land_confirm(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.MI_LAND_CONFIRM))

    @property
    def joy_timeout(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.JOY_TIMEOUT))

    @property
    def alt_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALT_KP))

    @property
    def alt_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALT_KI))

    @property
    def alt_kd(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALT_KD))

    @property
    def alt_out_limit(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.ALT_OUT_LIMIT))

    @property
    def takeoff_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TAKEOFF_RATE))

    @property
    def hov_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOV_KP))

    @property
    def hov_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOV_KI))

    @property
    def hov_kd(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOV_KD))

    @property
    def hov_out_limit(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOV_OUT_LIMIT))

    @property
    def hov_baseline(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HOV_BASELINE))

    @property
    def hov_alt_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOV_ALT_RATE))

    @property
    def hov_thr_db(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HOV_THR_DB))

    @property
    def hov_min_alt(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HOV_MIN_ALT))

    @property
    def takeoff_alt(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TAKEOFF_ALT))

    @property
    def hy_max_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HY_MAX_RATE))

    @property
    def hy_deadband(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.HY_DEADBAND))

    @property
    def hy_expo(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.HY_EXPO))

    @property
    def bf_yaw_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.BF_YAW_RATE))

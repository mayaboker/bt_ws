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
    def glide_pitch_ff(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_PITCH_FF))

    @property
    def glide_pitch_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_PITCH_MAX))

    @property
    def glide_vx_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_VX_KP))

    @property
    def glide_vx_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_VX_KI))

    @property
    def glide_vy_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_VY_KP))

    @property
    def glide_vy_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_VY_KI))

    @property
    def glide_vy_out(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_VY_OUT))

    @property
    def glide_yaw_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_YAW_KP))

    @property
    def glide_yaw_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_YAW_MAX))

    @property
    def glide_center_ky(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_CENTER_KY))

    @property
    def glide_depth_ema(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.GLIDE_DEPTH_EMA))

    @property
    def bf_angle_limit(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.BF_ANGLE_LIMIT))

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
    def vis_hov_thr(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_HOV_THR))

    @property
    def vis_fwd_pitch(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_FWD_PITCH))

    @property
    def vis_max_pitch(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_MAX_PITCH))

    @property
    def vis_max_thr(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_MAX_THR))

    @property
    def vis_kp_yaw(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_KP_YAW))

    @property
    def vis_max_yaw(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_MAX_YAW))

    @property
    def vis_kp_pitch(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_KP_PITCH))

    @property
    def vis_kp_thr(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_KP_THR))

    @property
    def bf_yaw_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.BF_YAW_RATE))

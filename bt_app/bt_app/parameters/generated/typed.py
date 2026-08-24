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

    @property
    def cam_fx_px(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.CAM_FX_PX))

    @property
    def cam_fy_px(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.CAM_FY_PX))

    @property
    def cam_cx_px(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.CAM_CX_PX))

    @property
    def cam_cy_px(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.CAM_CY_PX))

    @property
    def cam_width_px(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.CAM_WIDTH_PX))

    @property
    def cam_height_px(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.CAM_HEIGHT_PX))

    @property
    def obj_width_m(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.OBJ_WIDTH_M))

    @property
    def obj_height_m(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.OBJ_HEIGHT_M))

    @property
    def vis_speed_mps(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.VIS_SPEED_MPS))

    @property
    def ttc_pit_init(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_PIT_INIT))

    @property
    def ttc_pit_min(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_PIT_MIN))

    @property
    def ttc_pit_slew(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_PIT_SLEW))

    @property
    def ttc_inv_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_INV_KP))

    @property
    def ttc_scale_a(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_SCALE_A))

    @property
    def ttc_scale_b(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_SCALE_B))

    @property
    def ttc_inv_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_INV_MAX))

    @property
    def ttc_log_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_LOG_MAX))

    @property
    def ttc_lock_fr(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.TTC_LOCK_FR))

    @property
    def ttc_lock_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_LOCK_S))

    @property
    def ttc_timeout(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_TIMEOUT))

    @property
    def ttc_scale_jmp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_SCALE_JMP))

    @property
    def tgt_height_m(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TGT_HEIGHT_M))

    @property
    def ttc_vy_nom(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_NOM))

    @property
    def ttc_vy_min(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_MIN))

    @property
    def ttc_vy_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_MAX))

    @property
    def ttc_min_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_MIN_S))

    @property
    def ttc_dy_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_DY_KP))

    @property
    def ttc_vy_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_KP))

    @property
    def ttc_vy_ki(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_KI))

    @property
    def ttc_vy_kd(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_KD))

    @property
    def ttc_az_alpha(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_AZ_ALPHA))

    @property
    def ttc_vy_i_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_VY_I_MAX))

    @property
    def ttc_thr_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_THR_MAX))

    @property
    def ttc_fill(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_FILL))

    @property
    def ttc_align(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TTC_ALIGN))

    @property
    def ttc_commit_fr(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.TTC_COMMIT_FR))

    @property
    def trk_pitch_deg(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_PITCH_DEG))

    @property
    def trk_pitch_rate(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_PITCH_RATE))

    @property
    def trk_yaw_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_YAW_KP))

    @property
    def trk_yaw_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_YAW_MAX))

    @property
    def trk_thr_kp(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_THR_KP))

    @property
    def trk_vz_kd(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_KD))

    @property
    def trk_vz_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_MAX))

    @property
    def trk_vz_accel(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_ACCEL))

    @property
    def trk_vz_near(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_NEAR))

    @property
    def trk_vz_taper_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_TAPER_S))

    @property
    def trk_vz_taper_e(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_TAPER_E))

    @property
    def trk_vz_brake(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_VZ_BRAKE))

    @property
    def trk_thr_max(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_THR_MAX))

    @property
    def trk_deadband(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_DEADBAND))

    @property
    def trk_timeout_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_TIMEOUT_S))

    @property
    def trk_lock_frames(self) -> int:
        return cast(int, self._parameters.get(ParameterKey.TRK_LOCK_FRAMES))

    @property
    def trk_commit_m(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_COMMIT_M))

    @property
    def trk_commit_s(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_COMMIT_S))

    @property
    def trk_commit_xy(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_COMMIT_XY))

    @property
    def trk_commit_vz(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_COMMIT_VZ))

    @property
    def trk_commit_hold(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_COMMIT_HOLD))

    @property
    def trk_term_timeout(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.TRK_TERM_TIMEOUT))

    @property
    def bf_angle_limit(self) -> float:
        return cast(float, self._parameters.get(ParameterKey.BF_ANGLE_LIMIT))

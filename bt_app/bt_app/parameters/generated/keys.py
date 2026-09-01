"""Auto-generated parameter key constants."""

from __future__ import annotations

from typing import Final, Literal


class ParameterKey:
    """Parameter keys generated from bt_app/parameters.yaml."""
    FS_HOLD_TIME: Final[Literal['FS_HOLD_TIME']] = 'FS_HOLD_TIME'
    FS_DESC_RATE: Final[Literal['FS_DESC_RATE']] = 'FS_DESC_RATE'
    FS_MIN_ALT: Final[Literal['FS_MIN_ALT']] = 'FS_MIN_ALT'
    FS_LAND_ALT: Final[Literal['FS_LAND_ALT']] = 'FS_LAND_ALT'
    FS_LAND_VSPEED: Final[Literal['FS_LAND_VSPEED']] = 'FS_LAND_VSPEED'
    FS_LAND_CONFIRM: Final[Literal['FS_LAND_CONFIRM']] = 'FS_LAND_CONFIRM'
    MI_LAND_CONFIRM: Final[Literal['MI_LAND_CONFIRM']] = 'MI_LAND_CONFIRM'
    JOY_TIMEOUT: Final[Literal['JOY_TIMEOUT']] = 'JOY_TIMEOUT'
    ALT_KP: Final[Literal['ALT_KP']] = 'ALT_KP'
    ALT_KI: Final[Literal['ALT_KI']] = 'ALT_KI'
    ALT_KD: Final[Literal['ALT_KD']] = 'ALT_KD'
    ALT_OUT_LIMIT: Final[Literal['ALT_OUT_LIMIT']] = 'ALT_OUT_LIMIT'
    TAKEOFF_RATE: Final[Literal['TAKEOFF_RATE']] = 'TAKEOFF_RATE'
    HOV_KP: Final[Literal['HOV_KP']] = 'HOV_KP'
    HOV_KI: Final[Literal['HOV_KI']] = 'HOV_KI'
    HOV_KD: Final[Literal['HOV_KD']] = 'HOV_KD'
    HOV_OUT_LIMIT: Final[Literal['HOV_OUT_LIMIT']] = 'HOV_OUT_LIMIT'
    HOV_BASELINE: Final[Literal['HOV_BASELINE']] = 'HOV_BASELINE'
    HOV_ALT_RATE: Final[Literal['HOV_ALT_RATE']] = 'HOV_ALT_RATE'
    HOV_THR_DB: Final[Literal['HOV_THR_DB']] = 'HOV_THR_DB'
    HOV_MIN_ALT: Final[Literal['HOV_MIN_ALT']] = 'HOV_MIN_ALT'
    TAKEOFF_ALT: Final[Literal['TAKEOFF_ALT']] = 'TAKEOFF_ALT'
    HY_MAX_RATE: Final[Literal['HY_MAX_RATE']] = 'HY_MAX_RATE'
    HY_DEADBAND: Final[Literal['HY_DEADBAND']] = 'HY_DEADBAND'
    HY_EXPO: Final[Literal['HY_EXPO']] = 'HY_EXPO'
    BF_YAW_RATE: Final[Literal['BF_YAW_RATE']] = 'BF_YAW_RATE'
    BF_YAW_CENTER: Final[Literal['BF_YAW_CENTER']] = 'BF_YAW_CENTER'
    BF_YAW_EXPO: Final[Literal['BF_YAW_EXPO']] = 'BF_YAW_EXPO'
    CAM_FX_PX: Final[Literal['CAM_FX_PX']] = 'CAM_FX_PX'
    CAM_FY_PX: Final[Literal['CAM_FY_PX']] = 'CAM_FY_PX'
    CAM_CX_PX: Final[Literal['CAM_CX_PX']] = 'CAM_CX_PX'
    CAM_CY_PX: Final[Literal['CAM_CY_PX']] = 'CAM_CY_PX'
    CAM_WIDTH_PX: Final[Literal['CAM_WIDTH_PX']] = 'CAM_WIDTH_PX'
    CAM_HEIGHT_PX: Final[Literal['CAM_HEIGHT_PX']] = 'CAM_HEIGHT_PX'
    OBJ_WIDTH_M: Final[Literal['OBJ_WIDTH_M']] = 'OBJ_WIDTH_M'
    OBJ_HEIGHT_M: Final[Literal['OBJ_HEIGHT_M']] = 'OBJ_HEIGHT_M'
    VIS_SPEED_MPS: Final[Literal['VIS_SPEED_MPS']] = 'VIS_SPEED_MPS'
    TTC_PIT_INIT: Final[Literal['TTC_PIT_INIT']] = 'TTC_PIT_INIT'
    TTC_PIT_MIN: Final[Literal['TTC_PIT_MIN']] = 'TTC_PIT_MIN'
    TTC_PIT_SLEW: Final[Literal['TTC_PIT_SLEW']] = 'TTC_PIT_SLEW'
    TTC_PIT_REC: Final[Literal['TTC_PIT_REC']] = 'TTC_PIT_REC'
    TTC_INV_KP: Final[Literal['TTC_INV_KP']] = 'TTC_INV_KP'
    TTC_SCALE_A: Final[Literal['TTC_SCALE_A']] = 'TTC_SCALE_A'
    TTC_SCALE_B: Final[Literal['TTC_SCALE_B']] = 'TTC_SCALE_B'
    TTC_INV_MAX: Final[Literal['TTC_INV_MAX']] = 'TTC_INV_MAX'
    TTC_LOG_MAX: Final[Literal['TTC_LOG_MAX']] = 'TTC_LOG_MAX'
    TTC_LOCK_FR: Final[Literal['TTC_LOCK_FR']] = 'TTC_LOCK_FR'
    TTC_LOCK_S: Final[Literal['TTC_LOCK_S']] = 'TTC_LOCK_S'
    TTC_TIMEOUT: Final[Literal['TTC_TIMEOUT']] = 'TTC_TIMEOUT'
    TTC_SCALE_JMP: Final[Literal['TTC_SCALE_JMP']] = 'TTC_SCALE_JMP'
    TGT_HEIGHT_M: Final[Literal['TGT_HEIGHT_M']] = 'TGT_HEIGHT_M'
    TTC_VY_NOM: Final[Literal['TTC_VY_NOM']] = 'TTC_VY_NOM'
    TTC_VY_MIN: Final[Literal['TTC_VY_MIN']] = 'TTC_VY_MIN'
    TTC_VY_MAX: Final[Literal['TTC_VY_MAX']] = 'TTC_VY_MAX'
    TTC_MIN_S: Final[Literal['TTC_MIN_S']] = 'TTC_MIN_S'
    TTC_DY_KP: Final[Literal['TTC_DY_KP']] = 'TTC_DY_KP'
    TTC_DY_VMAX: Final[Literal['TTC_DY_VMAX']] = 'TTC_DY_VMAX'
    TTC_DY_NEAR: Final[Literal['TTC_DY_NEAR']] = 'TTC_DY_NEAR'
    TTC_VY_KP: Final[Literal['TTC_VY_KP']] = 'TTC_VY_KP'
    TTC_VY_KI: Final[Literal['TTC_VY_KI']] = 'TTC_VY_KI'
    TTC_VY_KD: Final[Literal['TTC_VY_KD']] = 'TTC_VY_KD'
    TTC_AZ_ALPHA: Final[Literal['TTC_AZ_ALPHA']] = 'TTC_AZ_ALPHA'
    TTC_VY_I_MAX: Final[Literal['TTC_VY_I_MAX']] = 'TTC_VY_I_MAX'
    TTC_THR_MAX: Final[Literal['TTC_THR_MAX']] = 'TTC_THR_MAX'
    TTC_FILL: Final[Literal['TTC_FILL']] = 'TTC_FILL'
    TTC_CLIP_FILL: Final[Literal['TTC_CLIP_FILL']] = 'TTC_CLIP_FILL'
    TTC_ALIGN: Final[Literal['TTC_ALIGN']] = 'TTC_ALIGN'
    TTC_COMMIT_FR: Final[Literal['TTC_COMMIT_FR']] = 'TTC_COMMIT_FR'
    TTC_ALN_PIT: Final[Literal['TTC_ALN_PIT']] = 'TTC_ALN_PIT'
    TTC_ALN_XY: Final[Literal['TTC_ALN_XY']] = 'TTC_ALN_XY'
    TTC_ALN_FR: Final[Literal['TTC_ALN_FR']] = 'TTC_ALN_FR'
    TRK_PITCH_DEG: Final[Literal['TRK_PITCH_DEG']] = 'TRK_PITCH_DEG'
    TRK_PITCH_RATE: Final[Literal['TRK_PITCH_RATE']] = 'TRK_PITCH_RATE'
    TRK_YAW_KP: Final[Literal['TRK_YAW_KP']] = 'TRK_YAW_KP'
    TRK_YAW_MAX: Final[Literal['TRK_YAW_MAX']] = 'TRK_YAW_MAX'
    TRK_YAW_SLEW: Final[Literal['TRK_YAW_SLEW']] = 'TRK_YAW_SLEW'
    TRK_YAW_SIGN: Final[Literal['TRK_YAW_SIGN']] = 'TRK_YAW_SIGN'
    TRK_THR_KP: Final[Literal['TRK_THR_KP']] = 'TRK_THR_KP'
    TRK_VZ_KD: Final[Literal['TRK_VZ_KD']] = 'TRK_VZ_KD'
    TRK_VZ_MAX: Final[Literal['TRK_VZ_MAX']] = 'TRK_VZ_MAX'
    TRK_VZ_ACCEL: Final[Literal['TRK_VZ_ACCEL']] = 'TRK_VZ_ACCEL'
    TRK_VZ_NEAR: Final[Literal['TRK_VZ_NEAR']] = 'TRK_VZ_NEAR'
    TRK_VZ_TAPER_S: Final[Literal['TRK_VZ_TAPER_S']] = 'TRK_VZ_TAPER_S'
    TRK_VZ_TAPER_E: Final[Literal['TRK_VZ_TAPER_E']] = 'TRK_VZ_TAPER_E'
    TRK_VZ_BRAKE: Final[Literal['TRK_VZ_BRAKE']] = 'TRK_VZ_BRAKE'
    TRK_THR_MAX: Final[Literal['TRK_THR_MAX']] = 'TRK_THR_MAX'
    TRK_DEADBAND: Final[Literal['TRK_DEADBAND']] = 'TRK_DEADBAND'
    TRK_TIMEOUT_S: Final[Literal['TRK_TIMEOUT_S']] = 'TRK_TIMEOUT_S'
    TRK_LOCK_FRAMES: Final[Literal['TRK_LOCK_FRAMES']] = 'TRK_LOCK_FRAMES'
    TRK_COMMIT_M: Final[Literal['TRK_COMMIT_M']] = 'TRK_COMMIT_M'
    TRK_COMMIT_S: Final[Literal['TRK_COMMIT_S']] = 'TRK_COMMIT_S'
    TRK_COMMIT_XY: Final[Literal['TRK_COMMIT_XY']] = 'TRK_COMMIT_XY'
    TRK_COMMIT_VZ: Final[Literal['TRK_COMMIT_VZ']] = 'TRK_COMMIT_VZ'
    TRK_COMMIT_HOLD: Final[Literal['TRK_COMMIT_HOLD']] = 'TRK_COMMIT_HOLD'
    TRK_TERM_TIMEOUT: Final[Literal['TRK_TERM_TIMEOUT']] = 'TRK_TERM_TIMEOUT'
    BF_ANGLE_LIMIT: Final[Literal['BF_ANGLE_LIMIT']] = 'BF_ANGLE_LIMIT'


ALL_PARAMETER_KEYS: Final[tuple[str, ...]] = (
    'FS_HOLD_TIME',
    'FS_DESC_RATE',
    'FS_MIN_ALT',
    'FS_LAND_ALT',
    'FS_LAND_VSPEED',
    'FS_LAND_CONFIRM',
    'MI_LAND_CONFIRM',
    'JOY_TIMEOUT',
    'ALT_KP',
    'ALT_KI',
    'ALT_KD',
    'ALT_OUT_LIMIT',
    'TAKEOFF_RATE',
    'HOV_KP',
    'HOV_KI',
    'HOV_KD',
    'HOV_OUT_LIMIT',
    'HOV_BASELINE',
    'HOV_ALT_RATE',
    'HOV_THR_DB',
    'HOV_MIN_ALT',
    'TAKEOFF_ALT',
    'HY_MAX_RATE',
    'HY_DEADBAND',
    'HY_EXPO',
    'BF_YAW_RATE',
    'BF_YAW_CENTER',
    'BF_YAW_EXPO',
    'CAM_FX_PX',
    'CAM_FY_PX',
    'CAM_CX_PX',
    'CAM_CY_PX',
    'CAM_WIDTH_PX',
    'CAM_HEIGHT_PX',
    'OBJ_WIDTH_M',
    'OBJ_HEIGHT_M',
    'VIS_SPEED_MPS',
    'TTC_PIT_INIT',
    'TTC_PIT_MIN',
    'TTC_PIT_SLEW',
    'TTC_PIT_REC',
    'TTC_INV_KP',
    'TTC_SCALE_A',
    'TTC_SCALE_B',
    'TTC_INV_MAX',
    'TTC_LOG_MAX',
    'TTC_LOCK_FR',
    'TTC_LOCK_S',
    'TTC_TIMEOUT',
    'TTC_SCALE_JMP',
    'TGT_HEIGHT_M',
    'TTC_VY_NOM',
    'TTC_VY_MIN',
    'TTC_VY_MAX',
    'TTC_MIN_S',
    'TTC_DY_KP',
    'TTC_DY_VMAX',
    'TTC_DY_NEAR',
    'TTC_VY_KP',
    'TTC_VY_KI',
    'TTC_VY_KD',
    'TTC_AZ_ALPHA',
    'TTC_VY_I_MAX',
    'TTC_THR_MAX',
    'TTC_FILL',
    'TTC_CLIP_FILL',
    'TTC_ALIGN',
    'TTC_COMMIT_FR',
    'TTC_ALN_PIT',
    'TTC_ALN_XY',
    'TTC_ALN_FR',
    'TRK_PITCH_DEG',
    'TRK_PITCH_RATE',
    'TRK_YAW_KP',
    'TRK_YAW_MAX',
    'TRK_YAW_SLEW',
    'TRK_YAW_SIGN',
    'TRK_THR_KP',
    'TRK_VZ_KD',
    'TRK_VZ_MAX',
    'TRK_VZ_ACCEL',
    'TRK_VZ_NEAR',
    'TRK_VZ_TAPER_S',
    'TRK_VZ_TAPER_E',
    'TRK_VZ_BRAKE',
    'TRK_THR_MAX',
    'TRK_DEADBAND',
    'TRK_TIMEOUT_S',
    'TRK_LOCK_FRAMES',
    'TRK_COMMIT_M',
    'TRK_COMMIT_S',
    'TRK_COMMIT_XY',
    'TRK_COMMIT_VZ',
    'TRK_COMMIT_HOLD',
    'TRK_TERM_TIMEOUT',
    'BF_ANGLE_LIMIT',
)

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
    CAM_FX_PX: Final[Literal['CAM_FX_PX']] = 'CAM_FX_PX'
    CAM_FY_PX: Final[Literal['CAM_FY_PX']] = 'CAM_FY_PX'
    CAM_CX_PX: Final[Literal['CAM_CX_PX']] = 'CAM_CX_PX'
    CAM_CY_PX: Final[Literal['CAM_CY_PX']] = 'CAM_CY_PX'
    CAM_WIDTH_PX: Final[Literal['CAM_WIDTH_PX']] = 'CAM_WIDTH_PX'
    CAM_HEIGHT_PX: Final[Literal['CAM_HEIGHT_PX']] = 'CAM_HEIGHT_PX'
    OBJ_WIDTH_M: Final[Literal['OBJ_WIDTH_M']] = 'OBJ_WIDTH_M'
    OBJ_HEIGHT_M: Final[Literal['OBJ_HEIGHT_M']] = 'OBJ_HEIGHT_M'
    VIS_SPEED_MPS: Final[Literal['VIS_SPEED_MPS']] = 'VIS_SPEED_MPS'
    TRK_PITCH_DEG: Final[Literal['TRK_PITCH_DEG']] = 'TRK_PITCH_DEG'
    TRK_PITCH_RATE: Final[Literal['TRK_PITCH_RATE']] = 'TRK_PITCH_RATE'
    TRK_YAW_KP: Final[Literal['TRK_YAW_KP']] = 'TRK_YAW_KP'
    TRK_YAW_MAX: Final[Literal['TRK_YAW_MAX']] = 'TRK_YAW_MAX'
    TRK_THR_KP: Final[Literal['TRK_THR_KP']] = 'TRK_THR_KP'
    TRK_THR_MAX: Final[Literal['TRK_THR_MAX']] = 'TRK_THR_MAX'
    TRK_DEADBAND: Final[Literal['TRK_DEADBAND']] = 'TRK_DEADBAND'
    TRK_TIMEOUT_S: Final[Literal['TRK_TIMEOUT_S']] = 'TRK_TIMEOUT_S'
    TRK_LOCK_FRAMES: Final[Literal['TRK_LOCK_FRAMES']] = 'TRK_LOCK_FRAMES'
    TRK_COMMIT_M: Final[Literal['TRK_COMMIT_M']] = 'TRK_COMMIT_M'
    TRK_COMMIT_S: Final[Literal['TRK_COMMIT_S']] = 'TRK_COMMIT_S'
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
    'CAM_FX_PX',
    'CAM_FY_PX',
    'CAM_CX_PX',
    'CAM_CY_PX',
    'CAM_WIDTH_PX',
    'CAM_HEIGHT_PX',
    'OBJ_WIDTH_M',
    'OBJ_HEIGHT_M',
    'VIS_SPEED_MPS',
    'TRK_PITCH_DEG',
    'TRK_PITCH_RATE',
    'TRK_YAW_KP',
    'TRK_YAW_MAX',
    'TRK_THR_KP',
    'TRK_THR_MAX',
    'TRK_DEADBAND',
    'TRK_TIMEOUT_S',
    'TRK_LOCK_FRAMES',
    'TRK_COMMIT_M',
    'TRK_COMMIT_S',
    'BF_ANGLE_LIMIT',
)

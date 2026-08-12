from enum import IntEnum, StrEnum


class MavSeverity(IntEnum):
    EMERGENCY = 0
    ALERT = 1
    CRITICAL = 2
    ERROR = 3
    WARNING = 4
    NOTICE = 5
    INFO = 6
    DEBUG = 7


class NamedValue(StrEnum):
    ALT_SP = "alt_sp"
    VERTICAL_SPEED_SP = "vs_sp"
    TARGET_DISTANCE = "tgt_dist"
    VISUAL_FOUND = "vis_found"
    VISUAL_LOCKED = "vis_locked"
    VISUAL_FRAME = "vis_frame"
    VISUAL_AGE = "vis_age"
    VISUAL_ERROR_X = "vis_ex"
    VISUAL_ERROR_Y = "vis_ey"
    OBSERVATION_VALID = "obs_valid"
    OBSERVATION_REASON = "obs_reason"
    GLIDE_ACQUISITION_COUNT = "acq_count"
    GLIDE_PHASE = "gld_phase"

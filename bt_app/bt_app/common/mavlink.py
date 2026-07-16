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

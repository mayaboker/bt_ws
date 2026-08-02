from enum import IntEnum


class AppExitCode(IntEnum):
    SUCCESS = 0
    STARTUP_ERROR = 1
    CLI_USAGE_ERROR = 2
    SERIAL_PORT_NOT_FOUND = 3
    FCU_CONNECTION_FAILED = 4


class AppStartupError(RuntimeError):
    """Expected application startup validation failure."""

    def __init__(
        self,
        message: str,
        exit_code: AppExitCode = AppExitCode.STARTUP_ERROR,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code

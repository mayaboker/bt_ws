"""Expected dashboard data and startup failures."""


class NoFinishedSessionError(LookupError):
    """Raised when the log directory contains no finished session."""


class SessionNotFoundError(LookupError):
    """Raised when a requested session is not discoverable."""


class SessionDataError(RuntimeError):
    """Raised when a discovered session cannot be read safely."""


"""Output adapter interface for the bt_joy UDP server."""

from __future__ import annotations

from typing import Protocol


class OutputAdapter(Protocol):
    """Protocol-specific sink for parsed joystick channel frames."""

    def __enter__(self) -> "OutputAdapter":
        ...

    def __exit__(self, *_exc: object) -> None:
        ...

    def startup_check(self) -> None:
        ...

    def write_channels(
        self,
        channels: list[int],
        sequence: int,
        timestamp_us: int,
    ) -> None:
        ...

    def enter_failsafe(self, reason: str) -> None:
        ...

    def exit_failsafe(self) -> None:
        ...

    def tick(self) -> None:
        ...

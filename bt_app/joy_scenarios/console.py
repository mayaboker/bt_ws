"""Console presentation for joystick scenarios."""

from __future__ import annotations

from collections.abc import Callable
import sys
import time
from typing import Protocol, TextIO

from joy_scenarios.models import ColorMode, TelemetrySnapshot, state_name
from joy_scenarios.telemetry import StateTransition


RESET = "\033[0m"
STATE_COLORS = {
    0: "\033[1;37m",
    1: "\033[1;34m",
    3: "\033[1;33m",
    4: "\033[1;31m",
    5: "\033[1;35m",
    6: "\033[1;36m",
    7: "\033[1;32m",
    8: "\033[1;96m",
}
UNKNOWN_COLOR = "\033[1;33m"


class ScenarioLogger(Protocol):
    def phase(self, message: str) -> None: ...

    def state_transition(self, transition: StateTransition) -> None: ...

    def failure(self, message: str) -> None: ...


class ConsoleScenarioLogger:
    def __init__(
        self,
        *,
        color: ColorMode = ColorMode.AUTO,
        stream: TextIO = sys.stdout,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.stream = stream
        self.wall_clock = wall_clock
        self.use_color = color is ColorMode.ALWAYS or (
            color is ColorMode.AUTO and stream.isatty()
        )

    def phase(self, message: str) -> None:
        self._write(message)

    def failure(self, message: str) -> None:
        self._write(message, "\033[1;31m")

    def state_transition(self, transition: StateTransition) -> None:
        snapshot = transition.snapshot
        altitude = self._altitude(snapshot)
        message = (
            f"STATE {state_name(transition.previous)} -> "
            f"{state_name(transition.current)} armed={snapshot.armed} "
            f"altitude={altitude}"
        )
        self._write(message, STATE_COLORS.get(transition.current, UNKNOWN_COLOR))

    def _write(self, message: str, color: str | None = None) -> None:
        timestamp = time.strftime("%H:%M:%S", time.localtime(self.wall_clock()))
        line = f"{timestamp} - {message}"
        if color and self.use_color:
            line = f"{color}{line}{RESET}"
        print(line, file=self.stream, flush=True)

    @staticmethod
    def _altitude(snapshot: TelemetrySnapshot) -> str:
        if snapshot.altitude_m is None:
            return "unknown"
        return f"{snapshot.altitude_m:.2f}m"

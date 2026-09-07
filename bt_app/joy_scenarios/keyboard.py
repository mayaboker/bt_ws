"""Nonblocking keyboard input for interactive joystick scenarios."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty
from types import TracebackType
from typing import TextIO


ARROW_KEYS = {
    b"\x1b[A": "up",
    b"\x1b[B": "down",
    b"\x1b[C": "right",
    b"\x1b[D": "left",
}


class TerminalKeyReader:
    """Read individual keys without blocking the scenario's RC send loop."""

    def __init__(self, stream: TextIO = sys.stdin) -> None:
        self.stream = stream
        self.fd = stream.fileno()
        self._saved_settings: list | None = None

    def __enter__(self) -> TerminalKeyReader:
        if not self.stream.isatty():
            raise RuntimeError(
                "manual tracker control requires an interactive terminal"
            )
        self._saved_settings = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if self._saved_settings is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved_settings)
            self._saved_settings = None
        return False

    def read_key(self, timeout_s: float) -> str | None:
        ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout_s))
        if not ready:
            return None

        first = os.read(self.fd, 1)
        if first == b"\x1b":
            sequence = bytearray(first)
            # Arrow keys arrive as a three-byte ANSI escape sequence. Use a
            # short bounded wait so an incomplete sequence cannot stop RC.
            for _ in range(2):
                ready, _, _ = select.select([self.fd], [], [], 0.01)
                if not ready:
                    break
                sequence.extend(os.read(self.fd, 1))
            return ARROW_KEYS.get(bytes(sequence))
        if first == b" ":
            return "enable"
        if first.lower() in (b"a", b"d", b"w", b"s"):
            return first.lower().decode("ascii")
        if first.lower() == b"q":
            return "cancel"
        return None

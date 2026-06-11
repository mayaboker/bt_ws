"""Linux joystick device reader."""

from __future__ import annotations

import os
import select
import struct
import fcntl
from dataclasses import dataclass, field
from pathlib import Path

JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
JS_EVENT_FORMAT = "IhBB"
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FORMAT)
JSIOCGNAME_BASE = 0x80006A13
JOYSTICK_NAME_SIZE = 128


@dataclass
class JoystickState:
    axes: list[int] = field(default_factory=list)
    buttons: list[int] = field(default_factory=list)


class JoystickOpenError(RuntimeError):
    pass


class JoystickNameMismatchError(RuntimeError):
    pass


class JoystickReadError(RuntimeError):
    pass


class JoystickReader:
    """Read the latest state from a Linux /dev/input/js* device."""

    def __init__(
        self,
        device: str | Path,
        axis_count: int = 7,
        button_count: int = 16,
        expected_name: str | None = None,
    ) -> None:
        self.device = Path(device)
        self.expected_name = expected_name
        self.name: str | None = None
        self.state = JoystickState([0] * axis_count, [0] * button_count)
        self._fd: int | None = None

    def __enter__(self) -> "JoystickReader":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def open(self) -> None:
        if self._fd is None:
            try:
                self._fd = os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)
            except FileNotFoundError as exc:
                raise JoystickOpenError(f"joystick device not found: {self.device}") from exc
            except PermissionError as exc:
                raise JoystickOpenError(f"permission denied opening joystick device: {self.device}") from exc
            except OSError as exc:
                raise JoystickOpenError(f"failed to open joystick device {self.device}: {exc}") from exc
            try:
                self.name = read_joystick_name(self._fd)
            except OSError as exc:
                self.close()
                raise JoystickOpenError(f"failed to read joystick name from {self.device}: {exc}") from exc
            if self.expected_name is not None and self.name != self.expected_name:
                self.close()
                raise JoystickNameMismatchError(
                    f"joystick name mismatch for {self.device}: expected {self.expected_name!r}, got {self.name!r}"
                )

    def close(self) -> None:
        if self._fd is not None:
            fd = self._fd
            self._fd = None
            try:
                os.close(fd)
            except OSError:
                pass

    def poll(self) -> JoystickState:
        """Drain all pending joystick events and return the latest state."""
        fd = self._require_fd()
        while True:
            try:
                readable, _, _ = select.select([fd], [], [], 0)
            except OSError as exc:
                raise JoystickReadError(f"failed to poll joystick device {self.device}: {exc}") from exc
            if not readable:
                return self.state
            try:
                event = os.read(fd, JS_EVENT_SIZE)
            except BlockingIOError:
                return self.state
            except OSError as exc:
                raise JoystickReadError(f"failed to read joystick device {self.device}: {exc}") from exc
            if len(event) != JS_EVENT_SIZE:
                return self.state
            self._apply_event(event)

    def _apply_event(self, event: bytes) -> None:
        _time_ms, value, event_type, number = struct.unpack(JS_EVENT_FORMAT, event)
        event_type &= ~JS_EVENT_INIT
        if event_type == JS_EVENT_AXIS:
            self._ensure_axis(number)
            self.state.axes[number] = value
        elif event_type == JS_EVENT_BUTTON:
            self._ensure_button(number)
            self.state.buttons[number] = 1 if value else 0

    def _ensure_axis(self, index: int) -> None:
        while len(self.state.axes) <= index:
            self.state.axes.append(0)

    def _ensure_button(self, index: int) -> None:
        while len(self.state.buttons) <= index:
            self.state.buttons.append(0)

    def _require_fd(self) -> int:
        if self._fd is None:
            raise RuntimeError("JoystickReader is not open")
        return self._fd


def read_joystick_name(fd: int, size: int = JOYSTICK_NAME_SIZE) -> str:
    buffer = bytearray(size)
    request = JSIOCGNAME_BASE | (size << 16)
    fcntl.ioctl(fd, request, buffer, True)
    return bytes(buffer).split(b"\x00", 1)[0].decode("utf-8", errors="replace")

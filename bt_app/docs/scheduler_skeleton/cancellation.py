from __future__ import annotations

from .commands import Command


class CancellationRegistry:
    def __init__(self) -> None:
        self._active_tokens: dict[str, object] = {}

    def new_token(self, command: Command) -> object | None:
        if command.key is None:
            return None
        return object()

    def activate(self, command: Command, token: object | None) -> None:
        if command.key is not None and token is not None:
            self._active_tokens[command.key] = token

    def remove(self, key: str) -> None:
        self._active_tokens[key] = object()

    def is_active(self, command: Command, token: object | None) -> bool:
        if command.key is None:
            return True
        return self._active_tokens.get(command.key) is token

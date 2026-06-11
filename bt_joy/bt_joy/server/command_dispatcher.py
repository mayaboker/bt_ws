"""Threaded MSP command dispatcher for the bt_joy server."""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from loguru import logger

from bt_joy.server.msp import MspAltitude, MspClient, MspStatus, normalize_rc_channels
from bt_joy.server.state import ServerStateSnapshot, ServerStateStore

CommandCallback = Callable[["MspCommandDispatcher", Any], None]
ErrorCallback = Callable[[BaseException], None]


class MspCommand(ABC):
    repeat_interval_s: float | None = None
    key: ClassVar[str | None] = None

    @abstractmethod
    def execute(self, dispatcher: "MspCommandDispatcher") -> Any:
        pass


@dataclass
class RawRcCommand(MspCommand):
    key: ClassVar[str | None] = "rc"
    channels: Sequence[int]
    repeat_interval_s: float | None = None

    def execute(self, dispatcher: "MspCommandDispatcher") -> list[int]:
        channels = normalize_rc_channels(self.channels)
        dispatcher.current_channels = channels
        dispatcher.msp.send_raw_rc(channels)
        dispatcher.state_store.update_commanded_channels(channels)
        return channels


@dataclass
class FunctionCommand(MspCommand):
    callback: Callable[["MspCommandDispatcher"], Any]
    repeat_interval_s: float | None = None
    key: ClassVar[str | None] = None

    def execute(self, dispatcher: "MspCommandDispatcher") -> Any:
        return self.callback(dispatcher)


@dataclass
class ScheduledCommand(MspCommand):
    command: MspCommand
    repeat_interval_s: float | None = None
    callback: CommandCallback | None = None
    key_override: str | None = None

    @property
    def key(self) -> str | None:
        if self.key_override is not None:
            return self.key_override
        return self.command.key

    def execute(self, dispatcher: "MspCommandDispatcher") -> Any:
        result = self.command.execute(dispatcher)
        if self.callback is not None:
            self.callback(dispatcher, result)
        return result


class MspCommandDispatcher:
    def __init__(
        self,
        msp: MspClient,
        initial_channels: Sequence[int] = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000),
        state_store: ServerStateStore | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.msp = msp
        self.current_channels = normalize_rc_channels(initial_channels)
        self.state_store = state_store or ServerStateStore()
        self._on_error = on_error
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()
        self._sequence = itertools.count()
        self._queue: list[tuple[float, int, object | None, MspCommand]] = []
        self._active_tokens: dict[str, object] = {}
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="bt-joy-msp-command-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def submit(self, command: MspCommand, delay_s: float = 0.0) -> None:
        token = object() if command.key is not None else None
        self._submit(command, delay_s=delay_s, token=token, replace=True)

    def schedule(
        self,
        command: MspCommand,
        interval_s: float | None = None,
        callback: CommandCallback | None = None,
        delay_s: float = 0.0,
        key: str | None = None,
    ) -> None:
        if interval_s is not None and interval_s <= 0:
            raise ValueError("interval_s must be greater than zero")

        self.submit(
            ScheduledCommand(
                command=command,
                repeat_interval_s=interval_s,
                callback=callback,
                key_override=key,
            ),
            delay_s=delay_s,
        )

    def set_rc(self, channels: Sequence[int], rate_hz: float) -> None:
        if rate_hz <= 0:
            raise ValueError("rate_hz must be greater than zero")
        self.schedule(RawRcCommand(channels=channels), interval_s=1.0 / rate_hz)

    def schedule_function(
        self,
        callback: Callable[["MspCommandDispatcher"], Any],
        interval_s: float,
        key: str,
        delay_s: float = 0.0,
    ) -> None:
        self.schedule(FunctionCommand(callback), interval_s=interval_s, delay_s=delay_s, key=key)

    def record_status(self, status: MspStatus) -> None:
        self.state_store.update_status(status)

    def record_rc(self, channels: Sequence[int]) -> None:
        self.state_store.update_fc_rc_channels(channels)

    def record_altitude(self, altitude: MspAltitude) -> None:
        self.state_store.update_altitude(altitude)

    def snapshot(self) -> ServerStateSnapshot:
        return self.state_store.snapshot()

    def _submit(
        self,
        command: MspCommand,
        delay_s: float,
        token: object | None,
        replace: bool,
    ) -> None:
        run_at = time.monotonic() + delay_s
        with self._lock:
            if replace and command.key is not None and token is not None:
                self._active_tokens[command.key] = token
            heapq.heappush(self._queue, (run_at, next(self._sequence), token, command))
        self._wake_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            item = self._pop_ready_command()
            if item is None:
                self._wait_until_next_command()
                continue

            _, _, token, command = item
            try:
                command.execute(self)
            except BaseException as exc:
                self._handle_error(exc)

            if command.repeat_interval_s is not None and not self._stop_event.is_set():
                if self._is_token_active(command, token):
                    self._submit(
                        command,
                        delay_s=command.repeat_interval_s,
                        token=token,
                        replace=False,
                    )

    def _pop_ready_command(self) -> tuple[float, int, object | None, MspCommand] | None:
        now = time.monotonic()
        with self._lock:
            while self._queue and self._queue[0][0] <= now:
                item = heapq.heappop(self._queue)
                _, _, token, command = item
                if self._is_token_active(command, token):
                    return item
            return None

    def _wait_until_next_command(self) -> None:
        with self._lock:
            delay_s = max(0.0, self._queue[0][0] - time.monotonic()) if self._queue else 0.1

        self._wake_event.wait(delay_s)
        self._wake_event.clear()

    def _handle_error(self, exc: BaseException) -> None:
        if self._on_error is not None:
            self._on_error(exc)
            return
        logger.warning("MSP dispatcher command failed: {}", exc)

    def _is_token_active(self, command: MspCommand, token: object | None) -> bool:
        if command.key is None:
            return True
        return self._active_tokens.get(command.key) is token

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .cancellation import CancellationRegistry
from .commands import Command, SchedulerContext
from .queue import QueuedCommand, TimedCommandQueue


ErrorCallback = Callable[[BaseException, Command], None]


class SchedulerWorker:
    def __init__(
        self,
        queue: TimedCommandQueue,
        cancellation: CancellationRegistry,
        lock: threading.Lock,
        wake_event: threading.Event,
        stop_event: threading.Event,
        context: SchedulerContext,
        set_last_error: Callable[[BaseException], None],
        on_error: ErrorCallback | None = None,
    ) -> None:
        self._queue = queue
        self._cancellation = cancellation
        self._lock = lock
        self._wake_event = wake_event
        self._stop_event = stop_event
        self._context = context
        self._set_last_error = set_last_error
        self._on_error = on_error

    def run(self) -> None:
        while not self._stop_event.is_set():
            item = self._pop_ready_command()
            if item is None:
                self._wait_until_next_command()
                continue

            try:
                item.command.execute(self._context)
            except BaseException as exc:
                self._handle_error(exc, item.command)

            if item.command.repeat_interval_s is not None:
                if self._cancellation.is_active(item.command, item.token):
                    self._requeue(item.command, item.token)

    def _pop_ready_command(self) -> QueuedCommand | None:
        now = time.monotonic()
        with self._lock:
            return self._queue.pop_ready(now, self._cancellation.is_active)

    def _wait_until_next_command(self) -> None:
        with self._lock:
            delay_s = self._queue.next_delay(time.monotonic())

        self._wake_event.wait(delay_s)
        self._wake_event.clear()

    def _requeue(self, command: Command, token: object | None) -> None:
        if command.repeat_interval_s is None:
            return

        run_at = time.monotonic() + command.repeat_interval_s
        with self._lock:
            self._queue.push(run_at, token, command)
        self._wake_event.set()

    def _handle_error(self, exc: BaseException, command: Command) -> None:
        if self._on_error is not None:
            self._on_error(exc, command)
            return
        self._set_last_error(exc)

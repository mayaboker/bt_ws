from __future__ import annotations

import threading
import time

from .cancellation import CancellationRegistry
from .commands import BasicSchedulerContext, Command, ScheduledCommand, SchedulerContext
from .queue import TimedCommandQueue
from .worker import ErrorCallback, SchedulerWorker


class CommandScheduler:
    def __init__(
        self,
        context: SchedulerContext | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.context = context or BasicSchedulerContext()
        self._queue = TimedCommandQueue()
        self._cancellation = CancellationRegistry()
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._worker = SchedulerWorker(
            queue=self._queue,
            cancellation=self._cancellation,
            lock=self._lock,
            wake_event=self._wake_event,
            stop_event=self._stop_event,
            context=self.context,
            set_last_error=self._set_last_error,
            on_error=on_error,
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 2.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def submit(self, command: Command, delay_s: float = 0.0) -> None:
        token = self._cancellation.new_token(command)
        self._submit(command, delay_s=delay_s, token=token, replace=True)

    def schedule(
        self,
        command: Command,
        interval_s: float,
        delay_s: float = 0.0,
        key: str | None = None,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be > 0")

        self.submit(
            ScheduledCommand(
                command=command,
                repeat_interval_s=interval_s,
                key_override=key,
            ),
            delay_s=delay_s,
        )

    def remove(self, key: str) -> None:
        with self._lock:
            self._cancellation.remove(key)
        self._wake_event.set()

    def _submit(
        self,
        command: Command,
        delay_s: float,
        token: object | None,
        replace: bool,
    ) -> None:
        run_at = time.monotonic() + delay_s
        with self._lock:
            if replace:
                self._cancellation.activate(command, token)
            self._queue.push(run_at, token, command)
        self._wake_event.set()

    def _set_last_error(self, exc: BaseException) -> None:
        self.context.last_error = exc

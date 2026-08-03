from __future__ import annotations

from collections.abc import Callable
import threading

from loguru import logger as log

from bt_joy.server.mavlink import (
    CommunicationResumedEvent,
    MavlinkServerConfig,
    MavlinkServerListener,
    NoCommunicationEvent,
    RcChannelsOverrideEvent,
)


class MavlinkListenerError(RuntimeError):
    """Report a MAVLink listener startup or runtime failure."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


class MavlinkListenerShutdownError(MavlinkListenerError):
    """Report a listener thread that could not be stopped cleanly."""


class MavlinkListenerService:
    """Run a MAVLink listener and dispatch its events on the caller thread."""

    def __init__(
        self,
        config: MavlinkServerConfig,
        on_rc: Callable[[RcChannelsOverrideEvent], None],
        on_timeout: Callable[[NoCommunicationEvent], None],
        on_resume: Callable[[CommunicationResumedEvent], None],
        on_failure: Callable[[MavlinkListenerError], None] | None = None,
    ) -> None:
        self.config = config
        self._on_rc = on_rc
        self._on_timeout = on_timeout
        self._on_resume = on_resume
        self._on_failure = on_failure

        self.listener: MavlinkServerListener | None = None
        self.thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._failure: MavlinkListenerError | None = None
        self._shutdown_error: MavlinkListenerShutdownError | None = None
        self._sequence = 0
        self._pending_rc: tuple[int, RcChannelsOverrideEvent] | None = None
        self._pending_communication: tuple[
            int, NoCommunicationEvent | CommunicationResumedEvent
        ] | None = None
        self._pending_failure: tuple[int, MavlinkListenerError] | None = None

    @property
    def failure(self) -> MavlinkListenerError | None:
        """Return the latest listener failure, if any."""
        with self._lifecycle_lock:
            return self._failure

    def start(self, timeout: float = 2.0) -> None:
        """Start the listener and wait until its connection is open."""
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        with self._lifecycle_lock:
            if self.thread is not None and self.thread.is_alive():
                return

            self._stop_event = threading.Event()
            self._ready_event = threading.Event()
            self._failure = None
            self._shutdown_error = None
            self._clear_pending()
            try:
                self.listener = MavlinkServerListener(
                    config=self.config,
                    on_rc_channels_override=self._queue_rc,
                    on_no_communication=self._queue_timeout,
                    on_communication_resumed=self._queue_resume,
                )
            except Exception as exc:
                raise MavlinkListenerError(
                    f"Failed to create MAVLink listener: {exc}", exc
                ) from exc

            self.thread = threading.Thread(
                target=self._run,
                name="bt-joy-mavlink-listener",
                daemon=True,
            )
            thread = self.thread
            ready_event = self._ready_event
            thread.start()

        if not ready_event.wait(timeout):
            error = MavlinkListenerError(
                f"MAVLink listener did not start within {timeout:.3f}s"
            )
            self._record_failure(error, notify=False)
            try:
                self.stop(timeout=timeout)
            except MavlinkListenerShutdownError as stop_error:
                raise MavlinkListenerError(
                    f"{error}; listener also failed to stop: {stop_error}",
                    stop_error,
                ) from stop_error
            raise error

        failure = self.failure
        if failure is not None:
            thread.join(timeout)
            raise failure

        log.info("Started MAVLink RC channel override listener")

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the listener, closing its connection if receive is blocked."""
        if timeout <= 0:
            raise ValueError("timeout must be > 0")

        with self._lifecycle_lock:
            thread = self.thread
            listener = self.listener

        if thread is None:
            return
        if not thread.is_alive():
            with self._lifecycle_lock:
                shutdown_error = self._shutdown_error
            if shutdown_error is not None:
                raise shutdown_error
            return

        self._stop_event.set()
        thread.join(timeout)
        close_error: Exception | None = None
        if thread.is_alive() and listener is not None:
            try:
                listener.close()
            except Exception as exc:
                close_error = exc
            thread.join(timeout)

        if thread.is_alive():
            raise MavlinkListenerShutdownError(
                f"MAVLink listener thread did not stop within {2 * timeout:.3f}s",
                close_error,
            ) from close_error
        if close_error is not None:
            raise MavlinkListenerShutdownError(
                f"Failed to close MAVLink listener: {close_error}", close_error
            ) from close_error
        with self._lifecycle_lock:
            shutdown_error = self._shutdown_error
        if shutdown_error is not None:
            raise shutdown_error

    def dispatch_pending(self) -> None:
        """Invoke coalesced listener callbacks on the calling thread."""
        with self._pending_lock:
            pending = [
                item
                for item in (
                    self._pending_rc,
                    self._pending_communication,
                    self._pending_failure,
                )
                if item is not None
            ]
            self._pending_rc = None
            self._pending_communication = None
            self._pending_failure = None

        for _, event in sorted(pending, key=lambda item: item[0]):
            if isinstance(event, RcChannelsOverrideEvent):
                self._on_rc(event)
            elif isinstance(event, NoCommunicationEvent):
                self._on_timeout(event)
            elif isinstance(event, CommunicationResumedEvent):
                self._on_resume(event)
            elif self._on_failure is not None:
                self._on_failure(event)

    def _run(self) -> None:
        listener = self.listener
        if listener is None:
            self._record_failure(
                MavlinkListenerError("MAVLink listener was not initialized"),
                notify=False,
            )
            self._ready_event.set()
            return

        opened = False
        try:
            listener.open()
            opened = True
            self._ready_event.set()
            while not self._stop_event.is_set():
                listener.process_once()
        except Exception as exc:
            if not self._stop_event.is_set():
                error = MavlinkListenerError(
                    f"MAVLink listener failed: {exc}", exc
                )
                self._record_failure(error, notify=opened)
                log.opt(exception=exc).error("MAVLink listener failed")
        finally:
            self._ready_event.set()
            try:
                listener.close()
            except Exception as exc:
                error = MavlinkListenerShutdownError(
                    f"Failed to close MAVLink listener: {exc}", exc
                )
                with self._lifecycle_lock:
                    if self._shutdown_error is None:
                        self._shutdown_error = error
                if self.failure is None and not self._stop_event.is_set():
                    runtime_error = MavlinkListenerError(
                        str(error), exc
                    )
                    self._record_failure(runtime_error, notify=opened)
                log.opt(exception=exc).error("Failed to close MAVLink listener")

    def _record_failure(
        self, error: MavlinkListenerError, *, notify: bool
    ) -> None:
        with self._lifecycle_lock:
            if self._failure is None:
                self._failure = error
            recorded_error = self._failure
        if notify:
            with self._pending_lock:
                if self._pending_failure is None:
                    self._pending_failure = (
                        self._next_sequence_locked(),
                        recorded_error,
                    )

    def _queue_rc(self, event: RcChannelsOverrideEvent) -> None:
        with self._pending_lock:
            self._pending_rc = (self._next_sequence_locked(), event)

    def _queue_timeout(self, event: NoCommunicationEvent) -> None:
        with self._pending_lock:
            self._pending_communication = (
                self._next_sequence_locked(),
                event,
            )

    def _queue_resume(self, event: CommunicationResumedEvent) -> None:
        with self._pending_lock:
            self._pending_communication = (
                self._next_sequence_locked(),
                event,
            )

    def _next_sequence_locked(self) -> int:
        self._sequence += 1
        return self._sequence

    def _clear_pending(self) -> None:
        with self._pending_lock:
            self._pending_rc = None
            self._pending_communication = None
            self._pending_failure = None

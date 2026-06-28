from __future__ import annotations

import heapq
import itertools
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from bt_app.msp.bt_v2 import BetaflightMspClient


RcChannels = tuple[int, int, int, int, int, int, int, int]
StateCallback = Callable[[dict[str, object]], None]
AltitudeCallback = Callable[[dict[str, float]], None]
ErrorCallback = Callable[[BaseException], None]
CommandCallback = Callable[["MspCommandDispatcher", Any], None]


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

    def execute(self, dispatcher: "MspCommandDispatcher") -> RcChannels:
        channels = dispatcher.normalize_channels(self.channels)
        dispatcher.current_channels = channels
        dispatcher.msp.send_raw_rc(channels)
        return channels


@dataclass
class ReadStateCommand(MspCommand):
    key: ClassVar[str | None] = "state"
    repeat_interval_s: float | None = None

    def execute(self, dispatcher: "MspCommandDispatcher") -> dict[str, object]:
        dispatcher.last_state = dispatcher.msp.read_state()
        if dispatcher.on_state is not None:
            dispatcher.on_state(dispatcher.last_state)
        return dispatcher.last_state


@dataclass
class ReadAltitudeCommand(MspCommand):
    key: ClassVar[str | None] = "altitude"
    repeat_interval_s: float | None = None

    def execute(self, dispatcher: "MspCommandDispatcher") -> dict[str, float]:
        dispatcher.last_altitude = dispatcher.msp.read_altitude()
        if dispatcher.on_altitude is not None:
            dispatcher.on_altitude(dispatcher.last_altitude)
        return dispatcher.last_altitude


@dataclass
class HoverAtAltitudeCommand(MspCommand):
    key: ClassVar[str | None] = "rc"
    target_altitude_m: float
    base_channels: Sequence[int]
    kp: float = 40.0
    throttle_min: int = 1000
    throttle_max: int = 1800
    repeat_interval_s: float | None = None

    def execute(self, dispatcher: "MspCommandDispatcher") -> RcChannels:
        altitude = dispatcher.last_altitude or dispatcher.msp.read_altitude()
        dispatcher.last_altitude = altitude
        altitude_m = float(altitude.get("altitude_m", 0.0))
        error_m = self.target_altitude_m - altitude_m

        channels = list(dispatcher.normalize_channels(self.base_channels))
        throttle = int(channels[2] + self.kp * error_m)
        channels[2] = max(self.throttle_min, min(self.throttle_max, throttle))

        dispatcher.current_channels = dispatcher.normalize_channels(channels)
        dispatcher.msp.send_raw_rc(dispatcher.current_channels)
        return dispatcher.current_channels


@dataclass
class FunctionCommand(MspCommand):
    callback: Callable[["MspCommandDispatcher"], None]
    repeat_interval_s: float | None = None

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


class MspCommandDispatcher:
    def __init__(
        self,
        msp: BetaflightMspClient,
        initial_channels: Sequence[int] = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000),
        on_state: StateCallback | None = None,
        on_altitude: AltitudeCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.msp = msp
        self.on_state = on_state
        self.on_altitude = on_altitude
        self.current_channels = self.normalize_channels(initial_channels)
        self.last_state: dict[str, object] | None = None
        self.last_altitude: dict[str, float] | None = None

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
            name="msp-command-dispatcher",
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
            raise ValueError("interval_s must be > 0")

        self.submit(
            ScheduledCommand(
                command=command,
                repeat_interval_s=interval_s,
                callback=callback,
                key_override=key,
            ),
            delay_s=delay_s,
        )

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

    def set_rc(self, channels: Sequence[int], rate_hz: float = 50.0) -> None:
        self.schedule(
            RawRcCommand(
                channels=channels,
            ),
            interval_s=1.0 / rate_hz,
        )

    def schedule_state(self, interval_s: float = 1.0) -> None:
        self.schedule(ReadStateCommand(), interval_s=interval_s)

    def schedule_altitude(self, interval_s: float = 0.1) -> None:
        self.schedule(ReadAltitudeCommand(), interval_s=interval_s)

    def hover_at_altitude(
        self,
        target_altitude_m: float,
        base_channels: Sequence[int],
        rate_hz: float = 50.0,
        kp: float = 40.0,
    ) -> None:
        self.schedule(
            HoverAtAltitudeCommand(
                target_altitude_m=target_altitude_m,
                base_channels=base_channels,
                kp=kp,
            ),
            interval_s=1.0 / rate_hz,
        )

    def arm_sequence(
        self,
        neutral_s: float = 2.0,
        arm_s: float = 2.0,
        rate_hz: float = 50.0,
    ) -> None:
        disarmed = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)
        armed = (1500, 1500, 1000, 1500, 1900, 1000, 1000, 1000)

        self.set_rc(disarmed, rate_hz=rate_hz)
        self.submit(
            FunctionCommand(lambda dispatcher: dispatcher.set_rc(armed, rate_hz=rate_hz)),
            delay_s=neutral_s,
        )
        self.submit(FunctionCommand(lambda dispatcher: dispatcher.set_rc(disarmed, rate_hz=rate_hz)), delay_s=neutral_s + arm_s)

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
            if self._queue:
                delay_s = max(0.0, self._queue[0][0] - time.monotonic())
            else:
                delay_s = 0.1

        self._wake_event.wait(delay_s)
        self._wake_event.clear()

    def _handle_error(self, exc: BaseException) -> None:
        if self._on_error is not None:
            self._on_error(exc)
            return
        raise exc

    def _is_token_active(self, command: MspCommand, token: object | None) -> bool:
        if command.key is None:
            return True
        return self._active_tokens.get(command.key) is token

    def normalize_channels(self, channels: Sequence[int]) -> RcChannels:
        if len(channels) != 8:
            raise ValueError("RC command must contain exactly 8 channels")

        normalized = tuple(int(channel) for channel in channels)
        for channel in normalized:
            if not 800 <= channel <= 2200:
                raise ValueError(f"RC channel out of expected range: {channel}")

        return normalized  # type: ignore[return-value]


RcCommandDispatcher = MspCommandDispatcher

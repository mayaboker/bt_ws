from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable
import signal

Command = Callable[[], None]


@dataclass
class ScheduledCommand:
    name: str
    interval: float
    callback: Command
    next_run: float = field(default_factory=time.monotonic)

    def due(self, now: float) -> bool:
        return now >= self.next_run

    def run(self, now: float) -> None:
        self.callback()

        # Better than: self.next_run = now + self.interval
        # This keeps stable timing and avoids drift.
        self.next_run += self.interval

        # If we are very late, skip missed periods
        while self.next_run <= now:
            self.next_run += self.interval

class Scheduler:
    def __init__(self) -> None:
        self.commands: list[ScheduledCommand] = []

    def every(self, name: str, interval: float, callback: Command) -> None:
        now = time.monotonic()
        self.commands.append(
            ScheduledCommand(
                name=name,
                interval=interval,
                callback=callback,
                next_run=now + interval,
            )
        )

    def tick(self) -> "ScheduledCommand":
        now = time.monotonic()

        for command in self.commands:
            if command.due(now):
                yield command


def send_heartbeat() -> None:
    print("heartbeat", time.monotonic())


def dump_status() -> None:
    print("status", time.monotonic())

class Runner():
    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler
        self._running = False

    def start(self) -> None:
        self._running = True
        while self._running:
            for command in self.scheduler.tick():
                print(f"Running command: {command.name}")
                command.run(time.monotonic())
            time.sleep(0.02)

    def stop(self) -> None:
        self._running = False

    
if __name__ == "__main__":
    scheduler = Scheduler()
    runner =Runner(scheduler)
    scheduler.every("heartbeat", 1.0, send_heartbeat)  # every 1 second

    signal.signal(signal.SIGINT, lambda sig, frame: runner.stop())
    signal.signal(signal.SIGTERM, lambda sig, frame: runner.stop())

    runner.start()
    signal.pause()


    
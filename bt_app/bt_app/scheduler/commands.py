from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol


class SchedulerContext(Protocol):
    last_error: BaseException | None


@dataclass
class BasicSchedulerContext:
    last_error: BaseException | None = None


class Command(ABC):
    key: ClassVar[str | None] = None
    repeat_interval_s: float | None = None

    @abstractmethod
    def execute(self, scheduler: SchedulerContext) -> Any:
        pass


@dataclass
class ScheduledCommand(Command):
    command: Command
    repeat_interval_s: float | None = None
    key_override: str | None = None

    @property
    def key(self) -> str | None:
        if self.key_override is not None:
            return self.key_override
        return self.command.key

    def execute(self, scheduler: SchedulerContext) -> Any:
        return self.command.execute(scheduler)

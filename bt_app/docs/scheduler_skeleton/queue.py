from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field

from .commands import Command


@dataclass(order=True)
class QueuedCommand:
    run_at: float
    sequence: int
    token: object | None = field(compare=False)
    command: Command = field(compare=False)


class TimedCommandQueue:
    def __init__(self) -> None:
        self._items: list[QueuedCommand] = []
        self._sequence = itertools.count()

    def push(self, run_at: float, token: object | None, command: Command) -> None:
        item = QueuedCommand(
            run_at=run_at,
            sequence=next(self._sequence),
            token=token,
            command=command,
        )
        heapq.heappush(self._items, item)

    def pop_ready(
        self,
        now: float,
        is_active: Callable[[Command, object | None], bool],
    ) -> QueuedCommand | None:
        while self._items and self._items[0].run_at <= now:
            item = heapq.heappop(self._items)
            if is_active(item.command, item.token):
                return item
        return None

    def next_delay(self, now: float, default_s: float = 0.1) -> float:
        if not self._items:
            return default_s
        return max(0.0, self._items[0].run_at - now)

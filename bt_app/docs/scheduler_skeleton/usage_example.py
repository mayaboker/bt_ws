from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import cast

from . import BasicSchedulerContext, Command, CommandScheduler, SchedulerContext


@dataclass
class AppContext(BasicSchedulerContext):
    messages: list[str] = field(default_factory=list)


@dataclass
class PrintCommand(Command):
    message: str

    def execute(self, context: SchedulerContext) -> None:
        app_context = cast(AppContext, context)
        app_context.messages.append(self.message)
        print(self.message)


def main() -> None:
    context = AppContext()
    scheduler = CommandScheduler(context)
    scheduler.start()

    try:
        scheduler.submit(PrintCommand("runs once"))
        scheduler.schedule(PrintCommand("runs repeatedly"), interval_s=0.5, key="printer")
        time.sleep(2.0)
        scheduler.remove("printer")
    finally:
        scheduler.stop()

    print(f"messages stored in context: {len(context.messages)}")


if __name__ == "__main__":
    main()

"""Application controller pipeline between UDP input and output adapters."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from bt_joy.server.adapters.base import OutputAdapter
from bt_joy.server.automation import TakeoffAutomation
from bt_joy.server.config import TakeoffAutomationConfig
from bt_joy.server.state import ServerStateStore


@dataclass(frozen=True)
class JoystickFrame:
    channels: tuple[int, ...]
    sequence: int
    timestamp_us: int
    source: tuple[str, int]


class JoystickController:
    """Pass-through controller that owns the final RC decision point."""

    def __init__(
        self,
        adapter: OutputAdapter,
        state_store: ServerStateStore | None = None,
        takeoff_automation_config: TakeoffAutomationConfig | None = None,
    ) -> None:
        self.adapter = adapter
        self.state_store = state_store or ServerStateStore()
        self.takeoff_automation = TakeoffAutomation(
            takeoff_automation_config or TakeoffAutomationConfig()
        )

    def handle_frame(self, frame: JoystickFrame) -> bool:
        self.state_store.update_manual_channels(frame.channels)
        output_channels = self.takeoff_automation.apply(frame.channels, self.state_store)
        self.state_store.update_output_channels(output_channels)

        try:
            self.adapter.write_channels(list(output_channels), frame.sequence, frame.timestamp_us)
        except Exception as exc:
            logger.error("failed to write channels for seq={}: {}", frame.sequence, exc)
            return False
        return True

    def enter_failsafe(self, reason: str) -> None:
        self.adapter.enter_failsafe(reason)

    def exit_failsafe(self) -> None:
        self.adapter.exit_failsafe()

    def tick(self) -> None:
        self.adapter.tick()

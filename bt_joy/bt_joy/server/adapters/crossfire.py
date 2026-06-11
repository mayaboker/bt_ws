"""Placeholder Crossfire output adapter.

This adapter intentionally does not implement CRSF output yet. It exists so the
server can load and test the adapter configuration path before the protocol
writer is added.
"""

from __future__ import annotations

from loguru import logger


class CrossfireOutputAdapter:
    def __enter__(self) -> "CrossfireOutputAdapter":
        logger.warning("Crossfire adapter is a placeholder; received channels will be ignored")
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def startup_check(self) -> None:
        logger.info("Crossfire placeholder startup check complete")

    def write_channels(
        self,
        channels: list[int],
        sequence: int,
        timestamp_us: int,
    ) -> None:
        del timestamp_us
        logger.debug("Crossfire placeholder ignored seq={} channels={}", sequence, channels)

    def enter_failsafe(self, reason: str) -> None:
        logger.warning("Crossfire placeholder entering failsafe mode: {}", reason)

    def exit_failsafe(self) -> None:
        logger.warning("Crossfire placeholder exiting failsafe mode; client data recovered")

    def tick(self) -> None:
        pass

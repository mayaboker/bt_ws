from typing import Sequence, TypeVar

from bt_app.common import AETR1234


T = TypeVar("T")




def format_channels(channels: Sequence[T], formatter: Sequence = tuple(AETR1234)) -> str:
    lines = []

    for index, channel in enumerate(formatter):
        if index >= len(channels):
            break
        name = getattr(channel, "name", str(channel))
        lines.append(f"{name}: {channels[index]}")

    for index in range(len(formatter), len(channels)):
        lines.append(f"AUX{index - 3}: {channels[index]}")

    row = ", ".join(lines) + "\n"
    return row

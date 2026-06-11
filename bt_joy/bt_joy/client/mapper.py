"""Map joystick axes and buttons to packed channel values."""

from __future__ import annotations

from bt_joy.client.config import ChannelConfig
from bt_joy.client.joystick import JoystickState


def map_channels(state: JoystickState, channels: tuple[ChannelConfig, ...]) -> list[int]:
    return [_map_channel(state, channel) for channel in channels]


def _map_channel(state: JoystickState, channel: ChannelConfig) -> int:
    if channel.source == "constant":
        return _clamp_channel(channel.value or 0)
    if channel.source == "button":
        pressed = _read_button(state, channel.index or 0)
        return _clamp_channel(channel.on if pressed else channel.off)
    if channel.source == "axis":
        raw_value = _read_axis(state, channel.index or 0)
        return _map_axis(raw_value, channel)
    raise ValueError(f"Unsupported channel source: {channel.source}")


def _map_axis(raw_value: int, channel: ChannelConfig) -> int:
    in_span = channel.in_max - channel.in_min
    if in_span == 0:
        raise ValueError(f"Axis channel {channel.name} has equal in_min and in_max")

    normalized = (raw_value - channel.in_min) / in_span
    normalized = max(0.0, min(1.0, normalized))
    signed = (normalized * 2.0) - 1.0
    if abs(signed) < channel.deadband:
        signed = 0.0
    if channel.invert:
        signed *= -1.0

    output = channel.out_min + ((signed + 1.0) / 2.0) * (channel.out_max - channel.out_min)
    return _clamp_channel(round(output))


def _read_axis(state: JoystickState, index: int) -> int:
    if index >= len(state.axes):
        return 0
    return state.axes[index]


def _read_button(state: JoystickState, index: int) -> int:
    if index >= len(state.buttons):
        return 0
    return state.buttons[index]


def _clamp_channel(value: int) -> int:
    return max(0, min(65535, int(value)))

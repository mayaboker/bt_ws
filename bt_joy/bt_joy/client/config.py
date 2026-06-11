"""YAML configuration for joystick channel mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    source: str
    index: int | None = None
    value: int | None = None
    in_min: int = -32767
    in_max: int = 32767
    out_min: int = 1000
    out_max: int = 2000
    off: int = 1000
    on: int = 2000
    deadband: float = 0.0
    invert: bool = False


@dataclass(frozen=True)
class UdpConfig:
    host: str = "127.0.0.1"
    port: int = 9000


@dataclass(frozen=True)
class KeepaliveRttWarningConfig:
    enabled: bool = True
    threshold_ms: float = 100.0
    window_s: float = 10.0
    count: int = 3
    cooldown_s: float = 10.0


@dataclass(frozen=True)
class JoyConfig:
    device: str = "/dev/input/js0"
    expected_name: str | None = None
    mapping: str | None = None
    poll_hz: float = 50.0
    keepalive_interval: float = 1.0
    keepalive_timeout: float = 1.0
    joystick_reconnect_interval: float = 1.0
    keepalive_rtt_warning: KeepaliveRttWarningConfig = field(
        default_factory=KeepaliveRttWarningConfig
    )
    axes: int = 7
    buttons: int = 16
    udp: UdpConfig = UdpConfig()
    channels: tuple[ChannelConfig, ...] = ()


def load_config(path: str | Path) -> JoyConfig:
    yaml_path = Path(path)
    with yaml_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("Joystick YAML must contain a mapping")
    return parse_config(data)


def load_mapping(path: str | Path) -> tuple[ChannelConfig, ...]:
    yaml_path = Path(path)
    with yaml_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("Joystick mapping YAML must contain a mapping")
    return parse_mapping(data)


def parse_config(data: dict[str, Any]) -> JoyConfig:
    udp_data = data.get("udp", {})
    if not isinstance(udp_data, dict):
        raise ValueError("udp must be a mapping")

    rtt_warning_data = data.get("keepalive_rtt_warning", {})
    if not isinstance(rtt_warning_data, dict):
        raise ValueError("keepalive_rtt_warning must be a mapping")

    channels_data = data.get("channels", [])
    if not isinstance(channels_data, list):
        raise ValueError("channels must be a list")

    return JoyConfig(
        device=str(data.get("device", "/dev/input/js0")),
        expected_name=None if data.get("expected_name") is None else str(data["expected_name"]),
        mapping=None if data.get("mapping") is None else str(data["mapping"]),
        poll_hz=float(data.get("poll_hz", 50.0)),
        keepalive_interval=float(data.get("keepalive_interval", 1.0)),
        keepalive_timeout=float(data.get("keepalive_timeout", 1.0)),
        joystick_reconnect_interval=float(data.get("joystick_reconnect_interval", 1.0)),
        keepalive_rtt_warning=KeepaliveRttWarningConfig(
            enabled=bool(rtt_warning_data.get("enabled", True)),
            threshold_ms=float(rtt_warning_data.get("threshold_ms", 100.0)),
            window_s=float(rtt_warning_data.get("window_s", 10.0)),
            count=int(rtt_warning_data.get("count", 3)),
            cooldown_s=float(rtt_warning_data.get("cooldown_s", 10.0)),
        ),
        axes=int(data.get("axes", 7)),
        buttons=int(data.get("buttons", 16)),
        udp=UdpConfig(
            host=str(udp_data.get("host", "127.0.0.1")),
            port=int(udp_data.get("port", 9000)),
        ),
        channels=tuple(_parse_channel(index, item) for index, item in enumerate(channels_data)),
    )


def parse_mapping(data: dict[str, Any]) -> tuple[ChannelConfig, ...]:
    channels_data = data.get("channels", [])
    if not isinstance(channels_data, list):
        raise ValueError("channels must be a list")
    return tuple(_parse_channel(index, item) for index, item in enumerate(channels_data))


def _parse_channel(index: int, data: Any) -> ChannelConfig:
    if not isinstance(data, dict):
        raise ValueError(f"channel {index} must be a mapping")

    source = str(data.get("source", "")).lower()
    if source not in {"axis", "button", "constant"}:
        raise ValueError(f"channel {index} source must be axis, button, or constant")

    input_index = data.get("index")
    if source in {"axis", "button"} and input_index is None:
        raise ValueError(f"channel {index} requires index")

    value = data.get("value")
    if source == "constant" and value is None:
        raise ValueError(f"channel {index} requires value")

    return ChannelConfig(
        name=str(data.get("name", f"ch{index + 1}")),
        source=source,
        index=None if input_index is None else int(input_index),
        value=None if value is None else int(value),
        in_min=int(data.get("in_min", -32767)),
        in_max=int(data.get("in_max", 32767)),
        out_min=int(data.get("out_min", 1000)),
        out_max=int(data.get("out_max", 2000)),
        off=int(data.get("off", 1000)),
        on=int(data.get("on", 2000)),
        deadband=float(data.get("deadband", 0.0)),
        invert=bool(data.get("invert", False)),
    )

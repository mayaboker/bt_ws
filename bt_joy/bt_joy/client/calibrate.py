"""Interactive joystick calibration for bt_joy clients."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
from typing import Callable

import yaml

from bt_joy.client.config import JoyConfig
from bt_joy.client.joystick import JoystickReader, JoystickState

CHANNEL_ORDER = ("roll", "pitch", "throttle", "yaw", "arm", "aux2")
DEADBAND_CHANNELS = {"roll", "pitch", "yaw"}
AXIS_CHANGE_THRESHOLD = 1000
DEFAULT_OUTPUT_DIR = Path("output/joy")
DEFAULT_CONFIG_PREFIX = "default"
BANNER_COLOR = "\033[96m"
BANNER_RESET = "\033[0m"
CONFIG_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class CalibrationError(RuntimeError):
    """Raised when a joystick movement cannot be mapped to one input."""


def run_calibration(
    joy_config: JoyConfig,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    input_func: Callable[[str], str] = input,
    print_func: Callable[[str], None] = print,
) -> tuple[Path, Path]:
    """Run interactive calibration and write client/mapping YAML files."""

    with JoystickReader(
        joy_config.device,
        axis_count=joy_config.axes,
        button_count=joy_config.buttons,
    ) as reader:
        joystick_name = (reader.name or "").strip()
        config_prefix = _prompt_config_prefix(input_func, print_func)
        mapping_config_name = f"{config_prefix}_mapping.yaml"
        channels = []
        for channel_name in CHANNEL_ORDER:
            while True:
                print_func(_channel_banner(channel_name))
                min_state = _capture_state(
                    reader,
                    f"Put {channel_name} in minimum position, then press Enter",
                    input_func,
                )
                max_state = _capture_state(
                    reader,
                    f"Put {channel_name} in maximum position, then press Enter",
                    input_func,
                )
                try:
                    channels.append(_build_channel(channel_name, min_state, max_state))
                    break
                except CalibrationError as exc:
                    print_func(f"{exc}. Please retry {channel_name}.")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    mapping_path = output_path / mapping_config_name
    client_path = output_path / f"{config_prefix}.yaml"
    mapping_path.write_text(_dump_mapping_yaml(channels), encoding="utf-8")
    calibrated_config = replace(
        joy_config,
        expected_name=joystick_name or None,
        mapping=mapping_config_name,
        channels=(),
    )
    client_path.write_text(_dump_client_yaml(calibrated_config), encoding="utf-8")
    return client_path, mapping_path


def _capture_state(
    reader: JoystickReader,
    prompt: str,
    input_func: Callable[[str], str],
) -> JoystickState:
    input_func(f"{prompt}: ")
    state = reader.poll()
    return JoystickState(axes=list(state.axes), buttons=list(state.buttons))


def _build_channel(name: str, min_state: JoystickState, max_state: JoystickState) -> dict[str, object]:
    detected = detect_changed_input(min_state, max_state)
    if detected[0] == "axis":
        channel: dict[str, object] = {
            "name": name,
            "source": "axis",
            "index": detected[1],
            "in_min": detected[2],
            "in_max": detected[3],
            "out_min": 1000,
            "out_max": 2000,
        }
        if name in DEADBAND_CHANNELS:
            channel["deadband"] = 0.03
        return channel

    return {
        "name": name,
        "source": "button",
        "index": detected[1],
        "off": 1000,
        "on": 2000,
    }


def detect_changed_input(min_state: JoystickState, max_state: JoystickState) -> tuple:
    """Return the single changed input as axis/button mapping data."""

    axis_changes = _axis_changes(min_state.axes, max_state.axes)
    if axis_changes:
        largest_delta = max(change[1] for change in axis_changes)
        if largest_delta >= AXIS_CHANGE_THRESHOLD:
            largest = [change for change in axis_changes if change[1] == largest_delta]
            if len(largest) == 1:
                index = largest[0][0]
                return ("axis", index, _read(min_state.axes, index), _read(max_state.axes, index))
            raise CalibrationError("multiple axis inputs changed by the same amount")

    changed_buttons = _changed_buttons(min_state.buttons, max_state.buttons)
    if len(changed_buttons) == 1:
        return ("button", changed_buttons[0])
    if len(changed_buttons) > 1:
        raise CalibrationError("multiple button inputs changed")
    raise CalibrationError("no joystick input changed enough")


def _axis_changes(min_axes: list[int], max_axes: list[int]) -> list[tuple[int, int]]:
    axis_count = max(len(min_axes), len(max_axes))
    return [
        (index, abs(_read(max_axes, index) - _read(min_axes, index)))
        for index in range(axis_count)
        if _read(max_axes, index) != _read(min_axes, index)
    ]


def _changed_buttons(min_buttons: list[int], max_buttons: list[int]) -> list[int]:
    button_count = max(len(min_buttons), len(max_buttons))
    return [
        index
        for index in range(button_count)
        if _read(min_buttons, index) != _read(max_buttons, index)
    ]


def _read(values: list[int], index: int) -> int:
    if index >= len(values):
        return 0
    return values[index]


def _prompt_config_prefix(
    input_func: Callable[[str], str],
    print_func: Callable[[str], None],
) -> str:
    while True:
        config_prefix = input_func("Enter config file name: ").strip()
        if is_valid_config_prefix(config_prefix):
            return config_prefix
        print_func(
            "Invalid config file name. Use only letters, numbers, dot, underscore, or hyphen."
        )


def is_valid_config_prefix(config_prefix: str) -> bool:
    return bool(CONFIG_PREFIX_PATTERN.fullmatch(config_prefix))


def _channel_banner(channel_name: str) -> str:
    title = f"Calibrating {channel_name}"
    line = "=" * (len(title) + 4)
    return f"\n{BANNER_COLOR}{line}\n  {title}\n{line}{BANNER_RESET}"


def _dump_mapping_yaml(channels: list[dict[str, object]]) -> str:
    return yaml.safe_dump({"channels": channels}, sort_keys=False)


def _dump_client_yaml(joy_config: JoyConfig) -> str:
    data = {
        "device": joy_config.device,
        "expected_name": joy_config.expected_name,
        "mapping": joy_config.mapping,
        "poll_hz": joy_config.poll_hz,
        "keepalive_interval": joy_config.keepalive_interval,
        "keepalive_timeout": joy_config.keepalive_timeout,
        "joystick_reconnect_interval": joy_config.joystick_reconnect_interval,
        "keepalive_rtt_warning": {
            "enabled": joy_config.keepalive_rtt_warning.enabled,
            "threshold_ms": joy_config.keepalive_rtt_warning.threshold_ms,
            "window_s": joy_config.keepalive_rtt_warning.window_s,
            "count": joy_config.keepalive_rtt_warning.count,
            "cooldown_s": joy_config.keepalive_rtt_warning.cooldown_s,
        },
        "axes": joy_config.axes,
        "buttons": joy_config.buttons,
        "udp": {
            "host": joy_config.udp.host,
            "port": joy_config.udp.port,
        },
    }
    return yaml.safe_dump(data, sort_keys=False)

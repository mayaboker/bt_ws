"""YAML configuration for the bt_joy MSP server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TakeoffAutomationConfig:
    enabled: bool = True
    require_manual_arm: bool = True
    trigger_channel: str = "aux4"
    arm_channel: str = "aux1"
    trigger_on: int = 1800
    arm_on: int = 2000
    target_altitude_m: float = 5.0
    target_tolerance_m: float = 0.2
    throttle_base: int = 1300
    throttle_min: int = 1000
    throttle_max: int = 1800
    pid_kp: float = 80.0
    pid_ki: float = 10.0
    pid_kd: float = 40.0
    pid_integral_limit: float = 10.0


@dataclass(frozen=True)
class MspServerConfig:
    adapter: str = "msp"
    listen_host: str = "0.0.0.0"
    listen_port: int = 9000
    output: str = "tcp"
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 5761
    serial_device: Path | None = None
    baudrate: int = 115200
    rc_rate_hz: float = 50.0
    failsafe_channels: tuple[int, ...] = (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000)
    status_interval: float = 1.0
    status_timeout: float = 1.0
    rc_read_interval: float = 1.0
    rc_read_timeout: float = 0.05
    altitude_interval: float = 0.2
    altitude_timeout: float = 0.05
    startup_probe_attempts: int = 3
    startup_probe_interval: float = 1.0
    udp_timeout: float = 0.05
    failsafe_joystick_timeout: float = 1.0
    takeoff_automation: TakeoffAutomationConfig = TakeoffAutomationConfig()
    log_level: str = "INFO"


def load_config(path: str | Path) -> MspServerConfig:
    yaml_path = Path(path)
    with yaml_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("MSP server YAML must contain a mapping")
    return parse_config(data)


def parse_config(data: dict[str, Any]) -> MspServerConfig:
    adapter = str(data.get("adapter", "msp")).lower()
    if adapter not in {"msp", "crossfire"}:
        raise ValueError("adapter must be msp or crossfire")

    output = str(data.get("output", "tcp")).lower()
    if output not in {"tcp", "serial"}:
        raise ValueError("output must be tcp or serial")

    serial_device = data.get("serial_device")
    takeoff_automation_data = data.get("takeoff_automation", {})
    if not isinstance(takeoff_automation_data, dict):
        raise ValueError("takeoff_automation must be a mapping")

    return MspServerConfig(
        adapter=adapter,
        listen_host=str(data.get("listen_host", "0.0.0.0")),
        listen_port=int(data.get("listen_port", 9000)),
        output=output,
        tcp_host=str(data.get("tcp_host", "127.0.0.1")),
        tcp_port=int(data.get("tcp_port", 5761)),
        serial_device=None if serial_device in (None, "") else Path(str(serial_device)),
        baudrate=int(data.get("baudrate", 115200)),
        rc_rate_hz=float(data.get("rc_rate_hz", 50.0)),
        failsafe_channels=tuple(int(value) for value in data.get(
            "failsafe_channels",
            (1500, 1500, 1000, 1500, 1000, 1000, 1000, 1000),
        )),
        status_interval=float(data.get("status_interval", 0.0)),
        status_timeout=float(data.get("status_timeout", 1.0)),
        rc_read_interval=float(data.get("rc_read_interval", 0.1)),
        rc_read_timeout=float(data.get("rc_read_timeout", 0.05)),
        altitude_interval=float(data.get("altitude_interval", 0.2)),
        altitude_timeout=float(data.get("altitude_timeout", 0.05)),
        startup_probe_attempts=int(data.get("startup_probe_attempts", 3)),
        startup_probe_interval=float(data.get("startup_probe_interval", 1.0)),
        udp_timeout=float(data.get("udp_timeout", 0.05)),
        failsafe_joystick_timeout=float(data.get("failsafe_joystick_timeout", 1.0)),
        takeoff_automation=_parse_takeoff_automation(takeoff_automation_data),
        log_level=str(data.get("log_level", "INFO")).upper(),
    )


def _parse_takeoff_automation(data: dict[str, Any]) -> TakeoffAutomationConfig:
    return TakeoffAutomationConfig(
        enabled=bool(data.get("enabled", False)),
        require_manual_arm=bool(data.get("require_manual_arm", False)),
        trigger_channel=str(data.get("trigger_channel", "aux4")).lower(),
        arm_channel=str(data.get("arm_channel", "aux1")).lower(),
        trigger_on=int(data.get("trigger_on", 1800)),
        arm_on=int(data.get("arm_on", 2000)),
        target_altitude_m=float(data.get("target_altitude_m", 5.0)),
        target_tolerance_m=float(data.get("target_tolerance_m", 0.2)),
        throttle_base=int(data.get("throttle_base", 1300)),
        throttle_min=int(data.get("throttle_min", 1000)),
        throttle_max=int(data.get("throttle_max", 1800)),
        pid_kp=float(data.get("pid_kp", 80.0)),
        pid_ki=float(data.get("pid_ki", 10.0)),
        pid_kd=float(data.get("pid_kd", 40.0)),
        pid_integral_limit=float(data.get("pid_integral_limit", 10.0)),
    )

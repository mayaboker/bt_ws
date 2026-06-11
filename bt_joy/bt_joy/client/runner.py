"""Runtime loop for reading joystick state and sending UDP frames."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Deque

from loguru import logger

from bt_joy.client import LogThrottle
from bt_joy.client.config import JoyConfig, KeepaliveRttWarningConfig
from bt_joy.client.joystick import (
    JoystickOpenError,
    JoystickReadError,
    JoystickReader,
)
from bt_joy.client.mapper import map_channels
from bt_joy.protocol import (
    pack_frame,
    pack_keepalive_request,
    timestamp_us,
    unpack_keepalive_response,
)
from bt_joy.client.udp import UdpSender

JOYSTICK_FRAME_SEND_ERROR_LOG_INTERVAL = 5.0
KEEPALIVE_SEND_ERROR_LOG_INTERVAL = 5.0

@dataclass
class _KeepaliveRttWarningState:
    high_rtt_events: Deque[float] = field(default_factory=deque)
    last_warning_at: float | None = None


@dataclass
class _RunnerState:
    sequence: int = 0
    keepalive_sequence: int = 0
    pending_keepalives: dict[int, tuple[float, int]] = field(default_factory=dict)
    next_keepalive_at: float | None = None
    rtt_warning_state: _KeepaliveRttWarningState = field(default_factory=_KeepaliveRttWarningState)
    log_throttle: LogThrottle = field(default_factory=LogThrottle)


def run(
    config: JoyConfig,
    log_mapping: bool = False,
    keepalive_interval: float = 1.0,
    keepalive_timeout: float = 1.0,
) -> None:
    if config.poll_hz <= 0:
        raise ValueError("poll_hz must be greater than zero")
    if keepalive_interval < 0:
        raise ValueError("keepalive_interval must be greater than or equal to zero")
    if keepalive_timeout <= 0:
        raise ValueError("keepalive_timeout must be greater than zero")
    if config.joystick_reconnect_interval < 0:
        raise ValueError("joystick_reconnect_interval must be greater than or equal to zero")
    _validate_keepalive_rtt_warning_config(config.keepalive_rtt_warning)
    period = 1.0 / config.poll_hz
    runner_state = _RunnerState(
        next_keepalive_at=time.monotonic() if keepalive_interval > 0 else None
    )
    channel_names = [channel.name for channel in config.channels]

    with UdpSender(config.udp.host, config.udp.port) as sender:
        while True:
            try:
                with JoystickReader(
                    config.device,
                    config.axes,
                    config.buttons,
                    config.expected_name,
                ) as joystick:
                    logger.info("joystick connected device={} name={}", config.device, joystick.name or "unknown")
                    _run_connected_joystick(
                        config,
                        joystick,
                        sender,
                        runner_state,
                        channel_names,
                        period,
                        log_mapping,
                        keepalive_interval,
                        keepalive_timeout,
                    )
            except (JoystickOpenError, JoystickReadError) as exc:
                logger.warning(
                    "joystick unavailable: {}; retrying in {:.3f}s",
                    exc,
                    config.joystick_reconnect_interval,
                )
                _wait_for_joystick_reconnect(
                    sender,
                    runner_state,
                    config,
                    keepalive_interval,
                    keepalive_timeout,
                )


def _run_connected_joystick(
    config: JoyConfig,
    joystick: JoystickReader,
    sender: UdpSender,
    runner_state: _RunnerState,
    channel_names: list[str],
    period: float,
    log_mapping: bool,
    keepalive_interval: float,
    keepalive_timeout: float,
) -> None:
    previous_logged_channels: list[int] | None = None
    next_tick = time.monotonic()

    while True:
        now = time.monotonic()
        if not log_mapping:
            _send_keepalive_if_due(
                sender,
                runner_state,
                now,
                keepalive_interval,
                keepalive_timeout,
            )

        state = joystick.poll()
        channels = map_channels(state, config.channels)
        if log_mapping and channels != previous_logged_channels:
            formatted_channels = _format_mapping_channels(
                channel_names,
                channels,
                previous_logged_channels,
            )
            previous_logged_channels = channels
            logger.opt(colors=True).info(
                "seq={} axes={} buttons={} channels="
                + formatted_channels,
                runner_state.sequence,
                state.axes,
                state.buttons,
            )
        if not log_mapping:
            try:
                sender.send(pack_frame(channels, runner_state.sequence))
            except OSError as exc:
                if runner_state.log_throttle.should_log(
                    "joystick-frame-send-error",
                    JOYSTICK_FRAME_SEND_ERROR_LOG_INTERVAL,
                ):
                    logger.error("joystick frame seq={} send failed: {}", runner_state.sequence, exc)
            else:
                runner_state.sequence = (runner_state.sequence + 1) & 0xFFFFFFFF

        if not log_mapping:
            _log_keepalive_responses(
                sender,
                runner_state.pending_keepalives,
                runner_state.rtt_warning_state,
                config.keepalive_rtt_warning,
            )
            _log_expired_keepalives(runner_state.pending_keepalives, time.monotonic())

        next_tick += period
        sleep_for = next_tick - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
        else:
            next_tick = time.monotonic()


def _wait_for_joystick_reconnect(
    sender: UdpSender,
    runner_state: _RunnerState,
    config: JoyConfig,
    keepalive_interval: float,
    keepalive_timeout: float,
) -> None:
    reconnect_at = time.monotonic() + config.joystick_reconnect_interval
    while True:
        now = time.monotonic()
        _send_keepalive_if_due(
            sender,
            runner_state,
            now,
            keepalive_interval,
            keepalive_timeout,
        )
        _log_keepalive_responses(
            sender,
            runner_state.pending_keepalives,
            runner_state.rtt_warning_state,
            config.keepalive_rtt_warning,
        )
        _log_expired_keepalives(runner_state.pending_keepalives, time.monotonic())
        sleep_for = min(0.1, reconnect_at - time.monotonic())
        if sleep_for <= 0:
            return
        time.sleep(sleep_for)


def _send_keepalive_if_due(
    sender: UdpSender,
    runner_state: _RunnerState,
    now: float,
    keepalive_interval: float,
    keepalive_timeout: float,
) -> None:
    if runner_state.next_keepalive_at is None or now < runner_state.next_keepalive_at:
        return

    client_sent_at = timestamp_us()
    try:
        sender.send(pack_keepalive_request(runner_state.keepalive_sequence, timestamp=client_sent_at))
    except OSError as exc:
        if runner_state.log_throttle.should_log(
            "keepalive-send-error",
            KEEPALIVE_SEND_ERROR_LOG_INTERVAL,
        ):
            logger.error("keepalive seq={} send failed: {}", runner_state.keepalive_sequence, exc)
    else:
        runner_state.pending_keepalives[runner_state.keepalive_sequence] = (
            now + keepalive_timeout,
            client_sent_at,
        )
        logger.debug("sent keepalive seq={}", runner_state.keepalive_sequence)
    runner_state.keepalive_sequence = (runner_state.keepalive_sequence + 1) & 0xFFFFFFFF
    runner_state.next_keepalive_at = now + keepalive_interval


def _format_mapping_channels(
    channel_names: list[str],
    channels: list[int],
    previous_channels: list[int] | None,
) -> str:
    parts = []
    for index, value in enumerate(channels):
        name = channel_names[index] if index < len(channel_names) else f"ch{index + 1}"
        text = f"{name}={value}"
        if previous_channels is None or index >= len(previous_channels) or previous_channels[index] != value:
            text = f"<yellow>{text}</yellow>"
        parts.append(text)
    return " ".join(parts)


def _log_keepalive_responses(
    sender: UdpSender,
    pending_keepalives: dict[int, tuple[float, int]],
    rtt_warning_state: _KeepaliveRttWarningState | None = None,
    rtt_warning_config: KeepaliveRttWarningConfig | None = None,
) -> None:
    if rtt_warning_state is None:
        rtt_warning_state = _KeepaliveRttWarningState()
    if rtt_warning_config is None:
        rtt_warning_config = KeepaliveRttWarningConfig()

    for packet in sender.receive_available():
        try:
            sequence, client_sent_at, server_received_at, server_delay_us = unpack_keepalive_response(
                packet.payload
            )
        except ValueError as exc:
            logger.error(
                "from {}:{} invalid keepalive response bytes={} error={}",
                packet.address[0],
                packet.address[1],
                len(packet.payload),
                exc,
            )
            continue

        pending = pending_keepalives.pop(sequence, None)
        if pending is None:
            logger.error(
                "keepalive seq={} unexpected or late response from {}:{}",
                sequence,
                packet.address[0],
                packet.address[1],
            )
            continue

        _deadline, expected_client_sent_at = pending
        if client_sent_at != expected_client_sent_at:
            logger.error(
                "keepalive seq={} response timestamp mismatch expected={} got={}",
                sequence,
                expected_client_sent_at,
                client_sent_at,
            )
            continue

        round_trip_us = max(0, timestamp_us() - client_sent_at)
        should_warn = _should_warn_keepalive_round_trip(
            round_trip_us,
            now=time.monotonic(),
            state=rtt_warning_state,
            config=rtt_warning_config,
        )
        log_keepalive = logger.warning if should_warn else logger.debug
        log_keepalive(
            "keepalive seq={} server_delay_ms={:.3f} round_trip_ms={:.3f} server_received_at_us={}",
            sequence,
            server_delay_us / 1000.0,
            round_trip_us / 1000.0,
            server_received_at,
        )


def _should_warn_keepalive_round_trip(
    round_trip_us: int,
    now: float,
    state: _KeepaliveRttWarningState,
    config: KeepaliveRttWarningConfig | None = None,
    threshold_us: int | None = None,
    window_s: float | None = None,
    warning_count: int | None = None,
    cooldown_s: float | None = None,
) -> bool:
    if config is None:
        config = KeepaliveRttWarningConfig()
    if not config.enabled:
        return False

    threshold_us = int(config.threshold_ms * 1000.0) if threshold_us is None else threshold_us
    window_s = config.window_s if window_s is None else window_s
    warning_count = config.count if warning_count is None else warning_count
    cooldown_s = config.cooldown_s if cooldown_s is None else cooldown_s

    cutoff = now - window_s
    while state.high_rtt_events and state.high_rtt_events[0] < cutoff:
        state.high_rtt_events.popleft()

    if round_trip_us <= threshold_us:
        return False

    state.high_rtt_events.append(now)
    if len(state.high_rtt_events) < warning_count:
        return False
    if state.last_warning_at is not None and now - state.last_warning_at < cooldown_s:
        return False

    state.last_warning_at = now
    return True


def _validate_keepalive_rtt_warning_config(config: KeepaliveRttWarningConfig) -> None:
    if config.threshold_ms < 0:
        raise ValueError("keepalive_rtt_warning.threshold_ms must be greater than or equal to zero")
    if config.window_s <= 0:
        raise ValueError("keepalive_rtt_warning.window_s must be greater than zero")
    if config.count <= 0:
        raise ValueError("keepalive_rtt_warning.count must be greater than zero")
    if config.cooldown_s < 0:
        raise ValueError("keepalive_rtt_warning.cooldown_s must be greater than or equal to zero")


def _log_expired_keepalives(
    pending_keepalives: dict[int, tuple[float, int]],
    now: float,
) -> None:
    expired_sequences = [
        sequence for sequence, (deadline, _sent_at) in pending_keepalives.items() if now >= deadline
    ]
    for sequence in expired_sequences:
        _deadline, client_sent_at = pending_keepalives.pop(sequence)
        age_ms = (timestamp_us() - client_sent_at) / 1000.0
        logger.error("keepalive seq={} timed out after {:.3f}ms with no server response", sequence, age_ms)

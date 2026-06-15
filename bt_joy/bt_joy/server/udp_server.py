"""Generic UDP server for parsed bt_joy joystick packets."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

from loguru import logger

from bt_joy.protocol import (
    is_keepalive_request,
    pack_keepalive_response,
    timestamp_us,
    unpack_frame,
    unpack_keepalive_request,
)
from bt_joy.server.controller import JoystickController, JoystickFrame


@dataclass
class FailsafeMonitor:
    joystick_timeout: float
    last_joystick_at: float
    in_failsafe: bool = False

    @classmethod
    def create(cls, joystick_timeout: float) -> "FailsafeMonitor":
        now = time.monotonic()
        return cls(
            joystick_timeout=joystick_timeout,
            last_joystick_at=now,
        )

    def record_joystick(self) -> None:
        """
        Record that a valid joystick frame was received.
        This resets the failsafe timer."""
        self.last_joystick_at = time.monotonic()

    def evaluate(self, controller: JoystickController) -> None:
        now = time.monotonic()
        stale_reasons = self._stale_reasons(now)

        if stale_reasons and not self.in_failsafe:
            reason = ", ".join(stale_reasons)
            self.in_failsafe = True
            try:
                controller.enter_failsafe(reason)
            except Exception as exc:
                logger.error("failsafe enter handler failed: {}", exc)
            return

        if not stale_reasons and self.in_failsafe:
            self.in_failsafe = False
            try:
                controller.exit_failsafe()
            except Exception as exc:
                logger.error("failsafe exit handler failed: {}", exc)

    def _stale_reasons(self, now: float) -> list[str]:
        reasons = []
        if self.joystick_timeout > 0:
            age = now - self.last_joystick_at
            if age >= self.joystick_timeout:
                reasons.append(f"joystick data stale for {age:.3f}s")
        return reasons


def run_udp_server(
    controller: JoystickController,
    listen_host: str,
    listen_port: int,
    udp_timeout: float,
    failsafe_joystick_timeout: float,
) -> None:
    """
    Wait for UDP data up to udp_timeout.
    - If timeout happens, no packet is processed, but failsafe and controller.tick() still run.
    - If keepalive arrives, respond immediately.
    - If joystick frame arrives, parse it and forward it to the controller.
    - If the controller accepts the frame, update the last valid joystick timestamp.
    - Every iteration checks failsafe state and ticks the controller.
    - parse_joystick_packet(...) converts raw UDP bytes into a JoystickFrame.
    - handle_keepalive_packet(...) sends a small response back to the sender and logs latency.
    """
    failsafe = FailsafeMonitor.create(
        joystick_timeout=failsafe_joystick_timeout,
    )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.bind((listen_host, listen_port))
        udp_socket.settimeout(udp_timeout)

        while True:
            try:
                payload, address = udp_socket.recvfrom(4096)
            except socket.timeout:
                payload = None
                address = None
            except KeyboardInterrupt:
                logger.info("stopping")
                return

            if payload is not None and address is not None:
                # keep alive 
                if is_keepalive_request(payload):
                    handle_keepalive_packet(udp_socket, payload, address)
                    failsafe.evaluate(controller)
                    controller.tick()
                    continue
                # joystick
                frame = parse_joystick_packet(payload, address)
                if frame is not None:
                    try:
                        handled = controller.handle_frame(frame)
                    except Exception as exc:
                        logger.error("controller frame handler failed: {}", exc)
                        handled = False
                    if handled:
                        failsafe.record_joystick()

            # even if no packet or an invalid packet was received, 
            # we still want to evaluate failsafe and tick the controller
            failsafe.evaluate(controller)
            controller.tick()


def parse_joystick_packet(
    payload: bytes,
    address: tuple[str, int],
) -> JoystickFrame | None:
    """
    unpack and map joystick request to channels array and return a JoystickFrame object.
    """
    try:
        sequence, frame_timestamp_us, channels = unpack_frame(payload)
    except ValueError as exc:
        logger.warning("from {}:{} invalid joystick packet: {}", address[0], address[1], exc)
        logger.debug("invalid payload hex={}", payload.hex())
        return None

    age_ms = (time.time_ns() // 1000 - frame_timestamp_us) / 1000.0
    logger.debug(
        "seq={} age_ms={:.3f} rc_channels={} source={}:{}",
        sequence,
        age_ms,
        channels,
        address[0],
        address[1],
    )
    return JoystickFrame(
        channels=tuple(channels),
        sequence=sequence,
        timestamp_us=frame_timestamp_us,
        source=address,
    )


def handle_keepalive_packet(
    udp_socket: socket.socket,
    payload: bytes,
    address: tuple[str, int],
) -> bool:
    if not is_keepalive_request(payload):
        return False

    received_at = timestamp_us()
    try:
        sequence, client_sent_at = unpack_keepalive_request(payload)
    except ValueError as exc:
        logger.warning("from {}:{} invalid keepalive packet: {}", address[0], address[1], exc)
        logger.debug("invalid keepalive payload hex={}", payload.hex())
        return False

    delay_us = max(0, received_at - client_sent_at)
    udp_socket.sendto(pack_keepalive_response(sequence, client_sent_at, received_at), address)
    logger.debug(
        "keepalive seq={} delay_ms={:.3f} source={}:{}",
        sequence,
        delay_us / 1000.0,
        address[0],
        address[1],
    )
    return True

"""Mock UDP receiver for bt_joy frames."""

from __future__ import annotations

import socket
import sys
import time

import click
from loguru import logger

from bt_joy import __version__
from bt_joy.protocol import (
    is_keepalive_request,
    pack_keepalive_response,
    timestamp_us,
    unpack_frame,
    unpack_keepalive_request,
)


@click.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="UDP host/interface to bind.")
@click.option("--port", default=9000, show_default=True, type=int, help="UDP port to bind.")
@click.option(
    "--timeout",
    type=float,
    help="Optional receive timeout in seconds. Exits if no packet arrives before timeout.",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    type=click.Choice(["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR"]),
    help="Log verbosity.",
)
@click.version_option(__version__, prog_name="bt-joy-mock-server")
def main(host: str, port: int, timeout: float | None, log_level: str) -> None:
    """Listen for bt_joy UDP packets and print decoded channel values."""
    _configure_logging(log_level)
    logger.info("bt-joy-mock-server {}", __version__)
    logger.info("listening on udp://{}:{}", host, port)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.bind((host, port))
        if timeout is not None:
            server.settimeout(timeout)

        while True:
            try:
                payload, address = server.recvfrom(4096)
            except socket.timeout:
                logger.warning("no UDP packet received for {:.3f}s; exiting", timeout)
                return
            except KeyboardInterrupt:
                logger.info("stopping")
                return

            if _handle_keepalive_packet(server, payload, address):
                continue
            _log_packet(payload, address)


def _configure_logging(log_level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | {module}:{line} | {message}",
    )


def _log_packet(payload: bytes, address: tuple[str, int]) -> None:
    try:
        sequence, timestamp, channels = unpack_frame(payload)
    except ValueError as exc:
        logger.warning(
            "from {}:{} invalid packet bytes={} error={}",
            address[0],
            address[1],
            len(payload),
            exc,
        )
        logger.debug("invalid payload hex={}", payload.hex())
        return

    age_ms = (time.time_ns() // 1000 - timestamp) / 1000.0
    logger.info(
        "from {}:{} seq={} timestamp_us={} age_ms={:.3f} channels={}",
        address[0],
        address[1],
        sequence,
        timestamp,
        age_ms,
        channels,
    )


def _handle_keepalive_packet(
    server: socket.socket,
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
        return True

    delay_us = max(0, received_at - client_sent_at)
    server.sendto(pack_keepalive_response(sequence, client_sent_at, received_at), address)
    logger.info(
        "from {}:{} keepalive seq={} delay_ms={:.3f}",
        address[0],
        address[1],
        sequence,
        delay_us / 1000.0,
    )
    return True


if __name__ == "__main__":
    main()

"""Command-line parsing for bt-analysis."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LOGS_DIRECTORY = Path("bt_app/logs/blackbox")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8002


@dataclass(frozen=True, slots=True)
class CliOptions:
    command: str
    logs_directory: Path
    host: str
    port: int


def parse_cli_args(args: Sequence[str] | None = None) -> CliOptions:
    parser = argparse.ArgumentParser(
        prog="bt-analysis",
        description="View the latest BT flight blackbox log.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Run the local analysis dashboard.")
    run.add_argument(
        "--logs-dir",
        type=Path,
        default=DEFAULT_LOGS_DIRECTORY,
        help=f"Blackbox directory (default: {DEFAULT_LOGS_DIRECTORY}).",
    )
    run.add_argument("--host", default=DEFAULT_HOST)
    run.add_argument("--port", type=_port, default=DEFAULT_PORT)
    parsed = parser.parse_args(args)
    return CliOptions(
        command=parsed.command,
        logs_directory=parsed.logs_dir,
        host=parsed.host,
        port=parsed.port,
    )


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port

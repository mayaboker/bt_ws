"""bt-analysis process entrypoint."""

from __future__ import annotations

from collections.abc import Sequence

import uvicorn

from bt_analysis.cli import parse_cli_args
from bt_analysis.repository import BlackboxRepository
from bt_analysis.web import create_app


def main(args: Sequence[str] | None = None) -> None:
    options = parse_cli_args(args)
    if options.command != "run":  # pragma: no cover - argparse owns this invariant
        raise RuntimeError(f"Unknown command: {options.command}")
    repository = BlackboxRepository(options.logs_directory)
    app = create_app(repository)
    uvicorn.run(app, host=options.host, port=options.port)


if __name__ == "__main__":
    main()


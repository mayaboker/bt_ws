from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TypeAlias

import click

DEFAULT_VIDEO = Path(__file__).resolve().parents[1] / "data" / "vtest.avi"


@dataclass(frozen=True)
class VersionCommand:
    pass


@dataclass(frozen=True)
class PlayCommand:
    video: Path


Command: TypeAlias = VersionCommand | PlayCommand | int


@click.group()
def _cli() -> None:
    """BT GStreamer command line utilities."""


@_cli.command()
def version() -> VersionCommand:
    """Print the bt-gst package version."""
    return VersionCommand()


@_cli.command("play")
@click.argument(
    "video",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def play(video: Path | None) -> PlayCommand:
    """Play a video file from the data folder using GStreamer's gtksink."""
    video_path = video or DEFAULT_VIDEO
    if not video_path.exists():
        raise click.ClickException(f"video file not found: {video_path}")
    return PlayCommand(video=video_path)


def parse_args(args: Sequence[str] | None = None) -> Command:
    try:
        return _cli.main(args=list(args) if args is not None else None, standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1

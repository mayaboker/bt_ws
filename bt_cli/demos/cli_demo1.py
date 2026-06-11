import shlex
import typer
import yaml
from pathlib import Path

app = typer.Typer()


def dump_data():
    return {
        "camera": {
            "fps": 30,
            "width": 1280,
        },
        "controller": {
            "kp": 1.0,
            "ki": 0.0,
        },
    }


def dump_yaml():
    return yaml.safe_dump(dump_data(), sort_keys=False)


@app.command()
def get(name: str):
    typer.echo(f"get {name}")


@app.command()
def set(name: str, value: str):
    typer.echo(f"set {name} = {value}")


@app.command()
def list():
    typer.echo("list params")


@app.command()
def dump(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write YAML to a file instead of stdout.",
    ),
):
    result = dump_yaml()

    if output:
        output.write_text(result)
        typer.echo(f"Written to {output}")
    else:
        typer.echo(result)


@app.command()
def shell():
    typer.echo("Param shell. Type 'exit' to quit.")

    while True:
        line = input("param> ").strip()

        if not line:
            continue

        if line in {"exit", "quit"}:
            break

        output_file = None

        if ">" in line:
            line, output_file = line.split(">", 1)
            output_file = output_file.strip()

        args = shlex.split(line)

        if not args:
            continue

        command = args[0]

        if command == "get":
            result = f"get {args[1]}"

        elif command == "set":
            result = f"set {args[1]} = {args[2]}"

        elif command == "list":
            result = "list params"

        elif command == "dump":
            result = dump_yaml()

        else:
            typer.echo(f"Unknown command: {command}")
            continue

        if output_file:
            Path(output_file).write_text(result)
            typer.echo(f"Written to {output_file}")
        else:
            typer.echo(result)


if __name__ == "__main__":
    app()

import typer
from bti_cli.param.command import app as param_app

app = typer.Typer(help="Main CLI", no_args_is_help=True)

app.add_typer(param_app, name="param")


if __name__ == "__main__":
    app()

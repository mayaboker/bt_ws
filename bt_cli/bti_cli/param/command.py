import json
from typing import Annotated, Any

import typer

from bti_cli.transport import (
    ZmqRequestResponseTransport,
    ZmqTransportError,
    ZmqTransportTimeout,
)

app = typer.Typer(help="Parameter commands", no_args_is_help=True)


EndpointOption = Annotated[
    str,
    typer.Option(
        "--endpoint",
        "-e",
        envvar="BTI_ZMQ_ENDPOINT",
        help="ZMQ remote endpoint.",
    ),
]
TimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout-ms",
        envvar="BTI_ZMQ_TIMEOUT_MS",
        help="Remote response timeout in milliseconds.",
    ),
]


def execute_remote(
    action: str,
    params: dict[str, Any] | None = None,
    endpoint: str = "tcp://127.0.0.1:5555",
    timeout_ms: int = 3000,
) -> Any:
    transport = ZmqRequestResponseTransport(endpoint=endpoint, timeout_ms=timeout_ms)

    try:
        return transport.request(action, params)
    except ZmqTransportTimeout as exc:
        typer.echo(f"Transport timeout: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ZmqTransportError as exc:
        typer.echo(f"Remote error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def echo_result(result: Any) -> None:
    if isinstance(result, (dict, list)):
        typer.echo(json.dumps(result, indent=2))
    elif result is not None:
        typer.echo(result)


# -----------------------
# param list
# -----------------------
@app.command("list")
def list_params(
    full: bool = typer.Option(
        False,
        "--full",
        "-f",
        help="Include parameter type and limits.",
    ),
    endpoint: EndpointOption = "tcp://127.0.0.1:5555",
    timeout_ms: TimeoutOption = 3000,
):
    """List parameters"""
    echo_result(
        execute_remote(
            "list",
            {"full": full},
            endpoint=endpoint,
            timeout_ms=timeout_ms,
        )
    )


# -----------------------
# param dump
# -----------------------
@app.command("dump")
def dump_params(
    endpoint: EndpointOption = "tcp://127.0.0.1:5555",
    timeout_ms: TimeoutOption = 3000,
):
    """Dump all parameters"""
    echo_result(execute_remote("dump", endpoint=endpoint, timeout_ms=timeout_ms))


# -----------------------
# param save
# -----------------------
@app.command("save")
def save_params(
    endpoint: EndpointOption = "tcp://127.0.0.1:5555",
    timeout_ms: TimeoutOption = 3000,
):
    """Save current parameter values to the source YAML file"""
    echo_result(execute_remote("save", endpoint=endpoint, timeout_ms=timeout_ms))


# -----------------------
# param describe
# -----------------------
@app.command("describe")
def describe_params(
    endpoint: EndpointOption = "tcp://127.0.0.1:5555",
    timeout_ms: TimeoutOption = 3000,
):
    """Describe parameter defaults and limits"""
    echo_result(execute_remote("describe", endpoint=endpoint, timeout_ms=timeout_ms))


# -----------------------
# param get
# -----------------------
@app.command("get")
def get_param(
    name: str,
    endpoint: EndpointOption = "tcp://127.0.0.1:5555",
    timeout_ms: TimeoutOption = 3000,
):
    """Get parameter value"""
    echo_result(
        execute_remote(
            "get",
            {"name": name},
            endpoint=endpoint,
            timeout_ms=timeout_ms,
        )
    )


# -----------------------
# param set
# -----------------------
@app.command("set")
def set_param(
    name: str,
    value: str,
    endpoint: EndpointOption = "tcp://127.0.0.1:5555",
    timeout_ms: TimeoutOption = 3000,
):
    """Set parameter value"""
    echo_result(
        execute_remote(
            "set",
            {"name": name, "value": value},
            endpoint=endpoint,
            timeout_ms=timeout_ms,
        )
    )

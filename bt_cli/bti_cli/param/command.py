import json
from typing import Annotated, Any, Callable, TypeVar

import typer

from bti_cli.transport import (
    MavlinkParameterTransport,
    MavlinkTransportError,
    MavlinkTransportTimeout,
)


app = typer.Typer(help="MAVLink parameter commands", no_args_is_help=True)
T = TypeVar("T")

EndpointOption = Annotated[
    str,
    typer.Option(
        "--endpoint",
        "-e",
        envvar="BTI_MAVLINK_ENDPOINT",
        help="MAVLink endpoint as HOST:PORT.",
    ),
]
TimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout-ms",
        envvar="BTI_MAVLINK_TIMEOUT_MS",
        help="Response timeout per attempt in milliseconds.",
    ),
]
SystemOption = Annotated[int, typer.Option("--system", help="Target system ID.")]
ComponentOption = Annotated[
    int,
    typer.Option("--component", help="Target component ID."),
]


def parse_endpoint(endpoint: str) -> tuple[str, int]:
    host, separator, raw_port = endpoint.rpartition(":")
    if not separator or not host:
        raise typer.BadParameter("Endpoint must be HOST:PORT")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise typer.BadParameter("Endpoint port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise typer.BadParameter("Endpoint port must be between 1 and 65535")
    return host, port


def execute_remote(
    operation: Callable[[MavlinkParameterTransport], T],
    *,
    endpoint: str,
    timeout_ms: int,
    system: int,
    component: int,
) -> T:
    try:
        with MavlinkParameterTransport(
            parse_endpoint(endpoint),
            target_system=system,
            target_component=component,
            timeout_s=timeout_ms / 1000.0,
        ) as transport:
            return operation(transport)
    except MavlinkTransportTimeout as exc:
        typer.echo(f"Transport timeout: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except (MavlinkTransportError, OSError) as exc:
        typer.echo(f"MAVLink error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def echo_result(result: Any) -> None:
    if isinstance(result, (dict, list)):
        typer.echo(json.dumps(result, indent=2))
    elif result is not None:
        typer.echo(result)


@app.command("list")
def list_params(
    endpoint: EndpointOption = "127.0.0.1:14551",
    timeout_ms: TimeoutOption = 3000,
    system: SystemOption = 1,
    component: ComponentOption = 1,
) -> None:
    """List parameter IDs, values, types, and indices."""
    values = execute_remote(
        lambda transport: transport.list(),
        endpoint=endpoint,
        timeout_ms=timeout_ms,
        system=system,
        component=component,
    )
    echo_result([value.as_dict() for value in values])


@app.command("get")
def get_param(
    name: str,
    endpoint: EndpointOption = "127.0.0.1:14551",
    timeout_ms: TimeoutOption = 3000,
    system: SystemOption = 1,
    component: ComponentOption = 1,
) -> None:
    """Get a parameter by its canonical MAVLink ID."""
    value = execute_remote(
        lambda transport: transport.get(name),
        endpoint=endpoint,
        timeout_ms=timeout_ms,
        system=system,
        component=component,
    )
    echo_result(value.as_dict())


@app.command("set")
def set_param(
    name: str,
    value: str,
    endpoint: EndpointOption = "127.0.0.1:14551",
    timeout_ms: TimeoutOption = 3000,
    system: SystemOption = 1,
    component: ComponentOption = 1,
) -> None:
    """Set a parameter by its canonical MAVLink ID."""
    updated = execute_remote(
        lambda transport: transport.set(name, value),
        endpoint=endpoint,
        timeout_ms=timeout_ms,
        system=system,
        component=component,
    )
    echo_result(updated.as_dict())


@app.command("save")
def save_params(
    endpoint: EndpointOption = "127.0.0.1:14551",
    timeout_ms: TimeoutOption = 3000,
    system: SystemOption = 1,
    component: ComponentOption = 1,
) -> None:
    """Persist current parameters; the vehicle must be disarmed."""
    execute_remote(
        lambda transport: transport.save(),
        endpoint=endpoint,
        timeout_ms=timeout_ms,
        system=system,
        component=component,
    )
    typer.echo("Parameters saved")

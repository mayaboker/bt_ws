from __future__ import annotations

import asyncio

import httpx
import pytest

import bt_analysis.main as main_module
from bt_analysis.cli import (
    DEFAULT_HOST,
    DEFAULT_LOGS_DIRECTORY,
    DEFAULT_PORT,
    parse_cli_args,
)
from bt_analysis.repository import BlackboxRepository
from bt_analysis.web import create_app


async def get_responses(app, *paths):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return [await client.get(path) for path in paths]


def test_dashboard_and_api_serve_latest_session(tmp_path, make_session):
    make_session("flight", start_utc_ns=100)
    app = create_app(BlackboxRepository(tmp_path))

    index, latest, velocity = asyncio.run(
        get_responses(
            app,
            "/",
            "/api/latest",
            "/api/sessions/flight/velocity",
        )
    )

    assert index.status_code == 200
    assert "Blackbox analysis" in index.text
    assert latest.status_code == 200
    assert latest.json()["session"]["session_id"] == "flight"
    assert velocity.status_code == 200
    assert velocity.json()["frame"] == "FLU"
    assert velocity.json()["vy_left_m_s"] == [-2.0, -0.0, 4.0]


def test_api_reports_empty_and_unsafe_requests(tmp_path):
    app = create_app(BlackboxRepository(tmp_path))

    latest, unsafe = asyncio.run(
        get_responses(app, "/api/latest", "/api/sessions/..%2Fsecret/velocity")
    )

    assert latest.status_code == 404
    assert unsafe.status_code == 404


def test_api_reports_missing_odometry(tmp_path, make_session):
    make_session("legacy", start_utc_ns=100, with_odometry=False)
    app = create_app(BlackboxRepository(tmp_path))

    [response] = asyncio.run(
        get_responses(app, "/api/sessions/legacy/velocity")
    )

    assert response.status_code == 404
    assert "unavailable" in response.json()["detail"]


def test_cli_defaults_and_overrides():
    defaults = parse_cli_args(["run"])
    custom = parse_cli_args(
        ["run", "--logs-dir", "/tmp/logs", "--host", "0.0.0.0", "--port", "9000"]
    )

    assert defaults.logs_directory == DEFAULT_LOGS_DIRECTORY
    assert defaults.host == DEFAULT_HOST
    assert defaults.port == DEFAULT_PORT
    assert str(custom.logs_directory) == "/tmp/logs"
    assert custom.host == "0.0.0.0"
    assert custom.port == 9000


def test_cli_rejects_invalid_port():
    with pytest.raises(SystemExit):
        parse_cli_args(["run", "--port", "70000"])


def test_main_passes_cli_values_to_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main_module.uvicorn,
        "run",
        lambda app, *, host, port: calls.append((app, host, port)),
    )

    main_module.main(
        ["run", "--logs-dir", "/tmp/logs", "--host", "127.0.0.2", "--port", "8123"]
    )

    assert len(calls) == 1
    assert calls[0][1:] == ("127.0.0.2", 8123)

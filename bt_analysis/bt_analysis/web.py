"""FastAPI application for the BT blackbox dashboard."""

from __future__ import annotations

from pathlib import Path
import subprocess

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from bt_analysis import __version__
from bt_analysis.analysis import analyze_session, flight_series, velocity_series
from bt_analysis.errors import (
    NoFinishedSessionError,
    SessionDataError,
    SessionNotFoundError,
)
from bt_analysis.repository import BlackboxRepository

STATIC_DIRECTORY = Path(__file__).with_name("static")
STATIC_ASSETS = {
    "app.css": ("text/css; charset=utf-8", STATIC_DIRECTORY / "app.css"),
    "app.js": ("text/javascript; charset=utf-8", STATIC_DIRECTORY / "app.js"),
}


def create_app(repository: BlackboxRepository) -> FastAPI:
    app = FastAPI(title="BT Analysis", version=__version__)
    index_html = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
    static_content = {
        name: (media_type, path.read_bytes())
        for name, (media_type, path) in STATIC_ASSETS.items()
    }

    @app.get("/", include_in_schema=False)
    async def index():
        return HTMLResponse(index_html)

    @app.get("/static/{asset_name}", include_in_schema=False)
    async def static_asset(asset_name: str):
        asset = static_content.get(asset_name)
        if asset is None:
            raise HTTPException(status_code=404, detail="Static asset not found")
        media_type, content = asset
        return Response(content, media_type=media_type)

    @app.get("/api/latest")
    async def latest():
        try:
            session = repository.latest()
            return analyze_session(repository, session)
        except NoFinishedSessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/sessions")
    async def sessions():
        return {
            "sessions": [
                {
                    "session_id": session.session_id,
                    "start_utc_ns": session.metadata.get("start_utc_ns"),
                    "end_utc_ns": session.metadata.get("end_utc_ns"),
                    "status": session.metadata.get("status"),
                    "end_reason": session.metadata.get("end_reason"),
                }
                for session in repository.sessions()
            ]
        }

    @app.get("/api/logs-directory")
    async def logs_directory():
        return {"path": str(repository.logs_directory.resolve())}

    @app.post("/api/logs-directory/browse")
    async def browse_logs_directory():
        initial = repository.logs_directory.resolve()
        if not initial.is_dir():
            initial = initial.parent
        try:
            result = subprocess.run(
                [
                    "zenity",
                    "--file-selection",
                    "--directory",
                    "--title=Select BT blackbox log folder",
                    f"--filename={initial}/",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise HTTPException(
                status_code=501,
                detail=f"Unable to open the folder browser: {exc}",
            ) from exc
        if result.returncode != 0:
            raise HTTPException(status_code=409, detail="Folder selection cancelled")

        selected = Path(result.stdout.strip()).expanduser().resolve()
        selected_session_id = None
        if selected.name.endswith("_blackbox"):
            selected_session_id = selected.name.removesuffix("_blackbox")
            candidate = selected.parent
        else:
            candidate = selected
        if not candidate.is_dir():
            raise HTTPException(status_code=422, detail="Selected folder does not exist")
        previous = repository.logs_directory
        repository.logs_directory = candidate
        if not repository.sessions():
            repository.logs_directory = previous
            raise HTTPException(
                status_code=422,
                detail="Selected folder contains no finished blackbox sessions",
            )
        return {
            "path": str(candidate),
            "selected_session_id": selected_session_id,
        }

    @app.get("/api/sessions/{session_id}")
    async def session_summary(session_id: str):
        try:
            return analyze_session(repository, repository.get(session_id))
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/velocity")
    async def velocity(session_id: str):
        try:
            session = repository.get(session_id)
            table = repository.load_odometry(session)
            if table is None or table.num_rows == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Odometry is unavailable for session {session_id}",
                )
            return {
                "session_id": session.session_id,
                "frame": "FLU",
                "units": "m/s",
                **velocity_series(table),
            }
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/flight")
    async def flight(session_id: str):
        try:
            session = repository.get(session_id)
            table = repository.load_frames(session)
            if table is None or table.num_rows == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Flight frames are unavailable for session {session_id}",
                )
            return {"session_id": session.session_id, **flight_series(table)}
        except SessionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except SessionDataError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app

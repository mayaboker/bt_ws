"""FastAPI application for the BT blackbox dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from bt_analysis import __version__
from bt_analysis.analysis import analyze_session, velocity_series
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

    return app

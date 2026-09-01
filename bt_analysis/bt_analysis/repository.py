"""Read-only discovery and loading for bt-app blackbox sessions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bt_analysis.errors import (
    NoFinishedSessionError,
    SessionDataError,
    SessionNotFoundError,
)

FINISHED_STATUSES = frozenset({"complete", "unclean"})
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class BlackboxSession:
    session_id: str
    directory: Path
    metadata: dict[str, Any]

    @property
    def start_utc_ns(self) -> int:
        return int(self.metadata["start_utc_ns"])


class BlackboxRepository:
    """Discover finished sessions and load their immutable Parquet chunks."""

    def __init__(self, logs_directory: str | Path) -> None:
        self.logs_directory = Path(logs_directory)

    def sessions(self) -> list[BlackboxSession]:
        sessions: list[BlackboxSession] = []
        if not self.logs_directory.is_dir():
            return sessions
        for metadata_path in self.logs_directory.glob("*_blackbox/metadata.json"):
            session = self._read_session_metadata(metadata_path)
            if session is not None:
                sessions.append(session)
        return sorted(
            sessions,
            key=lambda session: (session.start_utc_ns, session.session_id),
            reverse=True,
        )

    def latest(self) -> BlackboxSession:
        sessions = self.sessions()
        if not sessions:
            raise NoFinishedSessionError(
                f"No finished blackbox session found in {self.logs_directory}"
            )
        return sessions[0]

    def get(self, session_id: str) -> BlackboxSession:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionNotFoundError(f"Blackbox session not found: {session_id}")
        for session in self.sessions():
            if session.session_id == session_id:
                return session
        raise SessionNotFoundError(f"Blackbox session not found: {session_id}")

    def load_events(self, session: BlackboxSession) -> pa.Table | None:
        return self._load_stream(session, "events")

    def load_odometry(self, session: BlackboxSession) -> pa.Table | None:
        return self._load_stream(session, "odometry")

    def _read_session_metadata(self, metadata_path: Path) -> BlackboxSession | None:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            session_id = str(metadata["session_id"])
            start_utc_ns = int(metadata["start_utc_ns"])
            status = str(metadata["status"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
        if (
            status not in FINISHED_STATUSES
            or start_utc_ns < 0
            or not SESSION_ID_PATTERN.fullmatch(session_id)
            or metadata_path.parent.name != f"{session_id}_blackbox"
        ):
            return None
        return BlackboxSession(session_id, metadata_path.parent, metadata)

    def _load_stream(self, session: BlackboxSession, stream: str) -> pa.Table | None:
        names: list[str] = []
        chunks = session.metadata.get("chunks", [])
        if not isinstance(chunks, list):
            raise SessionDataError(
                f"Invalid chunk inventory for session {session.session_id}"
            )
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise SessionDataError(
                    f"Invalid chunk entry for session {session.session_id}"
                )
            name = chunk.get(stream)
            if name is not None:
                names.append(self._safe_chunk_name(session, name, stream))
        if not names:
            return None
        paths = [session.directory / name for name in names]
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            raise SessionDataError(
                f"Missing {stream} chunk(s) in {session.session_id}: "
                + ", ".join(missing)
            )
        try:
            tables = [pq.read_table(path) for path in paths]
            return pa.concat_tables(tables)
        except (OSError, ValueError, TypeError, pa.ArrowException) as exc:
            raise SessionDataError(
                f"Unable to read {stream} for {session.session_id}: {exc}"
            ) from exc

    @staticmethod
    def _safe_chunk_name(
        session: BlackboxSession,
        value: object,
        stream: str,
    ) -> str:
        name = str(value)
        path = Path(name)
        expected_prefix = f"{stream}-"
        if (
            path.name != name
            or not name.startswith(expected_prefix)
            or path.suffix != ".parquet"
        ):
            raise SessionDataError(
                f"Unsafe {stream} chunk name in {session.session_id}: {name}"
            )
        return name

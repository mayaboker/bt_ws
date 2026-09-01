"""Nonblocking, armed-flight Parquet blackbox recorder."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from loguru import logger as log
import pyarrow as pa
import pyarrow.parquet as pq

from bt_app._version import __version__
from bt_app.context import Context
from bt_app.mavlink_wrapper import OdometryVelocitySample
from bt_app.services.tracker_result_store import TrackerObservation


SCHEMA_VERSION = 2
FRAME_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("sample_index", pa.int64()),
        ("time_monotonic_ns", pa.int64()),
        ("elapsed_s", pa.float64()),
        ("state_id", pa.int16()),
        ("state_name", pa.string()),
        ("armed", pa.bool_()),
        *[(f"request_ch{index}", pa.int16()) for index in range(1, 19)],
        *[(f"output_ch{index}", pa.int16()) for index in range(1, 9)],
        ("altitude_m", pa.float64()),
        ("vario_m_s", pa.float64()),
        ("altitude_age_s", pa.float64()),
        ("altitude_fresh", pa.bool_()),
        ("roll_deg", pa.float64()),
        ("pitch_deg", pa.float64()),
        ("heading_deg", pa.float64()),
        ("attitude_age_s", pa.float64()),
        ("attitude_fresh", pa.bool_()),
        ("tracker_present", pa.bool_()),
        ("tracker_new_frame", pa.bool_()),
        ("tracker_id", pa.int64()),
        ("tracker_frame_id", pa.int64()),
        ("tracker_timestamp_ns", pa.int64()),
        ("tracker_received_monotonic_ns", pa.int64()),
        ("tracker_age_s", pa.float64()),
        ("tracker_state", pa.int16()),
        ("tracker_locked", pa.bool_()),
        ("tracker_score", pa.float64()),
        ("tracker_bbox_x", pa.int32()),
        ("tracker_bbox_y", pa.int32()),
        ("tracker_bbox_width", pa.int32()),
        ("tracker_bbox_height", pa.int32()),
        ("tracker_dx", pa.int32()),
        ("tracker_dy", pa.int32()),
    ]
)
EVENT_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("time_monotonic_ns", pa.int64()),
        ("elapsed_s", pa.float64()),
        ("previous_state_id", pa.int16()),
        ("previous_state_name", pa.string()),
        ("current_state_id", pa.int16()),
        ("current_state_name", pa.string()),
    ]
)
ODOMETRY_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("sample_index", pa.int64()),
        ("source_time_epoch_us", pa.int64()),
        ("received_monotonic_ns", pa.int64()),
        ("elapsed_s", pa.float64()),
        ("mavlink_sequence", pa.uint8()),
        ("reset_counter", pa.uint8()),
        ("velocity_body_x_m_s", pa.float64()),
        ("velocity_body_y_m_s", pa.float64()),
        ("velocity_body_z_m_s", pa.float64()),
        ("velocity_north_m_s", pa.float64()),
        ("velocity_east_m_s", pa.float64()),
        ("velocity_down_m_s", pa.float64()),
    ]
)


@dataclass(frozen=True, slots=True)
class _StartFlight:
    session_id: str
    directory: Path
    monotonic_ns: int
    utc_ns: int
    dropped_frames_start: int
    dropped_odometry_start: int
    writer_errors_start: int


@dataclass(frozen=True, slots=True)
class _EndFlight:
    session_id: str
    monotonic_ns: int
    utc_ns: int
    clean: bool


@dataclass(frozen=True, slots=True)
class _StopWriter:
    pass


@dataclass(frozen=True, slots=True)
class _FrameRecord:
    row: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _OdometryRecord:
    row: dict[str, Any]


class _TelemetryBuffer:
    """Bounded FIFO that evicts odometry before rejecting control frames."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._items: deque[Any] = deque()
        self._telemetry_count = 0
        self._condition = threading.Condition()

    def put_frame(self, item: _FrameRecord) -> tuple[bool, bool]:
        with self._condition:
            evicted_odometry = False
            if self._telemetry_count >= self.capacity:
                for index, queued in enumerate(self._items):
                    if isinstance(queued, _OdometryRecord):
                        del self._items[index]
                        self._telemetry_count -= 1
                        evicted_odometry = True
                        break
                else:
                    return False, False
            self._items.append(item)
            self._telemetry_count += 1
            self._condition.notify()
            return True, evicted_odometry

    def put_odometry(self, item: _OdometryRecord) -> bool:
        with self._condition:
            if self._telemetry_count >= self.capacity:
                return False
            self._items.append(item)
            self._telemetry_count += 1
            self._condition.notify()
            return True

    def put_control(self, item: Any) -> None:
        with self._condition:
            self._items.append(item)
            self._condition.notify()

    def get(self) -> Any:
        with self._condition:
            while not self._items:
                self._condition.wait()
            item = self._items.popleft()
            if isinstance(item, (_FrameRecord, _OdometryRecord)):
                self._telemetry_count -= 1
            return item

    def qsize(self) -> int:
        with self._condition:
            return len(self._items)


class NullBlackboxRecorder:
    def start(self) -> None:
        return

    def record(
        self,
        context: Context,
        tracker: TrackerObservation | None,
        *,
        now_s: float | None = None,
    ) -> None:
        return

    def record_odometry(self, sample: OdometryVelocitySample) -> None:
        return

    def stop(self, timeout: float | None = 2.0) -> None:
        return


class BlackboxRecorder:
    """Capture coherent control frames and persist them off the flight thread."""

    def __init__(
        self,
        directory: str | Path,
        *,
        vehicle_config: object,
        parameters: dict[str, Any] | Callable[[], dict[str, Any]],
        chunk_duration_s: float = 5.0,
        queue_size: int = 1000,
        clock: Any = time.monotonic,
        wall_clock_ns: Any = time.time_ns,
    ) -> None:
        if chunk_duration_s <= 0:
            raise ValueError("blackbox chunk duration must be positive")
        if queue_size <= 0:
            raise ValueError("blackbox queue size must be positive")
        self.directory = Path(directory)
        self.chunk_duration_s = float(chunk_duration_s)
        self._frame_capacity = queue_size
        self._queue = _TelemetryBuffer(queue_size)
        self._clock = clock
        self._wall_clock_ns = wall_clock_ns
        self._vehicle_config = _json_safe(asdict(vehicle_config))
        self._parameters = parameters
        self._thread: threading.Thread | None = None
        self._enabled = False
        self._flight_active = False
        self._session_id: str | None = None
        self._session_start_ns = 0
        self._sample_index = 0
        self._odometry_sample_index = 0
        self._last_altitude_sample_s: float | None = None
        self._last_attitude_sample_s: float | None = None
        self._last_tracker_key: tuple[int, int] | None = None
        self.dropped_frames = 0
        self.dropped_odometry = 0
        self.writer_errors = 0

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted_sessions()
        self._enabled = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="blackbox-writer",
        )
        self._thread.start()

    def record(
        self,
        context: Context,
        tracker: TrackerObservation | None,
        *,
        now_s: float | None = None,
    ) -> None:
        if not self._enabled:
            return
        try:
            now_s = self._clock() if now_s is None else float(now_s)
            now_ns = int(now_s * 1_000_000_000)
            if context.armed and not self._flight_active:
                self._begin_flight(now_ns)
            if not self._enabled:
                return
            if not context.armed:
                if self._flight_active:
                    self._end_flight(now_ns, clean=True)
                return

            frame = self._make_frame(context, tracker, now_s=now_s, now_ns=now_ns)
            self._put_frame(frame)
        except Exception as exc:
            # Recorder faults must never escape into the flight-control loop.
            self.writer_errors += 1
            self._enabled = False
            log.exception("Blackbox frame capture disabled after error: {}", exc)

    def record_odometry(self, sample: OdometryVelocitySample) -> None:
        if not self._enabled or not self._flight_active:
            return
        try:
            row = {
                "schema_version": SCHEMA_VERSION,
                "sample_index": self._odometry_sample_index,
                "source_time_epoch_us": int(sample.source_time_epoch_us),
                "received_monotonic_ns": int(sample.received_monotonic_ns),
                "elapsed_s": (
                    sample.received_monotonic_ns - self._session_start_ns
                )
                / 1e9,
                "mavlink_sequence": int(sample.mavlink_sequence),
                "reset_counter": int(sample.reset_counter),
                "velocity_body_x_m_s": float(sample.velocity_body_x_m_s),
                "velocity_body_y_m_s": float(sample.velocity_body_y_m_s),
                "velocity_body_z_m_s": float(sample.velocity_body_z_m_s),
                "velocity_north_m_s": float(sample.velocity_north_m_s),
                "velocity_east_m_s": float(sample.velocity_east_m_s),
                "velocity_down_m_s": float(sample.velocity_down_m_s),
            }
            self._odometry_sample_index += 1
            self._put_odometry(row)
        except Exception as exc:
            self.writer_errors += 1
            self._enabled = False
            log.exception("Blackbox odometry capture disabled after error: {}", exc)

    def stop(self, timeout: float | None = 2.0) -> None:
        self._enabled = False
        if self._flight_active:
            self._end_flight(int(self._clock() * 1_000_000_000), clean=False)
        self._put_control(_StopWriter())
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                log.error("Blackbox writer did not stop within {} seconds", timeout)
            self._thread = None
        if self.dropped_frames:
            log.warning("Blackbox dropped {} frame(s)", self.dropped_frames)
        if self.dropped_odometry:
            log.warning(
                "Blackbox dropped {} odometry sample(s)", self.dropped_odometry
            )

    def _begin_flight(self, now_ns: int) -> None:
        utc_ns = int(self._wall_clock_ns())
        timestamp = datetime.fromtimestamp(utc_ns / 1e9, timezone.utc).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )
        session_id = f"{timestamp}_{uuid4().hex[:8]}"
        session_dir = self.directory / f"{session_id}_blackbox"
        self._flight_active = True
        self._session_id = session_id
        self._session_start_ns = now_ns
        self._sample_index = 0
        self._odometry_sample_index = 0
        self._last_altitude_sample_s = None
        self._last_attitude_sample_s = None
        self._last_tracker_key = None
        self._put_control(
            _StartFlight(
                session_id,
                session_dir,
                now_ns,
                utc_ns,
                self.dropped_frames,
                self.dropped_odometry,
                self.writer_errors,
            )
        )

    def _end_flight(self, now_ns: int, *, clean: bool) -> None:
        session_id = self._session_id
        self._flight_active = False
        self._session_id = None
        if session_id is not None:
            self._put_control(
                _EndFlight(session_id, now_ns, int(self._wall_clock_ns()), clean)
            )

    def _make_frame(
        self,
        context: Context,
        tracker: TrackerObservation | None,
        *,
        now_s: float,
        now_ns: int,
    ) -> dict[str, Any]:
        altitude_sample_s = context.drone_alt_received_at_s or None
        attitude_sample_s = context.drone_attitude_received_at_s or None
        altitude_fresh = (
            altitude_sample_s is not None
            and altitude_sample_s != self._last_altitude_sample_s
        )
        attitude_fresh = (
            attitude_sample_s is not None
            and attitude_sample_s != self._last_attitude_sample_s
        )
        self._last_altitude_sample_s = altitude_sample_s
        self._last_attitude_sample_s = attitude_sample_s
        state_id = int(context.state)
        row: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "sample_index": self._sample_index,
            "time_monotonic_ns": now_ns,
            "elapsed_s": (now_ns - self._session_start_ns) / 1e9,
            "state_id": state_id,
            "state_name": getattr(context.state, "name", str(context.state)),
            "armed": bool(context.armed),
            "altitude_m": float(context.drone_alt),
            "vario_m_s": float(context.drone_vertical_speed),
            "altitude_age_s": _age(now_s, altitude_sample_s),
            "altitude_fresh": altitude_fresh,
            "roll_deg": float(context.drone_roll_deg),
            "pitch_deg": float(context.drone_pitch_deg),
            "heading_deg": float(context.drone_heading_deg),
            "attitude_age_s": _age(now_s, attitude_sample_s),
            "attitude_fresh": attitude_fresh,
        }
        self._sample_index += 1
        request = tuple(context.request_rc)
        output = tuple(context.sent_rc)
        row.update({f"request_ch{i}": int(value) for i, value in enumerate(request, 1)})
        row.update({f"output_ch{i}": int(value) for i, value in enumerate(output, 1)})
        row.update(self._tracker_fields(tracker, now_s))
        return row

    def _tracker_fields(
        self,
        observation: TrackerObservation | None,
        now_s: float,
    ) -> dict[str, Any]:
        if observation is None:
            return {
                "tracker_present": False,
                "tracker_new_frame": False,
                "tracker_id": None,
                "tracker_frame_id": None,
                "tracker_timestamp_ns": None,
                "tracker_received_monotonic_ns": None,
                "tracker_age_s": None,
                "tracker_state": None,
                "tracker_locked": None,
                "tracker_score": None,
                "tracker_bbox_x": None,
                "tracker_bbox_y": None,
                "tracker_bbox_width": None,
                "tracker_bbox_height": None,
                "tracker_dx": None,
                "tracker_dy": None,
            }
        result = observation.result
        key = (result.tracker_id, result.frame_id)
        is_new = key != self._last_tracker_key
        self._last_tracker_key = key
        return {
            "tracker_present": True,
            "tracker_new_frame": is_new,
            "tracker_id": result.tracker_id,
            "tracker_frame_id": result.frame_id,
            "tracker_timestamp_ns": result.timestamp_ns,
            "tracker_received_monotonic_ns": int(observation.received_at_s * 1e9),
            "tracker_age_s": max(0.0, now_s - observation.received_at_s),
            "tracker_state": result.state,
            "tracker_locked": result.locked,
            "tracker_score": result.score,
            "tracker_bbox_x": result.bbox_x,
            "tracker_bbox_y": result.bbox_y,
            "tracker_bbox_width": result.bbox_width,
            "tracker_bbox_height": result.bbox_height,
            "tracker_dx": result.dx,
            "tracker_dy": result.dy,
        }

    def _put_frame(self, frame: dict[str, Any]) -> None:
        accepted, evicted_odometry = self._queue.put_frame(_FrameRecord(frame))
        if evicted_odometry:
            self.dropped_odometry += 1
        if not accepted:
            self.dropped_frames += 1

    def _put_odometry(self, row: dict[str, Any]) -> None:
        if not self._queue.put_odometry(_OdometryRecord(row)):
            self.dropped_odometry += 1

    def _put_control(self, item: Any) -> None:
        self._queue.put_control(item)

    def _run(self) -> None:
        session: _SessionWriter | None = None
        while True:
            item = self._queue.get()
            try:
                if isinstance(item, _StopWriter):
                    if session is not None:
                        session.finish(
                            clean=False,
                            end_monotonic_ns=time.monotonic_ns(),
                            dropped_frames=self.dropped_frames,
                            dropped_odometry=self.dropped_odometry,
                            writer_errors=self.writer_errors,
                        )
                    return
                if isinstance(item, _StartFlight):
                    session = _SessionWriter(
                        item,
                        vehicle_config=self._vehicle_config,
                        parameters=_json_safe(
                            self._parameters()
                            if callable(self._parameters)
                            else self._parameters
                        ),
                        chunk_duration_s=self.chunk_duration_s,
                    )
                elif isinstance(item, _EndFlight):
                    if session is not None and session.session_id == item.session_id:
                        session.finish(
                            clean=item.clean,
                            end_monotonic_ns=item.monotonic_ns,
                            end_utc_ns=item.utc_ns,
                            dropped_frames=self.dropped_frames,
                            dropped_odometry=self.dropped_odometry,
                            writer_errors=self.writer_errors,
                        )
                        session = None
                elif session is not None and isinstance(item, _FrameRecord):
                    session.append_frame(item.row)
                elif session is not None and isinstance(item, _OdometryRecord):
                    session.append_odometry(item.row)
            except Exception as exc:
                self.writer_errors += 1
                self._enabled = False
                log.exception("Blackbox writer failed: {}", exc)
                if session is not None:
                    session.fail(
                        exc,
                        self.dropped_frames,
                        self.dropped_odometry,
                        self.writer_errors,
                    )
                    session = None

    def _recover_interrupted_sessions(self) -> None:
        for metadata_path in self.directory.glob("*_blackbox/metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("status") != "recording":
                    continue
                for temporary in metadata_path.parent.glob("*.tmp"):
                    temporary.unlink(missing_ok=True)
                metadata["status"] = "unclean"
                metadata["end_reason"] = "interrupted"
                _write_json_atomic(metadata_path, metadata)
            except (OSError, ValueError, TypeError) as exc:
                log.warning("Unable to recover blackbox session {}: {}", metadata_path, exc)


class _SessionWriter:
    def __init__(
        self,
        start: _StartFlight,
        *,
        vehicle_config: Any,
        parameters: Any,
        chunk_duration_s: float,
    ) -> None:
        self.session_id = start.session_id
        self.directory = start.directory
        self.directory.mkdir(parents=True, exist_ok=False)
        self.chunk_duration_s = chunk_duration_s
        self.start_monotonic_ns = start.monotonic_ns
        self.rows: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.odometry_rows: list[dict[str, Any]] = []
        self.chunk_index = 0
        self.frame_count = 0
        self.odometry_count = 0
        self.previous_state: tuple[int, str] | None = None
        self.dropped_frames_start = start.dropped_frames_start
        self.dropped_odometry_start = start.dropped_odometry_start
        self.writer_errors_start = start.writer_errors_start
        self.metadata = {
            "schema_version": SCHEMA_VERSION,
            "session_id": start.session_id,
            "status": "recording",
            "start_utc_ns": start.utc_ns,
            "start_monotonic_ns": start.monotonic_ns,
            "timezone": str(datetime.now().astimezone().tzinfo),
            "app_version": __version__,
            "git_revision": _git_revision(),
            "platform": platform.platform(),
            "vehicle_config": vehicle_config,
            "parameters": parameters,
            "chunks": [],
        }
        _write_json_atomic(self.directory / "metadata.json", self.metadata)

    def _rotate_if_needed(self, elapsed_s: float) -> None:
        if (
            (self.rows or self.odometry_rows)
            and elapsed_s >= (self.chunk_index + 1) * self.chunk_duration_s
        ):
            self._flush_chunk()

    def append_frame(self, row: dict[str, Any]) -> None:
        self._rotate_if_needed(row["elapsed_s"])
        state = (row["state_id"], row["state_name"])
        if state != self.previous_state:
            previous = self.previous_state
            self.events.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "time_monotonic_ns": row["time_monotonic_ns"],
                    "elapsed_s": row["elapsed_s"],
                    "previous_state_id": None if previous is None else previous[0],
                    "previous_state_name": None if previous is None else previous[1],
                    "current_state_id": state[0],
                    "current_state_name": state[1],
                }
            )
            self.previous_state = state
        self.rows.append(row)
        self.frame_count += 1

    def append_odometry(self, row: dict[str, Any]) -> None:
        self._rotate_if_needed(row["elapsed_s"])
        self.odometry_rows.append(row)
        self.odometry_count += 1

    def _flush_chunk(self) -> None:
        if not self.rows and not self.odometry_rows:
            return
        part = self.chunk_index
        frame_name = None
        if self.rows:
            frame_name = f"frames-{part:06d}.parquet"
            _write_parquet_atomic(
                self.directory / frame_name,
                pa.Table.from_pylist(self.rows, schema=FRAME_SCHEMA),
            )
        event_name = None
        if self.events:
            event_name = f"events-{part:06d}.parquet"
            _write_parquet_atomic(
                self.directory / event_name,
                pa.Table.from_pylist(self.events, schema=EVENT_SCHEMA),
            )
        odometry_name = None
        if self.odometry_rows:
            odometry_name = f"odometry-{part:06d}.parquet"
            _write_parquet_atomic(
                self.directory / odometry_name,
                pa.Table.from_pylist(self.odometry_rows, schema=ODOMETRY_SCHEMA),
            )
        self.metadata["chunks"].append(
            {
                "index": part,
                "frames": frame_name,
                "events": event_name,
                "odometry": odometry_name,
            }
        )
        self.rows.clear()
        self.events.clear()
        self.odometry_rows.clear()
        self.chunk_index += 1
        _write_json_atomic(self.directory / "metadata.json", self.metadata)

    def finish(
        self,
        *,
        clean: bool,
        end_monotonic_ns: int,
        end_utc_ns: int | None = None,
        dropped_frames: int = 0,
        dropped_odometry: int = 0,
        writer_errors: int = 0,
    ) -> None:
        self._flush_chunk()
        self.metadata.update(
            {
                "status": "complete" if clean else "unclean",
                "end_reason": "disarmed" if clean else "application_stopped",
                "end_monotonic_ns": end_monotonic_ns,
                "end_utc_ns": end_utc_ns,
                "frame_count": self.frame_count,
                "odometry_count": self.odometry_count,
                "dropped_frames": max(
                    0, dropped_frames - self.dropped_frames_start
                ),
                "dropped_odometry": max(
                    0, dropped_odometry - self.dropped_odometry_start
                ),
                "writer_errors": max(0, writer_errors - self.writer_errors_start),
            }
        )
        _write_json_atomic(self.directory / "metadata.json", self.metadata)

    def fail(
        self,
        exc: Exception,
        dropped_frames: int,
        dropped_odometry: int,
        writer_errors: int,
    ) -> None:
        self.metadata.update(
            {
                "status": "unclean",
                "end_reason": "writer_error",
                "error": str(exc),
                "frame_count": self.frame_count,
                "odometry_count": self.odometry_count,
                "dropped_frames": max(
                    0, dropped_frames - self.dropped_frames_start
                ),
                "dropped_odometry": max(
                    0, dropped_odometry - self.dropped_odometry_start
                ),
                "writer_errors": max(0, writer_errors - self.writer_errors_start),
            }
        )
        try:
            _write_json_atomic(self.directory / "metadata.json", self.metadata)
        except OSError:
            pass


def _age(now_s: float, sample_s: float | None) -> float | None:
    return None if sample_s is None else max(0.0, now_s - sample_s)


def _write_parquet_atomic(path: Path, table: pa.Table) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, path)


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=0.5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return getattr(value, "value", str(value))

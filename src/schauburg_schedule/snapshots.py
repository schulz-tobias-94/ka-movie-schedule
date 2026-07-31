from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from urllib.parse import urlparse

from .models import CinemaResult, Screening

SNAPSHOT_SCHEMA_VERSION = 3
APPLICATION_VERSION = "0.1.0"
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


class SnapshotError(ValueError):
    pass


def serialize_snapshot(result: CinemaResult, *, start_date: date | None = None, end_date: date | None = None) -> str:
    data = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "application_version": APPLICATION_VERSION,
        "cinema": {"id": result.cinema_id, "name": result.cinema_name},
        "retrieved_at": result.retrieved_at.isoformat(),
        "requested_date_range": {"start": start_date.isoformat() if start_date else None, "end": end_date.isoformat() if end_date else None},
        "success": result.success,
        "error": result.error,
        "fresh": result.fresh,
        "screenings": [
            {
                "cinema_id": item.cinema_id, "cinema_name": item.cinema_name,
                "date": item.date.isoformat(), "time": item.time.isoformat(),
                "movie_title": item.movie_title, "format_label": item.format_label,
                "original_language": item.original_language, "subtitle_language": item.subtitle_language,
                "auditorium": item.auditorium, "movie_url": item.movie_url, "booking_url": item.booking_url,
                "dimension": item.dimension, "technology": item.technology, "screening_url": item.screening_url,
            }
            for item in sorted(result.screenings, key=lambda item: (item.date, item.time, item.movie_title.casefold()))
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def deserialize_snapshot(text: str) -> CinemaResult:
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("schema_version") not in (1, 2, SNAPSHOT_SCHEMA_VERSION):
            raise SnapshotError("Unsupported snapshot schema.")
        cinema = data["cinema"]
        if not isinstance(cinema, dict) or not all(isinstance(cinema.get(key), str) and cinema[key] for key in ("id", "name")):
            raise SnapshotError("Snapshot cinema identity is invalid.")
        if not isinstance(data["success"], bool) or not isinstance(data["fresh"], bool):
            raise SnapshotError("Snapshot status is invalid.")
        if data.get("error") is not None and not isinstance(data["error"], str):
            raise SnapshotError("Snapshot error is invalid.")
        retrieved_at = datetime.fromisoformat(data["retrieved_at"])
        if data.get("schema_version") == SNAPSHOT_SCHEMA_VERSION:
            request_range = data.get("requested_date_range")
            if not isinstance(data.get("application_version"), str) or not isinstance(request_range, dict) or set(request_range) != {"start", "end"}:
                raise SnapshotError("Snapshot date range is invalid.")
            for value in request_range.values():
                if value is not None:
                    date.fromisoformat(value)
        if not isinstance(data["screenings"], list):
            raise SnapshotError("Snapshot screenings are invalid.")
        screenings = tuple(_screening_from_data(item) for item in data["screenings"])
        if any(item.cinema_id != cinema["id"] or item.cinema_name != cinema["name"] for item in screenings):
            raise SnapshotError("Snapshot screening cinema identity is invalid.")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, SnapshotError):
            raise
        raise SnapshotError(f"Malformed snapshot: {exc}") from exc
    return CinemaResult(cinema["id"], cinema["name"], screenings, retrieved_at, data["success"], data.get("error"), data["fresh"])


def _screening_from_data(data: object) -> Screening:
    if not isinstance(data, dict):
        raise SnapshotError("Snapshot screening is invalid.")
    required = ("cinema_id", "cinema_name", "movie_title")
    if not all(isinstance(data.get(key), str) and data[key] for key in required):
        raise SnapshotError("Snapshot screening fields are invalid.")
    optional = ("format_label", "original_language", "subtitle_language", "auditorium", "movie_url", "booking_url", "dimension", "technology", "screening_url")
    if any(data.get(key) is not None and not isinstance(data.get(key), str) for key in optional):
        raise SnapshotError("Snapshot optional screening fields are invalid.")
    for key in ("movie_url", "booking_url", "screening_url"):
        if (value := data.get(key)) is not None and urlparse(value).scheme not in {"http", "https"}:
            raise SnapshotError("Snapshot URL is invalid.")
    try:
        return Screening(data["cinema_id"], data["cinema_name"], date.fromisoformat(data["date"]), time.fromisoformat(data["time"]), data["movie_title"], *(data.get(key) for key in optional))
    except (KeyError, TypeError, ValueError) as exc:
        raise SnapshotError(f"Malformed snapshot screening: {exc}") from exc


def snapshot_path(directory: Path, cinema_id: str) -> Path:
    return directory / f"{cinema_id}.json"


def write_snapshot(result: CinemaResult, directory: Path, *, start_date: date, end_date: date) -> None:
    """Atomically persist only a fresh, successful source result."""
    if not result.success or not result.fresh:
        return
    directory.mkdir(parents=True, exist_ok=True)
    target = snapshot_path(directory, result.cinema_id)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, prefix=f".{result.cinema_id}.", suffix=".tmp", delete=False) as handle:
            temporary_name = handle.name
            handle.write(serialize_snapshot(result, start_date=start_date, end_date=end_date))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def load_snapshot(directory: Path, *, cinema_id: str, cinema_name: str, today: date, end_date: date) -> CinemaResult:
    target = snapshot_path(directory, cinema_id)
    try:
        if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("Snapshot file is not usable.")
        snapshot = deserialize_snapshot(target.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SnapshotError(f"Could not read snapshot: {exc}") from exc
    if snapshot.cinema_id != cinema_id or snapshot.cinema_name != cinema_name:
        raise SnapshotError("Snapshot cinema identity does not match.")
    if not snapshot.success or not snapshot.fresh:
        raise SnapshotError("Snapshot does not represent a successful retrieval.")
    screenings = tuple(item for item in snapshot.screenings if today <= item.date <= end_date)
    if not screenings:
        raise SnapshotError("Snapshot has no usable future screenings.")
    return CinemaResult(cinema_id, cinema_name, screenings, snapshot.retrieved_at, True, None, False)

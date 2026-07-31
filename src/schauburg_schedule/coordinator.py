from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import CinemaResult, Screening
from .sources.base import CinemaSource, SourceError
from .snapshots import SnapshotError, load_snapshot, write_snapshot


def collect_screenings(
    sources: Iterable[CinemaSource], *, days: int, today: date, use_cache: bool
) -> list[CinemaResult]:
    """Run every source, retaining expected failures beside successful results."""
    results = []
    for source in sources:
        retrieved_at = datetime.now(ZoneInfo("Europe/Berlin"))
        try:
            screenings = source.fetch(days=days, today=today, use_cache=use_cache)
        except SourceError as exc:
            results.append(CinemaResult(source.cinema_id, source.cinema_name, (), retrieved_at, False, str(exc), False))
        else:
            results.append(CinemaResult(
                source.cinema_id,
                source.cinema_name,
                tuple(sorted(screenings, key=screening_sort_key)),
                retrieved_at,
                True,
            ))
    return results


def screening_sort_key(item: Screening) -> tuple[date, object, str, str, str]:
    return (item.date, item.time, item.movie_title.casefold(), (item.format_label or "").casefold(), item.cinema_id)


def successful_screenings(results: Iterable[CinemaResult]) -> list[Screening]:
    return sorted((item for result in results if result.success for item in result.screenings), key=screening_sort_key)


def persist_and_restore_snapshots(
    results: Iterable[CinemaResult], *, directory: Path, today: date, end_date: date, fallback: bool
) -> list[CinemaResult]:
    """Persist fresh results and replace only failed sources with usable snapshots."""
    logger, resolved = logging.getLogger(__name__), []
    for result in results:
        if result.success:
            try:
                write_snapshot(result, directory, start_date=today, end_date=end_date)
            except OSError as exc:
                logger.warning("Could not save %s snapshot: %s", result.cinema_id, exc)
            resolved.append(result)
            continue
        if fallback:
            try:
                snapshot = load_snapshot(directory, cinema_id=result.cinema_id, cinema_name=result.cinema_name, today=today, end_date=end_date)
            except SnapshotError as exc:
                logger.debug("No usable %s snapshot: %s", result.cinema_id, exc)
            else:
                resolved.append(CinemaResult(snapshot.cinema_id, snapshot.cinema_name, snapshot.screenings, snapshot.retrieved_at, True, result.error, False))
                continue
        resolved.append(result)
    return resolved

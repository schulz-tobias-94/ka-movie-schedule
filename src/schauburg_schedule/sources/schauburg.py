from __future__ import annotations

import logging
import re
import time
from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from platformdirs import user_cache_dir

from ..models import Screening
from .base import CinemaSource, SourceError

SCHEDULE_URL = "https://www.schauburg.de/spielplan"
BASE_URL = "https://www.schauburg.de"
USER_AGENT = "schauburg-schedule/0.1 (https://www.schauburg.de/spielplan)"
CACHE_TTL_SECONDS = 15 * 60
MAX_LOAD_REQUESTS = 20
# Add exact labels here when Schauburg introduces another original-language format.
VERSION_LABELS = frozenset({"OV", "OmU", "OmeU", "OmdU"})
MONTHS = {"jan": 1, "feb": 2, "mär": 3, "apr": 4, "mai": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12}


class ScheduleParseError(SourceError):
    pass


class FetchError(SourceError):
    pass


def normalize(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def version_label(value: str) -> str | None:
    match = re.fullmatch(r"([A-Za-z]+)(?:\s*\|)?", normalize(value))
    if match is None:
        return None
    value = match.group(1)
    return value if any(value.casefold() == label.casefold() for label in VERSION_LABELS) else None


def _reference_date(soup: BeautifulSoup) -> date:
    selected = soup.select_one("input.selectedDate[value]")
    if selected is None:
        raise ScheduleParseError("Schedule reference date was not found.")
    match = re.search(r"\d{4}-\d{2}-\d{2}", selected["value"])
    if not match:
        raise ScheduleParseError("Schedule reference date is malformed.")
    return date.fromisoformat(match.group())


def _parse_date(element: Tag, reference: date) -> date:
    parts = normalize(element.get_text(" ", strip=True)).split()
    if len(parts) < 3 or not parts[1].isdigit() or parts[2][:3].casefold() not in MONTHS:
        raise ValueError(f"malformed date label: {parts!r}")
    result = date(reference.year, MONTHS[parts[2][:3].casefold()], int(parts[1]))
    return result.replace(year=result.year + 1) if result < reference else result


def _parse_time(value: str):
    match = re.fullmatch(r"(\d{1,2})[.:](\d{2})", normalize(value))
    if not match:
        raise ValueError(f"malformed time: {value!r}")
    from datetime import time as clock_time
    return clock_time(int(match.group(1)), int(match.group(2)))


def _runtime_minutes(entry: Tag) -> int | None:
    value = entry.get_text(" ", strip=True)
    hour = re.search(r"\b(\d{1,2})\s*Std(?:\.?|unden)?(?:\s+(\d{1,2})\s*Min(?:uten)?)?\b", value, re.I)
    minutes = int(hour.group(1)) * 60 + int(hour.group(2) or 0) if hour else None
    match = re.search(r"\b(\d{1,3})\s*(?:MIN|Minuten)\b", value, re.I)
    minutes = minutes if minutes is not None else int(match.group(1)) if match else None
    return minutes if minutes is not None and 1 <= minutes <= 600 else None


def schedule_dates(html: str, *, reference: date | None = None) -> list[date]:
    soup = BeautifulSoup(html, "html.parser")
    reference = reference or _reference_date(soup)
    result = []
    for heading in soup.select(".schauburg-previewelement-date.d-lg-flex"):
        try:
            result.append(_parse_date(heading, reference))
        except ValueError as exc:
            logging.getLogger(__name__).debug("Skipping date section: %s", exc)
    return result


def parse_schedule(html: str) -> list[Screening]:
    soup = BeautifulSoup(html, "html.parser")
    reference = _reference_date(soup)
    headings = soup.select(".schauburg-previewelement-date.d-lg-flex")
    if not headings:
        raise ScheduleParseError("No schedule date sections found; the website may have changed.")
    logger = logging.getLogger(__name__)
    seen: set[Screening] = set()
    found_entries = 0
    for heading in headings:
        date_column = heading.find_parent("div", class_="col-lg-2") or heading.parent
        entries = date_column.find_next_sibling("div", class_="collapse") if date_column else None
        entries = entries or date_column
        if entries is None:
            logger.debug("Skipping date section without screening container")
            continue
        try:
            screening_date = _parse_date(heading, reference)
        except ValueError as exc:
            logger.debug("Skipping date section: %s", exc)
            continue
        for entry in entries.select(".row.schauburg-previewelement"):
            found_entries += 1
            title_link = entry.select_one("a.schauburg-previewelement-title-link")
            title_node = entry.select_one(".schauburg-previewelement-title")
            category = entry.select_one(".schauburg-previewelement-category span")
            time_node = entry.select_one(".d-none.d-lg-flex.schauburg-previewelement-time")
            if not all((title_link, title_node, category, time_node)):
                logger.debug("Skipping malformed screening entry")
                continue
            label = version_label(category.get_text(" ", strip=True))
            if label is None:
                continue
            try:
                href = title_link.get("href")
                screening = Screening(
                    "schauburg", "Schauburg Karlsruhe", screening_date,
                    _parse_time(time_node.get_text(" ", strip=True)),
                    normalize(title_node.get_text(" ", strip=True)), label,
                    movie_url=urljoin(BASE_URL, href) if href else None,
                    runtime_minutes=_runtime_minutes(entry),
                )
            except ValueError as exc:
                logger.debug("Skipping malformed screening entry: %s", exc)
                continue
            if not screening.movie_title:
                logger.debug("Skipping screening with an empty title")
                continue
            seen.add(screening)
    if not found_entries:
        raise ScheduleParseError("No screening entries found; the website may have changed.")
    return sorted(seen, key=lambda item: (item.date, item.time, item.movie_title.casefold(), (item.format_label or "").casefold()))


def _cache_path(days: int) -> Path:
    return Path(user_cache_dir("schauburg-schedule")) / f"schedule-{days}.html"


def _read_cache(path: Path) -> str | None:
    try:
        if time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return None


def _write_cache(path: Path, html: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except OSError as exc:
        logging.getLogger(__name__).debug("Could not write cache: %s", exc)


def _load_more_url(html: str, base_url: str) -> str | None:
    link = BeautifulSoup(html, "html.parser").select_one("a.load-more[data-ajax-url]")
    return urljoin(base_url, link["data-ajax-url"]) if link else None


def _entry_keys(html: str) -> set[str]:
    return {str(entry) for entry in BeautifulSoup(html, "html.parser").select(".row.schauburg-previewelement")}


def fetch_schedule_html(*, days: int = 8, use_cache: bool = True, timeout: float = 20, today: date | None = None) -> str:
    if days < 1:
        raise FetchError("days must be at least 1")
    cache = _cache_path(days)
    if use_cache and (cached := _read_cache(cache)) is not None:
        logging.getLogger(__name__).debug("Using cached schedule from %s", cache)
        return cached
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        initial = session.get(SCHEDULE_URL, timeout=timeout)
        initial.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(f"Could not retrieve {SCHEDULE_URL}: {exc}") from exc
    soup = BeautifulSoup(initial.text, "html.parser")
    form = soup.select_one('form[action="/spielplan/filter"]')
    if form is None:
        raise FetchError("Schedule filter form was not found; the website may have changed.")
    all_button = next((button for button in form.find_all("button") if button.get_text(" ", strip=True) == "Alles ab heute"), None)
    if all_button is None or not all_button.get("name") or not all_button.get("value"):
        raise FetchError("The complete-schedule filter was not found; the website may have changed.")
    data = {field["name"]: field.get("value", "") for field in form.select('input[type="hidden"][name]')}
    data[all_button["name"]] = all_button["value"]
    try:
        response = session.post(urljoin(SCHEDULE_URL, form["action"]), data=data, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FetchError(f"Could not retrieve the complete schedule: {exc}") from exc
    if "schauburg-previewelement" not in response.text:
        raise FetchError("Complete schedule response has no screening entries; the website may have changed.")
    logger = logging.getLogger(__name__)
    reference = today or date.today()
    end_date = reference + timedelta(days=days - 1)
    pages, known_entries = [response.text], _entry_keys(response.text)
    seen_urls, seen_bodies = set(), {sha256(response.content).hexdigest()}
    page_dates, next_url = schedule_dates(response.text), _load_more_url(response.text, response.url)
    for request_number in range(1, MAX_LOAD_REQUESTS + 1):
        if page_dates and max(page_dates) > end_date:
            break
        if not next_url:
            logger.debug("No more schedule batches after %d additional requests", request_number - 1)
            break
        if next_url in seen_urls:
            logger.debug("Stopping at repeated load-more URL: %s", next_url)
            break
        seen_urls.add(next_url)
        logger.debug("Loading more schedule (%d/%d): %s", request_number, MAX_LOAD_REQUESTS, next_url)
        try:
            more = session.get(next_url, timeout=timeout)
            more.raise_for_status()
        except requests.RequestException as exc:
            raise FetchError(f"Could not retrieve additional schedule: {exc}") from exc
        body_hash = sha256(more.content).hexdigest()
        if body_hash in seen_bodies:
            logger.debug("Stopping at repeated load-more response")
            break
        seen_bodies.add(body_hash)
        entries = _entry_keys(more.text)
        if not entries or not entries - known_entries:
            logger.debug("Stopping after additional batch with no new screenings")
            break
        known_entries.update(entries)
        batch_dates = schedule_dates(more.text, reference=reference)
        logger.debug("Additional batch dates: %s", ", ".join(item.isoformat() for item in batch_dates) or "none")
        pages.append(more.text)
        page_dates.extend(batch_dates)
        next_url = _load_more_url(more.text, more.url)
    else:
        logger.debug("Stopping after pagination safety limit (%d requests)", MAX_LOAD_REQUESTS)
    html = "\n".join(pages)
    if use_cache:
        _write_cache(cache, html)
    return html


class SchauburgSource(CinemaSource):
    cinema_id = "schauburg"
    cinema_name = "Schauburg Karlsruhe"

    @staticmethod
    def _directors(screenings: list[Screening]) -> dict[str, tuple[str, ...]]:
        """The labelled detail field is optional matching evidence, never source data."""
        urls = sorted({item.movie_url for item in screenings if item.movie_url})
        session, directors = requests.Session(), {}
        session.headers["User-Agent"] = USER_AGENT
        for url in urls:
            try:
                response = session.get(url, timeout=20)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                topic = next((node for node in soup.select(".schauburg-filmdetail-poster-topic") if normalize(node.get_text(" ", strip=True)).casefold() == "regie"), None)
                value = topic.find_next_sibling(class_="schauburg-filmdetail-poster-topic-text") if topic else None
                if value:
                    names = tuple(dict.fromkeys(part.strip() for part in value.get_text(" ", strip=True).replace("\xa0", " ").split(",") if part.strip()))
                    if names:
                        directors[url] = names
            except requests.RequestException as exc:
                logging.getLogger(__name__).debug("Could not load Schauburg movie metadata for %s: %s", url, exc)
        return directors

    def fetch(self, *, days: int, today: date, use_cache: bool) -> list[Screening]:
        screenings = parse_schedule(fetch_schedule_html(days=days, use_cache=use_cache, today=today))
        directors = self._directors(screenings)
        logging.getLogger(__name__).debug("Schauburg movie metadata requests: %d", len({item.movie_url for item in screenings if item.movie_url}))
        return [replace(item, director_names=directors.get(item.movie_url, ())) for item in screenings]

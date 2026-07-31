from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from platformdirs import user_cache_dir

from .parser import schedule_dates

SCHEDULE_URL = "https://www.schauburg.de/spielplan"
USER_AGENT = "schauburg-schedule/0.1 (https://www.schauburg.de/spielplan)"
CACHE_TTL_SECONDS = 15 * 60
MAX_LOAD_REQUESTS = 20


class FetchError(RuntimeError):
    pass


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
    soup = BeautifulSoup(html, "html.parser")
    return {str(entry) for entry in soup.select(".row.schauburg-previewelement")}


def fetch_schedule_html(*, days: int = 8, use_cache: bool = True, timeout: float = 20, today: date | None = None) -> str:
    """Return schedule HTML through ``days`` calendar days, following load-more links."""
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
    all_button = next(
        (button for button in form.find_all("button") if button.get_text(" ", strip=True) == "Alles ab heute"),
        None,
    )
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
    reference = (today or date.today())
    end_date = reference + timedelta(days=days - 1)
    pages = [response.text]
    known_entries = _entry_keys(response.text)
    seen_urls: set[str] = set()
    seen_bodies = {sha256(response.content).hexdigest()}
    page_dates = schedule_dates(response.text)
    next_url = _load_more_url(response.text, response.url)

    for request_number in range(1, MAX_LOAD_REQUESTS + 1):
        # A later date proves that the complete final requested day was loaded.
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

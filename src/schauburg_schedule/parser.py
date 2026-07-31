from __future__ import annotations

import logging
import re
from datetime import date, time
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import Screening

# Add exact labels here when Schauburg introduces another original-language format.
VERSION_LABELS = frozenset({"OV", "OmU", "OmeU", "OmdU"})
MONTHS = {"jan": 1, "feb": 2, "mär": 3, "apr": 4, "mai": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12}
BASE_URL = "https://www.schauburg.de"


class ScheduleParseError(RuntimeError):
    pass


def normalize(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def version_label(value: str) -> str | None:
    """Return a configured, exact version marker while preserving its spelling."""
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
    month = MONTHS[parts[2][:3].casefold()]
    result = date(reference.year, month, int(parts[1]))
    return result.replace(year=result.year + 1) if result < reference else result


def _parse_time(value: str) -> time:
    match = re.fullmatch(r"(\d{1,2})[.:](\d{2})", normalize(value))
    if not match:
        raise ValueError(f"malformed time: {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def schedule_dates(html: str, *, reference: date | None = None) -> list[date]:
    """Return the date headings in a schedule page or load-more fragment."""
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
        entries_container = date_column.find_next_sibling("div", class_="collapse") if date_column else None
        entries_container = entries_container or date_column
        if entries_container is None:
            logger.debug("Skipping date section without screening container")
            continue
        try:
            screening_date = _parse_date(heading, reference)
        except ValueError as exc:
            logger.debug("Skipping date section: %s", exc)
            continue
        for entry in entries_container.select(".row.schauburg-previewelement"):
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
                    date=screening_date,
                    time=_parse_time(time_node.get_text(" ", strip=True)),
                    title=normalize(title_node.get_text(" ", strip=True)),
                    version_label=label,
                    movie_url=urljoin(BASE_URL, href) if href else None,
                )
            except ValueError as exc:
                logger.debug("Skipping malformed screening entry: %s", exc)
                continue
            if not screening.title:
                logger.debug("Skipping screening with an empty title")
                continue
            seen.add(screening)
    if not found_entries:
        raise ScheduleParseError("No screening entries found; the website may have changed.")
    return sorted(seen, key=lambda item: (item.date, item.time, item.title.casefold(), item.version_label.casefold()))

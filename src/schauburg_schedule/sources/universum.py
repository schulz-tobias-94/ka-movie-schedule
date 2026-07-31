from __future__ import annotations

import logging
import json
import re
import time
from datetime import date, datetime, time as clock_time, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag
from platformdirs import user_cache_dir

from ..models import Screening
from .base import CinemaSource, SourceError

SCHEDULE_URL = "https://www.universum-city.de/de/programm"
BASE_URL = "https://www.universum-city.de"
USER_AGENT = "schauburg-schedule/0.1 (https://github.com/schauburg-schedule)"
CACHE_TTL_SECONDS = 15 * 60
LANGUAGE_CODES = {"DE": "German", "DEU": "German", "EN": "English", "ENG": "English", "ES": "Spanish", "SPA": "Spanish", "FR": "French", "FRA": "French", "IT": "Italian", "ITA": "Italian", "JA": "Japanese", "JPN": "Japanese", "KO": "Korean", "KOR": "Korean", "TR": "Turkish", "TUR": "Turkish", "UK": "Ukrainian", "UKR": "Ukrainian", "RU": "Russian", "RUS": "Russian", "PL": "Polish", "POL": "Polish", "AR": "Arabic", "ARA": "Arabic", "FA": "Persian", "FAS": "Persian", "HI": "Hindi", "HIN": "Hindi", "TA": "Tamil", "TAM": "Tamil", "ZH": "Chinese", "ZHO": "Chinese", "CANTONESE": "Cantonese", "YUE": "Cantonese"}
FORMAT_RE = re.compile(r"\b(OV|OmU|OmeU|OmdU)\b", re.I)
BERLIN = ZoneInfo("Europe/Berlin")


class UniversumError(SourceError):
    pass


def _cache_path() -> Path:
    return Path(user_cache_dir("schauburg-schedule")) / "universum-program.html"


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    url = urljoin(BASE_URL, value)
    return url if urlparse(url).scheme in {"http", "https"} else None


def fetch_program_html(*, use_cache: bool = True, timeout: float = 20) -> str:
    path = _cache_path()
    try:
        if use_cache and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    try:
        response = requests.get(SCHEDULE_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UniversumError(f"Could not retrieve {SCHEDULE_URL}: {exc}") from exc
    if "Tickets" not in response.text or "Programm" not in response.text:
        raise UniversumError("Universum response has no program entries; the website may have changed.")
    if use_cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(response.text, encoding="utf-8")
        except OSError as exc:
            logging.getLogger(__name__).debug("Could not write Universum cache: %s", exc)
    return response.text


def _date(value: str, today: date) -> date:
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.", value)
    if not match:
        raise ValueError("missing German date")
    result = date(today.year, int(match.group(2)), int(match.group(1)))
    return result.replace(year=result.year + 1) if result.month < today.month else result


def _format(value: str) -> str | None:
    match = FORMAT_RE.search(value)
    return match.group(1).replace("OM", "Om") if match else None


def _title(value: str) -> tuple[str, str | None]:
    match = re.match(r"\s*\((?:(?:2D|3D)\s*)?(?:[a-z]{2,12}\.?\s*)?(OV|OmU|OmeU|OmdU)\)\s*", value, re.I)
    title = value[match.end():] if match else value
    return re.sub(r"\s*\(auch in D-BOX\)\s*$", "", title, flags=re.I).strip(), _format(match.group(0)) if match else None


def _movie_urls(soup: BeautifulSoup) -> dict[str, str]:
    urls = {}
    for link in soup.find_all("a", href=True, attrs={"aria-label": True}):
        if re.fullmatch(r"/de/programm/\d+", link["href"]):
            urls.setdefault(_title(link["aria-label"])[0], _safe_url(link["href"]) or "")
    return urls


def _embedded_value(payload: str, key: str) -> object | None:
    marker = f'"{key}":'
    position = payload.find(marker)
    if position < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(payload, position + len(marker))[0]
    except json.JSONDecodeError:
        return None


def _embedded_program(soup: BeautifulSoup) -> tuple[list[dict], dict[int, str]] | None:
    showings: list[dict] | None = None
    rooms: dict[int, str] = {}
    for script in soup.find_all("script"):
        text = script.string or ""
        if not text.startswith("self.__next_f.push("):
            continue
        try:
            payload = json.loads(text.removeprefix("self.__next_f.push(").removesuffix(")"))[1]
        except (IndexError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, str):
            continue
        value = _embedded_value(payload, "initialShowings")
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            showings = value
        value = _embedded_value(payload, "cinemaRooms")
        if isinstance(value, list):
            rooms.update({item["id"]: item["name"] for item in value if isinstance(item, dict) and isinstance(item.get("id"), int) and isinstance(item.get("name"), str)})
    return (showings, rooms) if showings is not None else None


def _screening_urls(soup: BeautifulSoup) -> dict[int, str]:
    urls: dict[int, str] = {}
    for link in soup.find_all("a", href=True):
        match = re.fullmatch(r"/de/programm/\d+/(\d+)", link["href"])
        if match:
            urls[int(match.group(1))] = _safe_url(link["href"]) or ""
    return urls


def _parse_embedded_program(soup: BeautifulSoup, *, today: date, days: int) -> tuple[list[Screening], int] | None:
    data = _embedded_program(soup)
    if data is None:
        return None
    showings, rooms = data
    if not showings:
        return [], 0
    movie_urls, screening_urls = _movie_urls(soup), _screening_urls(soup)
    end_date, seen, parsed = today + timedelta(days=days - 1), set(), 0
    logger = logging.getLogger(__name__)
    for raw in showings:
        name, starts = raw.get("name"), raw.get("startDatetime")
        if not isinstance(name, str) or not isinstance(starts, str):
            logger.debug("Skipping malformed Universum showing: %r", raw.get("id"))
            continue
        try:
            local_start = datetime.fromisoformat(starts.replace("Z", "+00:00")).astimezone(BERLIN)
        except ValueError:
            logger.debug("Skipping Universum showing with malformed start time: %r", raw.get("id"))
            continue
        parsed += 1
        title, prefix_format = _title(name)
        original = LANGUAGE_CODES.get(str(raw.get("language") or "").upper())
        subtitle = LANGUAGE_CODES.get(str(raw.get("subtitledLanguage") or "").upper())
        format_label = _format(name) or ("OmU" if raw.get("isOriginalLanguage") and raw.get("isSubtitled") else "OV" if raw.get("isOriginalLanguage") else prefix_format)
        has_audio = original is not None
        relevant = bool(raw.get("isOriginalLanguage")) or (original is not None and original != "German") or (not has_audio and bool(format_label))
        if has_audio and original == "German" and prefix_format:
            logger.debug("Universum title prefix conflicts with explicit German audio for %s", title)
        if not relevant:
            logger.debug("Excluding German-only Universum screening: %s", title)
            continue
        if not today <= local_start.date() <= end_date:
            continue
        technology = "D-BOX" if raw.get("isDbox") else "Dolby Atmos" if raw.get("isDolbyAtmos") else None
        dimension = "3D" if raw.get("isThreeDimensional") else "2D"
        showing_id = raw.get("id")
        seen.add(Screening("universum", "Universum City Kinos Karlsruhe", local_start.date(), local_start.time().replace(tzinfo=None), title,
                           format_label, original, subtitle, rooms.get(raw.get("cinemaRoomId")), movie_urls.get(title),
                           _safe_url(raw.get("onlineTicketUrl") or raw.get("bookingUrlExternal")), dimension, technology,
                           screening_urls.get(showing_id) if isinstance(showing_id, int) else None))
    if parsed == 0:
        raise UniversumError("Universum program contains no usable screening entries; the website may have changed.")
    return sorted(seen, key=lambda item: (item.date, item.time, item.movie_title.casefold(), item.auditorium or "")), parsed


def _parse_html_program(soup: BeautifulSoup, *, today: date, days: int) -> tuple[list[Screening], int]:
    tickets = soup.find_all("a", href=True, attrs={"aria-label": "Tickets"})
    if not tickets:
        if "keine" in soup.get_text(" ", strip=True).casefold() and "vorstellung" in soup.get_text(" ", strip=True).casefold():
            return [], 0
        raise UniversumError("Universum program entries were not found; the website may have changed.")
    movie_urls, end_date, seen = _movie_urls(soup), today + timedelta(days=days - 1), set()
    parsed = 0
    logger = logging.getLogger(__name__)
    for ticket in tickets:
        card = ticket.find_parent("div", class_=lambda classes: classes and "grid" in classes and "grid-cols-[80px_minmax(0,1fr)_auto]" in classes)
        if not isinstance(card, Tag):
            logger.debug("Skipping Universum ticket without screening card")
            continue
        date_block = card.find("div", class_=lambda classes: classes and "col-start-1" in classes)
        info_block = card.find("div", class_=lambda classes: classes and "col-start-2" in classes)
        if not date_block or not info_block:
            continue
        date_text = date_block.get_text(" ", strip=True)
        time_match = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", date_text)
        spans = [item.get_text(" ", strip=True) for item in info_block.find_all("span", recursive=False)]
        if not time_match or not spans:
            logger.debug("Skipping malformed Universum screening")
            continue
        try:
            screening_date = _date(date_text, today)
            clock = clock_time.fromisoformat(time_match.group(0))
        except ValueError:
            continue
        parsed += 1
        title, prefix_format = _title(spans[0])
        metadata_parts = [item.get_text(" ", strip=True) for item in info_block.find_all("span")]
        metadata = " ".join(metadata_parts)
        format_label = _format(metadata) or prefix_format
        audio_match, subtitle_match = re.search(r"🔊\s*([A-Z]{2}|Cantonese)", metadata), re.search(r"💬\s*([A-Z]{2})", metadata)
        original = LANGUAGE_CODES.get(audio_match.group(1).upper()) if audio_match else None
        subtitle = LANGUAGE_CODES.get(subtitle_match.group(1).upper()) if subtitle_match else None
        relevant = bool(format_label) or (original is not None and original != "German")
        if not relevant:
            logger.debug("Excluding German-only Universum screening: %s", title)
            continue
        if not today <= screening_date <= end_date:
            continue
        auditorium = next((text for text in metadata_parts if text.startswith("Universum ")), None)
        dimension = next((value for value in ("2D", "3D") if re.search(rf"\b{value}\b", metadata)), None)
        technology = "D-BOX" if "D-BOX" in metadata.upper() else None
        seen.add(Screening("universum", "Universum City Kinos Karlsruhe", screening_date, clock, title, format_label,
                           original, subtitle, auditorium, movie_urls.get(spans[0]) or None, _safe_url(ticket.get("href")),
                           dimension, technology, None))
    if parsed == 0:
        raise UniversumError("Universum program contains no usable screening entries; the website may have changed.")
    return sorted(seen, key=lambda item: (item.date, item.time, item.movie_title.casefold(), item.auditorium or "")), parsed


def parse_program(content: str, *, today: date, days: int) -> tuple[list[Screening], int]:
    soup = BeautifulSoup(content, "html.parser")
    return _parse_embedded_program(soup, today=today, days=days) or _parse_html_program(soup, today=today, days=days)


class UniversumSource(CinemaSource):
    cinema_id = "universum"
    cinema_name = "Universum City Kinos Karlsruhe"

    def fetch(self, *, days: int, today: date, use_cache: bool) -> list[Screening]:
        screenings, parsed = parse_program(fetch_program_html(use_cache=use_cache), today=today, days=days)
        logging.getLogger(__name__).debug("Universum overview requests: 1; detail requests: 0; parsed %d, retained %d", parsed, len(screenings))
        return screenings

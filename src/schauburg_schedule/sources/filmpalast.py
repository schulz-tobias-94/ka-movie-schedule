from __future__ import annotations

import html
import json
import logging
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from platformdirs import user_cache_dir

from ..models import Screening
from .base import CinemaSource, SourceError

SCHEDULE_URL = "https://filmpalast.net/programmuebersicht/?time=week"
USER_AGENT = "schauburg-schedule/0.1 (https://github.com/schauburg-schedule)"
CACHE_TTL_SECONDS = 15 * 60
# Website labels mapped to stable internal language names. Keep source spellings here.
LANGUAGE_LABELS = {
    "englisch": "English", "english": "English", "koreanisch": "Korean",
    "japanisch": "Japanese", "turkisch": "Turkish", "tuerkisch": "Turkish",
    "franzosisch": "French", "spanisch": "Spanish", "italienisch": "Italian",
    "polnisch": "Polish", "arabisch": "Arabic", "persisch": "Persian", "farsi": "Persian",
    "hindi": "Hindi", "tamil": "Tamil", "tamilisch": "Tamil", "ukrainisch": "Ukrainian",
    "russisch": "Russian", "chinesisch": "Chinese", "mandarin": "Chinese", "kantonesisch": "Cantonese",
}
VERSION_MARKERS = frozenset({"ov", "omu", "omeu", "omdu", "original", "originalversion"})


class FilmpalastParseError(SourceError):
    pass


class FilmpalastFetchError(SourceError):
    pass


def normalize(value: str) -> str:
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def _fold(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", normalize(value).casefold()) if not unicodedata.combining(char))


def parse_language_label(value: str) -> tuple[str | None, str | None, bool]:
    """Return spoken/subtitle languages and relevance from one source format label."""
    folded = _fold(value)
    words = re.sub(r"[^a-z0-9]+", " ", folded)
    matches = sorted(
        (match.start(), language)
        for label, language in LANGUAGE_LABELS.items()
        if (match := re.search(rf"\b{re.escape(label)}\w*\b", words))
    )
    original = matches[0][1] if matches else None
    marker = any(re.search(rf"\b{re.escape(item)}\b", words) for item in VERSION_MARKERS)
    subtitle = None
    if re.search(r"\buntertitel\w*\b|\bsubtitles?\b", words):
        if re.search(r"\bdeutsch\w*\b|\bgerman\w*\b", words):
            subtitle = "German"
        else:
            subtitle = next((language for _, language in matches[1:] if language != original), None)
    return original, subtitle, marker or original is not None


def _cache_path() -> Path:
    return Path(user_cache_dir("schauburg-schedule")) / "filmpalast-week.html"


def _read_cache(path: Path) -> str | None:
    try:
        if time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return None


def _write_cache(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        logging.getLogger(__name__).debug("Could not write Filmpalast cache: %s", exc)


def fetch_weekly_html(*, use_cache: bool = True, timeout: float = 20) -> str:
    cache = _cache_path()
    if use_cache and (cached := _read_cache(cache)) is not None:
        logging.getLogger(__name__).debug("Using cached Filmpalast schedule from %s", cache)
        return cached
    try:
        response = requests.get(SCHEDULE_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FilmpalastFetchError(f"Could not retrieve {SCHEDULE_URL}: {exc}") from exc
    if "pmkinoFrontVars" not in response.text:
        raise FilmpalastFetchError("Filmpalast response has no embedded program data; the website may have changed.")
    if use_cache:
        _write_cache(cache, response.text)
    return response.text


def _program_data(content: str) -> dict:
    match = re.search(r"var pmkinoFrontVars = (.*?);\s*//\# sourceURL", content, re.DOTALL)
    if not match:
        raise FilmpalastParseError("Filmpalast embedded program data was not found.")
    try:
        data = json.loads(match.group(1))["apiData"]
        if not all(isinstance(data.get(key), dict) and isinstance(data[key].get("items"), dict) for key in ("movies", "performances")):
            raise FilmpalastParseError("Filmpalast program data has an unexpected structure.")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FilmpalastParseError(f"Filmpalast program data is malformed: {exc}") from exc
    return data


def _movie_routes(content: str) -> dict:
    match = re.search(r"var pmkinoFrontVars = (.*?);\s*//\# sourceURL", content, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1)).get("routesData", {}).get("movies", {}).get("items", {})
    except json.JSONDecodeError:
        return {}


def _title_and_suffix(title: str) -> tuple[str, str | None]:
    match = re.search(r"\s+((?:[a-z]{2,4}\.\s*)?(?:ov|omu|omeu|omdu))\s*$", title, re.IGNORECASE)
    return (title[:match.start()].rstrip(), match.group(1)) if match else (title, None)


def parse_weekly_schedule(content: str, *, today: date, days: int) -> tuple[list[Screening], int]:
    data, routes = _program_data(content), _movie_routes(content)
    movies, performances = data["movies"]["items"], data["performances"]["items"]
    if not movies and not performances:
        return [], 0
    end_date = today + timedelta(days=days - 1)
    seen: set[Screening] = set()
    parsed = sum(isinstance(item, dict) and isinstance(item.get("timeUtc"), (int, float)) for item in performances.values())
    for movie in movies.values():
        if not isinstance(movie, dict) or not isinstance(movie.get("title"), str):
            continue
        labels = [normalize(item["name"]) for item in movie.get("technologyAttributes", []) if isinstance(item, dict) and isinstance(item.get("name"), str)]
        parsed_labels = [parse_language_label(label) for label in labels]
        if not any(item[2] for item in parsed_labels):
            continue
        original = next((item[0] for item in parsed_labels if item[0]), None)
        subtitle = next((item[1] for item in parsed_labels if item[1]), None)
        title, suffix = _title_and_suffix(normalize(movie["title"]))
        relevant_labels = [label for label, parsed_label in zip(labels, parsed_labels) if parsed_label[2]]
        if suffix and not any(_fold(suffix) == _fold(label) for label in relevant_labels):
            relevant_labels.append(suffix)
        format_label = " · ".join(dict.fromkeys(relevant_labels)) or None
        route = routes.get(movie.get("pk"), {})
        movie_url = route.get("uri_list", {}).get("de") if isinstance(route, dict) else None
        for performance_id in movie.get("performances", []):
            performance = performances.get(performance_id)
            if not isinstance(performance, dict) or not isinstance(performance.get("timeUtc"), (int, float)):
                continue
            local = datetime.fromtimestamp(performance["timeUtc"] / 1000, timezone.utc).astimezone(ZoneInfo("Europe/Berlin"))
            if not today <= local.date() <= end_date:
                continue
            seen.add(Screening(
                "filmpalast", "Filmpalast am ZKM", local.date(), local.time().replace(tzinfo=None), title,
                format_label, original, subtitle,
                performance.get("theatreName") if isinstance(performance.get("theatreName"), str) else None,
                movie_url if isinstance(movie_url, str) else None,
                performance.get("deeplinkURL") if isinstance(performance.get("deeplinkURL"), str) else None,
            ))
    if movies and performances and not parsed:
        raise FilmpalastParseError("Filmpalast program contains no usable screening times; the website may have changed.")
    return sorted(seen, key=lambda item: (item.date, item.time, item.movie_title.casefold(), item.format_label or "")), parsed


class FilmpalastSource(CinemaSource):
    cinema_id = "filmpalast"
    cinema_name = "Filmpalast am ZKM"

    def fetch(self, *, days: int, today: date, use_cache: bool) -> list[Screening]:
        screenings, parsed = parse_weekly_schedule(fetch_weekly_html(use_cache=use_cache), today=today, days=days)
        logger = logging.getLogger(__name__)
        logger.debug("Filmpalast parsed %d screenings and retained %d original-language screenings", parsed, len(screenings))
        return screenings

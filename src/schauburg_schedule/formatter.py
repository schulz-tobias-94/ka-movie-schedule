from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from html import escape

from .models import CinemaResult, Screening
from .enrichment.title_normalization import movie_key
from .enrichment.imdb import imdb_search_url

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _label(item: Screening) -> str:
    parts = [item.format_label] if item.format_label else []
    if item.original_language and item.original_language.casefold() not in " ".join(parts).casefold():
        parts.append(item.original_language)
    subtitle = f"{item.subtitle_language} subtitles" if item.subtitle_language else None
    if subtitle and item.subtitle_language.casefold() not in " ".join(parts).casefold():
        parts.append(subtitle)
    if item.technology and item.technology not in parts:
        parts.append(item.technology)
    return " · ".join(parts)


def format_text(screenings: Iterable[Screening]) -> str:
    screenings = list(screenings)
    show_cinema = len({item.cinema_id for item in screenings}) > 1
    rows = [("Date", "Day", *( ("Cinema",) if show_cinema else () ), "Title", "Type", "Time")]
    previous_date = previous_movie = None
    for item in screenings:
        is_new_date = item.date != previous_date
        row = (
            item.date.strftime("%d.%m.%y") if is_new_date else "",
            DAYS[item.date.weekday()] if is_new_date else "",
            item.cinema_name if show_cinema and (is_new_date or item.cinema_id != (previous_movie or (None, None))[0]) else "",
            item.movie_title if is_new_date or (item.cinema_id, item.movie_title) != previous_movie else "",
            _label(item),
            item.time.strftime("%H:%M:%S"),
        )
        rows.append(row if show_cinema else row[:2] + row[3:])
        previous_date, previous_movie = item.date, (item.cinema_id, item.movie_title)
    widths = [max(len(row[index]) for row in rows) for index in range(5)]
    return "\n".join("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in rows)


def format_json(screenings: Iterable[Screening]) -> str:
    screenings = list(screenings)
    show_cinema = len({item.cinema_id for item in screenings}) > 1
    def item_data(item: Screening) -> dict:
        data = {"date": item.date.isoformat(), "time": item.time.isoformat(), "title": item.movie_title,
                "version_label": item.format_label, "movie_url": item.movie_url}
        if show_cinema:
            data.update(cinema_id=item.cinema_id, cinema_name=item.cinema_name)
        for key in ("original_language", "subtitle_language", "auditorium", "booking_url", "dimension", "technology", "screening_url"):
            if (value := getattr(item, key)) is not None:
                data[key] = value
        return data
    return json.dumps([
        item_data(item) for item in screenings
    ], ensure_ascii=False, indent=2) + "\n"


HTML_CINEMAS = (
    ("schauburg", "Schauburg Karlsruhe", "Schauburg", "https://www.schauburg.de/spielplan"),
    ("filmpalast", "Filmpalast am ZKM", "Filmpalast", "https://filmpalast.net/programmuebersicht/?time=week"),
    ("universum", "Universum City Kinos Karlsruhe", "Universum", "https://www.universum-city.de/de/programm"),
)
GERMAN_LANGUAGES = {"English": "Englisch", "German": "Deutsch", "Korean": "Koreanisch", "Japanese": "Japanisch", "Spanish": "Spanisch", "French": "Französisch", "Italian": "Italienisch", "Turkish": "Türkisch", "Ukrainian": "Ukrainisch", "Russian": "Russisch", "Polish": "Polnisch", "Arabic": "Arabisch", "Persian": "Persisch", "Chinese": "Chinesisch", "Cantonese": "Kantonesisch"}
GERMAN_DAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
GERMAN_MONTHS = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")
TMDB_URL = "https://www.themoviedb.org/"
# Official TMDb Blue Square 2 attribution SVG, embedded unchanged for standalone output.
TMDB_LOGO_SVG = '''<svg class="tmdb-logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 185.04 133.4" aria-hidden="true" focusable="false"><defs><style>.tmdb-logo .cls-1{fill:url(#tmdb-gradient);}</style><linearGradient id="tmdb-gradient" y1="66.7" x2="185.04" y2="66.7" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#90cea1"/><stop offset="0.56" stop-color="#3cbec9"/><stop offset="1" stop-color="#00b3e5"/></linearGradient></defs><path class="cls-1" d="M51.06,66.7h0A17.67,17.67,0,0,1,68.73,49h-.1A17.67,17.67,0,0,1,86.3,66.7h0A17.67,17.67,0,0,1,68.63,84.37h.1A17.67,17.67,0,0,1,51.06,66.7Zm82.67-31.33h32.9A17.67,17.67,0,0,0,184.3,17.7h0A17.67,17.67,0,0,0,166.63,0h-32.9A17.67,17.67,0,0,0,116.06,17.7h0A17.67,17.67,0,0,0,133.73,35.37Zm-113,98h63.9A17.67,17.67,0,0,0,102.3,115.7h0A17.67,17.67,0,0,0,84.63,98H20.73A17.67,17.67,0,0,0,3.06,115.7h0A17.67,17.67,0,0,0,20.73,133.37Zm83.92-49h6.25L125.5,49h-8.35l-8.9,23.2h-.1L99.4,49H90.5Zm32.45,0h7.8V49h-7.8Zm22.2,0h24.95V77.2H167.1V70h15.35V62.8H167.1V56.2h16.25V49h-24ZM10.1,35.4h7.8V6.9H28V0H0V6.9H10.1ZM39,35.4h7.8V20.1H61.9V35.4h7.8V0H61.9V13.2H46.75V0H39Zm41.25,0h25V28.2H88V21h15.35V13.8H88V7.2h16.25V0h-24Zm-79,49H9V57.25h.1l9,27.15H24l9.3-27.15h.1V84.4h7.8V49H29.45l-8.2,23.1h-.1L13,49H1.2Zm112.09,49H126a24.59,24.59,0,0,0,7.56-1.15,19.52,19.52,0,0,0,6.35-3.37,16.37,16.37,0,0,0,4.37-5.5A16.91,16.91,0,0,0,146,115.8a18.5,18.5,0,0,0-1.68-8.25,15.1,15.1,0,0,0-4.52-5.53A18.55,18.55,0,0,0,133.07,99,33.54,33.54,0,0,0,125,98H113.29Zm7.81-28.2h4.6a17.43,17.43,0,0,1,4.67.62,11.68,11.68,0,0,1,3.88,1.88,9,9,0,0,1,2.62,3.18,9.87,9.87,0,0,1,1,4.52,11.92,11.92,0,0,1-1,5.08,8.69,8.69,0,0,1-2.67,3.34,10.87,10.87,0,0,1-4,1.83,21.57,21.57,0,0,1-5,.55H121.1Zm36.14,28.2h14.5a23.11,23.11,0,0,0,4.73-.5,13.38,13.38,0,0,0,4.27-1.65,9.42,9.42,0,0,0,3.1-3,8.52,8.52,0,0,0,1.2-4.68,9.16,9.16,0,0,0-.55-3.2,7.79,7.79,0,0,0-1.57-2.62,8.38,8.38,0,0,0-2.45-1.85,10,10,0,0,0-3.18-1v-.1a9.28,9.28,0,0,0,4.43-2.82,7.42,7.42,0,0,0,1.67-5,8.34,8.34,0,0,0-1.15-4.65,7.88,7.88,0,0,0-3-2.73,12.9,12.9,0,0,0-4.17-1.3,34.42,34.42,0,0,0-4.63-.32h-13.2Zm7.8-28.8h5.3a10.79,10.79,0,0,1,1.85.17,5.77,5.77,0,0,1,1.7.58,3.33,3.33,0,0,1,1.23,1.13,3.22,3.22,0,0,1,.47,1.82,3.63,3.63,0,0,1-.42,1.8,3.34,3.34,0,0,1-1.13,1.2,4.78,4.78,0,0,1-1.57.65,8.16,8.16,0,0,1-1.78.2H165Zm0,14.15h5.9a15.12,15.12,0,0,1,2.05.15,7.83,7.83,0,0,1,2,.55,4,4,0,0,1,1.58,1.17,3.13,3.13,0,0,1,.62,2,3.71,3.71,0,0,1-.47,1.95,4,4,0,0,1-1.23,1.3,4.78,4.78,0,0,1-1.67.7,8.91,8.91,0,0,1-1.83.2h-7Z"/></svg>'''


def _safe_url(value: str | None) -> str | None:
    from urllib.parse import urlparse
    return value if value and urlparse(value).scheme in {"http", "https"} else None


def _de_language(value: str | None) -> str | None:
    return GERMAN_LANGUAGES.get(value, value)


def _html_label(item: Screening) -> str:
    parts = [item.format_label] if item.format_label else []
    for index, value in enumerate((_de_language(item.original_language), f"{_de_language(item.subtitle_language)}e Untertitel" if item.subtitle_language else None, item.auditorium, item.dimension, item.technology)):
        if index == 1 and "untertitel" in " ".join(parts).casefold():
            continue
        if value and value.casefold() not in " ".join(parts).casefold():
            parts.append(value)
    return " · ".join(parts)


def _de_date(value: date, today: date) -> str:
    relative = "Heute · " if value == today else "Morgen · " if value == date.fromordinal(today.toordinal() + 1) else ""
    return f"{relative}{GERMAN_DAYS[value.weekday()]}, {value.day}. {GERMAN_MONTHS[value.month - 1]} {value.year}"


def _render_screening(item: Screening) -> str:
    links = []
    if (url := _safe_url(item.booking_url)):
        links.append(f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">Tickets</a>')
    elif (url := _safe_url(item.screening_url)):
        links.append(f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">Details</a>')
    label = _html_label(item)
    details = label.removeprefix(item.format_label or "").removeprefix(" · ")
    badge = f' <span class="format-badge">{escape(item.format_label)}</span>' if item.format_label else ""
    return f'<li><time datetime="{item.time.isoformat()}">{item.time.strftime("%H:%M")}</time>{badge}{f" <span>{escape(details)}</span>" if details else ""}{f" <span class=\"action\">{links[0]}</span>" if links else ""}</li>'


def _render_schedule(items: list[Screening], *, today: date, imdb_matches: Mapping[str, object]) -> str:
    groups: dict[date, dict[str, list[Screening]]] = {}
    for item in sorted(items, key=lambda value: (value.date, value.movie_title.casefold(), value.time, value.auditorium or "")):
        groups.setdefault(item.date, {}).setdefault(item.movie_title, []).append(item)
    sections = []
    for screening_date, movies in groups.items():
        cards = []
        for title, showings in movies.items():
            movie_url = _safe_url(showings[0].movie_url)
            imdb_url = _safe_url(getattr(imdb_matches.get(movie_key(title, showings[0].release_year)), "url", None)) or imdb_search_url(title)
            heading = escape(title)
            if imdb_url:
                heading = f'<a href="{escape(imdb_url, quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="Open {escape(title, quote=True)} on IMDb">{heading}</a>'
            has_screening_actions = any(_safe_url(item.booking_url) or _safe_url(item.screening_url) for item in showings)
            details = f'<a class="movie-action" href="{escape(movie_url, quote=True)}" target="_blank" rel="noopener noreferrer">Details</a>' if movie_url and not has_screening_actions else ""
            cards.append(f'<article class="movie"><div class="movie-header"><h3>{heading}</h3>{details}</div><ul>{"".join(_render_screening(item) for item in showings)}</ul></article>')
        sections.append(f'<section class="date"><h2><time datetime="{screening_date.isoformat()}">{_de_date(screening_date, today)}</time></h2>{"".join(cards)}</section>')
    return "".join(sections)


def _render_status(result: CinemaResult) -> str:
    timestamp = result.retrieved_at.strftime("%d.%m.%Y, %H:%M")
    if result.success and result.fresh:
        return f'<p class="status current">Aktuell · zuletzt abgerufen <time datetime="{result.retrieved_at.isoformat()}">{timestamp}</time></p>'
    if result.success:
        return f'<p class="status warning">Vorübergehend nicht aktualisierbar. Angezeigt wird der letzte erfolgreiche Stand vom <time datetime="{result.retrieved_at.isoformat()}">{timestamp}</time>; vergangene Vorstellungen wurden entfernt.</p>'
    return '<p class="status failed">Der Spielplan konnte derzeit nicht geladen werden und es liegt kein nutzbarer letzter Stand vor.</p>'


def _render_panel(result: CinemaResult, *, cinema_id: str, cinema_name: str, official_url: str, start_date: date, end_date: date, imdb_matches: Mapping[str, object]) -> str:
    items = [item for item in result.screenings if start_date <= item.date <= end_date]
    heading = f'<h2>{escape(cinema_name)}</h2><p><a href="{official_url}">Offizielles Programm</a> · {len(items)} passende Vorstellungen · {start_date.strftime("%d.%m.%Y")} bis {end_date.strftime("%d.%m.%Y")}</p>'
    if not result.success:
        content = _render_status(result)
    elif not items:
        content = _render_status(result) + '<p>Für diesen Zeitraum wurden keine passenden OV-, OmU- oder fremdsprachigen Vorstellungen gefunden.</p>'
    else:
        content = _render_status(result) + _render_schedule(items, today=start_date, imdb_matches=imdb_matches)
    return f'<section id="panel-{cinema_id}" class="cinema-panel" data-cinema="{cinema_id}" role="tabpanel" aria-labelledby="tab-{cinema_id}">{heading}{content}</section>'


def format_html(results: Iterable[CinemaResult], *, start_date: date, end_date: date, updated_at: datetime, site_title: str = "KA OV Schedule", imdb_matches: Mapping[str, object] | None = None) -> str:
    """Render all configured cinema results as a standalone progressively enhanced page."""
    by_id, imdb_matches = {result.cinema_id: result for result in results}, imdb_matches or {}
    panels, tabs = [], []
    for cinema_id, cinema_name, short_name, official_url in HTML_CINEMAS:
        result = by_id.get(cinema_id, CinemaResult(cinema_id, cinema_name, (), updated_at, False, "not requested", False))
        tabs.append(f'<button id="tab-{cinema_id}" data-cinema="{cinema_id}" role="tab" aria-selected="{str(cinema_id == "schauburg").lower()}" aria-controls="panel-{cinema_id}" tabindex="{0 if cinema_id == "schauburg" else -1}">{short_name}</button>')
        panels.append(_render_panel(result, cinema_id=cinema_id, cinema_name=cinema_name, official_url=official_url, start_date=start_date, end_date=end_date, imdb_matches=imdb_matches))
    timestamp, tmdb_url = updated_at.strftime("%d.%m.%Y, %H:%M %Z"), _safe_url(TMDB_URL)
    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="OV-, OmU- und fremdsprachige Kinovorstellungen in Karlsruhe">
  <link rel="icon" href="assets/cinema-32x32.ico" sizes="32x32" type="image/x-icon">
  <title>{escape(site_title)}</title>
  <style>
    :root {{ --accent: #0f766e; --accent-dark: #115e59; --accent-light: #ccfbf1; --accent-soft: #f0fdfa; --accent-border: #99f6e4; --page: #f7f6f1; --surface: #ffffff; --ink: #1d2424; --muted: #53605c; --focus: #ea580c; --positive: #166534; --warning: #a16207; --danger: #b91c1c; font-family: system-ui, sans-serif; color: var(--ink); background: var(--page); }}
    body {{ margin: 0; line-height: 1.5; background: var(--page); transition: color .15s, background-color .15s; }}
    body[data-active-cinema="schauburg"] {{ --accent: #0f766e; --accent-dark: #115e59; --accent-light: #ccfbf1; --accent-soft: #f0fdfa; --accent-border: #99f6e4; }}
    body[data-active-cinema="filmpalast"] {{ --accent: #1e3a8a; --accent-dark: #172554; --accent-light: #dbeafe; --accent-soft: #eff6ff; --accent-border: #bfdbfe; }}
    body[data-active-cinema="universum"] {{ --accent: #b91c1c; --accent-dark: #7f1d1d; --accent-light: #fee2e2; --accent-soft: #fef2f2; --accent-border: #fecaca; }}
    header, main, footer {{ max-width: 52rem; margin: auto; padding: 1.25rem; }} header {{ max-width: none; position: relative; background: #263b3b; color: white; padding-left: max(1.25rem, calc((100% - 52rem) / 2)); padding-right: max(1.25rem, calc((100% - 52rem) / 2)); }} header::after {{ content: ""; position: absolute; bottom: 0; left: 0; width: 100%; height: 4px; background: var(--accent); }}
    h1 {{ margin: 0; font-size: 1.8rem; }} h2 {{ font-size: 1.2rem; margin: 1.4rem 0 .35rem; }} h3 {{ font-size: 1rem; margin: 0; }} a {{ color: var(--accent-dark); text-decoration: underline; text-underline-offset: .14em; }} a:hover {{ color: var(--accent); }} header p, .muted {{ color: #d9e5e1; }}
    [role=tablist] {{ display: flex; gap: .35rem; overflow-x: auto; border-bottom: 1px solid #b8c2be; }} [role=tab] {{ appearance: none; border: 0; border-bottom: 4px solid #a8b2b0; border-radius: .3rem .3rem 0 0; background: transparent; color: inherit; font: inherit; font-weight: 700; padding: .75rem 1rem; min-height: 2.75rem; white-space: nowrap; cursor: pointer; transition: color .15s, background-color .15s, border-color .15s; }} [role=tab]:hover {{ background: #e9ece8; }} [role=tab][data-cinema="schauburg"] {{ border-color: #0f766e; }} [role=tab][data-cinema="filmpalast"] {{ border-color: #1e3a8a; }} [role=tab][data-cinema="universum"] {{ border-color: #b91c1c; }} [role=tab][aria-selected=true] {{ background: var(--accent-soft); color: var(--accent-dark); border-bottom-width: 6px; font-weight: 800; }}
    [role=tab]:focus-visible, a:focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }} [role=tabpanel] {{ padding: .4rem 0 1rem; }} [role=tabpanel][hidden] {{ display: none; }}
    .cinema-panel[data-cinema="schauburg"] {{ --panel-accent: #0f766e; --panel-dark: #115e59; --panel-soft: #f0fdfa; --panel-border: #99f6e4; }} .cinema-panel[data-cinema="filmpalast"] {{ --panel-accent: #1e3a8a; --panel-dark: #172554; --panel-soft: #eff6ff; --panel-border: #bfdbfe; }} .cinema-panel[data-cinema="universum"] {{ --panel-accent: #b91c1c; --panel-dark: #7f1d1d; --panel-soft: #fef2f2; --panel-border: #fecaca; }} .cinema-panel a {{ color: var(--panel-dark); }} .cinema-panel a:hover {{ color: var(--panel-accent); }}
    .status {{ margin: .75rem 0; padding-left: .65rem; border-left: 3px solid currentColor; }} .current {{ color: var(--positive); }} .warning {{ color: var(--warning); font-weight: 600; }} .failed {{ color: var(--danger); font-weight: 600; }}
    .date {{ margin-top: 1.5rem; border-left: 3px solid var(--panel-accent); padding-left: .75rem; }} .date h2 {{ color: var(--panel-dark); background: var(--panel-soft); border-bottom: 1px solid var(--panel-border); padding: .35rem .5rem; }} .movie {{ border: 1px solid var(--panel-border); border-radius: .3rem; background: var(--surface); margin: .6rem 0; padding: .75rem; }} .movie-header {{ align-items: baseline; display: flex; gap: .75rem; justify-content: space-between; }} .movie h3 a:hover {{ text-decoration-thickness: .15em; }} ul {{ list-style: none; padding: 0; margin: .35rem 0 0; }} li {{ display: flex; flex-wrap: wrap; gap: .35rem; align-items: baseline; border-top: 1px solid color-mix(in srgb, var(--panel-border) 55%, transparent); padding: .35rem 0; }} li:first-child {{ border-top: 0; }} li time {{ font-variant-numeric: tabular-nums; font-weight: 700; min-width: 3.25rem; }} li span {{ color: var(--muted); }} .format-badge {{ background: var(--panel-accent); color: white !important; border-radius: .2rem; font-size: .82rem; font-weight: 800; line-height: 1.35; padding: .08rem .35rem; }} .action {{ margin-left: auto; }} .action a, .movie-action {{ background: var(--panel-accent); border-radius: .2rem; color: white !important; display: inline-block; font-weight: 700; padding: .16rem .45rem; text-decoration: none; }} .action a:hover, .movie-action:hover {{ background: var(--panel-dark); color: white !important; }} footer {{ color: #56615e; font-size: .9rem; }} .credits {{ border-top: 1px solid #c4ceca; margin-top: 1rem; padding-top: 1rem; }} .credits h2 {{ font-size: 1rem; margin: 0 0 .35rem; }} .credits p {{ margin: .35rem 0; }} .tmdb-link {{ display: inline-flex; vertical-align: middle; }} .tmdb-logo {{ display: block; height: 1.5rem; width: auto; }}
    @media (max-width: 34rem) {{ header, main, footer {{ padding: 1rem; }} h1 {{ font-size: 1.45rem; }} [role=tab] {{ padding-inline: .85rem; }} .movie-header {{ align-items: flex-start; flex-direction: column; gap: .35rem; }} .action {{ margin-left: 0; }} }}
    @media (prefers-color-scheme: dark) {{ :root {{ --page: #101716; --surface: #18211f; --ink: #edf4f0; --muted: #c0cbc6; }} body[data-active-cinema="schauburg"] {{ --accent: #5eead4; --accent-dark: #99f6e4; --accent-light: #134e4a; --accent-soft: #102f2d; --accent-border: #14b8a6; }} .cinema-panel[data-cinema="schauburg"] {{ --panel-accent: #5eead4; --panel-dark: #99f6e4; --panel-soft: #102f2d; --panel-border: #14b8a6; }} .cinema-panel[data-cinema="schauburg"] .format-badge, .cinema-panel[data-cinema="schauburg"] .action a, .cinema-panel[data-cinema="schauburg"] .movie-action {{ background: #134e4a; }} .cinema-panel[data-cinema="schauburg"] .action a:hover, .cinema-panel[data-cinema="schauburg"] .movie-action:hover {{ background: #0f766e; }} body[data-active-cinema="filmpalast"] {{ --accent: #93c5fd; --accent-dark: #bfdbfe; --accent-light: #172554; --accent-soft: #111c3d; --accent-border: #3b82f6; }} .cinema-panel[data-cinema="filmpalast"] {{ --panel-accent: #93c5fd; --panel-dark: #bfdbfe; --panel-soft: #111c3d; --panel-border: #3b82f6; }} .cinema-panel[data-cinema="filmpalast"] .format-badge, .cinema-panel[data-cinema="filmpalast"] .action a, .cinema-panel[data-cinema="filmpalast"] .movie-action {{ background: #172554; }} .cinema-panel[data-cinema="filmpalast"] .action a:hover, .cinema-panel[data-cinema="filmpalast"] .movie-action:hover {{ background: #1d4ed8; }} body[data-active-cinema="universum"] {{ --accent: #fca5a5; --accent-dark: #fecaca; --accent-light: #450a0a; --accent-soft: #321010; --accent-border: #ef4444; }} .cinema-panel[data-cinema="universum"] {{ --panel-accent: #fca5a5; --panel-dark: #fecaca; --panel-soft: #321010; --panel-border: #ef4444; }} .cinema-panel[data-cinema="universum"] .format-badge, .cinema-panel[data-cinema="universum"] .action a, .cinema-panel[data-cinema="universum"] .movie-action {{ background: #450a0a; }} .cinema-panel[data-cinema="universum"] .action a:hover, .cinema-panel[data-cinema="universum"] .movie-action:hover {{ background: #b91c1c; }} header {{ background: #17201f; }} [role=tablist] {{ border-color: #4c5a56; }} [role=tab]:hover {{ background: #26312e; }} [role=tab][aria-selected=true] {{ background: color-mix(in srgb, var(--accent-dark) 35%, #18211f); color: #f7fffb; }} .date h2 {{ background: color-mix(in srgb, var(--panel-accent) 16%, #18211f); }} .movie {{ background: #18211f; }} footer {{ color: #c0cbc6; }} .credits {{ border-color: #4c5a56; }} }}
    @media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto; transition: none !important; }} }}
  </style>
</head>
<body data-active-cinema="schauburg">
  <header><h1>{escape(site_title)}</h1><p>OV-, OmU- und fremdsprachige Kinovorstellungen in Karlsruhe</p><p>Erstellt <time datetime="{updated_at.isoformat()}">{timestamp}</time> · {start_date.strftime("%d.%m.%Y")} bis {end_date.strftime("%d.%m.%Y")}</p><p>Spielpläne können sich ändern. Bitte prüfe die Angaben beim Kino.</p></header>
  <main><nav aria-label="Kinoauswahl" role="tablist">{"".join(tabs)}</nav>{"".join(panels)}</main>
  <footer><section class="credits" aria-labelledby="credits-heading"><h2 id="credits-heading">Datenquellen &amp; Hinweise</h2><p><a class="tmdb-link" href="{escape(tmdb_url or '', quote=True)}" aria-label="TMDb öffnen">{TMDB_LOGO_SVG}</a></p><p>TMDb wird zur Zuordnung von Kinotiteln zu IMDb-Einträgen verwendet.</p><p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p><p>Dieses unabhängige Projekt ist nicht mit Schauburg, Filmpalast, Universum, IMDb oder TMDb verbunden. Spielpläne können sich ändern; bitte prüfe Ticketdetails beim jeweiligen Kino.</p></section></footer>
  <script>(function(){{const ids=['schauburg','filmpalast','universum'],tabs=ids.map(id=>document.getElementById('tab-'+id)),panels=ids.map(id=>document.getElementById('panel-'+id));function select(id,hash){{if(!ids.includes(id))return;document.body.dataset.activeCinema=id;tabs.forEach((tab,i)=>{{const active=tab.dataset.cinema===id;tab.setAttribute('aria-selected',active);tab.tabIndex=active?0:-1;panels[i].hidden=!active;}});try{{localStorage.setItem('schauburg-schedule-cinema',id)}}catch(e){{}}if(hash&&location.hash.slice(1)!==id)history.pushState(null,'','#'+id)}}function initial(){{const hash=location.hash.slice(1);if(ids.includes(hash))return hash;try{{const saved=localStorage.getItem('schauburg-schedule-cinema');if(ids.includes(saved))return saved}}catch(e){{}}return 'schauburg'}}tabs.forEach((tab,index)=>{{tab.addEventListener('click',()=>select(tab.dataset.cinema,true));tab.addEventListener('keydown',event=>{{let next;if(event.key==='ArrowRight')next=(index+1)%ids.length;else if(event.key==='ArrowLeft')next=(index+ids.length-1)%ids.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=ids.length-1;else if(event.key==='Enter'||event.key===' '){{event.preventDefault();select(tab.dataset.cinema,true);return}}else return;event.preventDefault();tabs[next].focus();select(ids[next],true)}})}});window.addEventListener('hashchange',()=>select(location.hash.slice(1),false));select(initial(),false)}})();</script>
</body>
</html>
'''

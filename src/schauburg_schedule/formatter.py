from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from html import escape

from .models import CinemaResult, Screening

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
        links.append(f'<a href="{escape(url, quote=True)}">Tickets</a>')
    elif (url := _safe_url(item.screening_url)):
        links.append(f'<a href="{escape(url, quote=True)}">Details</a>')
    label = _html_label(item)
    details = label.removeprefix(item.format_label or "").removeprefix(" · ")
    badge = f' <span class="format-badge">{escape(item.format_label)}</span>' if item.format_label else ""
    return f'<li><time datetime="{item.time.isoformat()}">{item.time.strftime("%H:%M")}</time>{badge}{f" <span>{escape(details)}</span>" if details else ""}{f" <span class=\"action\">{links[0]}</span>" if links else ""}</li>'


def _render_schedule(items: list[Screening], *, today: date) -> str:
    groups: dict[date, dict[str, list[Screening]]] = {}
    for item in sorted(items, key=lambda value: (value.date, value.movie_title.casefold(), value.time, value.auditorium or "")):
        groups.setdefault(item.date, {}).setdefault(item.movie_title, []).append(item)
    sections = []
    for screening_date, movies in groups.items():
        cards = []
        for title, showings in movies.items():
            movie_url = _safe_url(showings[0].movie_url)
            heading = escape(title)
            if movie_url:
                heading = f'<a href="{escape(movie_url, quote=True)}">{heading}</a>'
            cards.append(f'<article class="movie"><h3>{heading}</h3><ul>{"".join(_render_screening(item) for item in showings)}</ul></article>')
        sections.append(f'<section class="date"><h2><time datetime="{screening_date.isoformat()}">{_de_date(screening_date, today)}</time></h2>{"".join(cards)}</section>')
    return "".join(sections)


def _render_status(result: CinemaResult) -> str:
    timestamp = result.retrieved_at.strftime("%d.%m.%Y, %H:%M")
    if result.success and result.fresh:
        return f'<p class="status current">Aktuell · zuletzt abgerufen <time datetime="{result.retrieved_at.isoformat()}">{timestamp}</time></p>'
    if result.success:
        return f'<p class="status warning">Vorübergehend nicht aktualisierbar. Angezeigt wird der letzte erfolgreiche Stand vom <time datetime="{result.retrieved_at.isoformat()}">{timestamp}</time>; vergangene Vorstellungen wurden entfernt.</p>'
    return '<p class="status failed">Der Spielplan konnte derzeit nicht geladen werden und es liegt kein nutzbarer letzter Stand vor.</p>'


def _render_panel(result: CinemaResult, *, cinema_id: str, cinema_name: str, official_url: str, start_date: date, end_date: date) -> str:
    items = [item for item in result.screenings if start_date <= item.date <= end_date]
    heading = f'<h2>{escape(cinema_name)}</h2><p><a href="{official_url}">Offizielles Programm</a> · {len(items)} passende Vorstellungen · {start_date.strftime("%d.%m.%Y")} bis {end_date.strftime("%d.%m.%Y")}</p>'
    if not result.success:
        content = _render_status(result)
    elif not items:
        content = _render_status(result) + '<p>Für diesen Zeitraum wurden keine passenden OV-, OmU- oder fremdsprachigen Vorstellungen gefunden.</p>'
    else:
        content = _render_status(result) + _render_schedule(items, today=start_date)
    return f'<section id="panel-{cinema_id}" class="cinema-panel" data-cinema="{cinema_id}" role="tabpanel" aria-labelledby="tab-{cinema_id}">{heading}{content}</section>'


def format_html(results: Iterable[CinemaResult], *, start_date: date, end_date: date, updated_at: datetime, site_title: str = "Karlsruhe Originalfassungen") -> str:
    """Render all configured cinema results as a standalone progressively enhanced page."""
    by_id = {result.cinema_id: result for result in results}
    panels, tabs = [], []
    for cinema_id, cinema_name, short_name, official_url in HTML_CINEMAS:
        result = by_id.get(cinema_id, CinemaResult(cinema_id, cinema_name, (), updated_at, False, "not requested", False))
        tabs.append(f'<button id="tab-{cinema_id}" data-cinema="{cinema_id}" role="tab" aria-selected="{str(cinema_id == "schauburg").lower()}" aria-controls="panel-{cinema_id}" tabindex="{0 if cinema_id == "schauburg" else -1}">{short_name}</button>')
        panels.append(_render_panel(result, cinema_id=cinema_id, cinema_name=cinema_name, official_url=official_url, start_date=start_date, end_date=end_date))
    timestamp = updated_at.strftime("%d.%m.%Y, %H:%M %Z")
    return f'''<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="OV-, OmU- und fremdsprachige Kinovorstellungen in Karlsruhe">
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
    .date {{ margin-top: 1.5rem; border-left: 3px solid var(--panel-accent); padding-left: .75rem; }} .date h2 {{ color: var(--panel-dark); background: var(--panel-soft); border-bottom: 1px solid var(--panel-border); padding: .35rem .5rem; }} .movie {{ border: 1px solid var(--panel-border); border-radius: .3rem; background: var(--surface); margin: .6rem 0; padding: .75rem; }} .movie h3 a:hover {{ text-decoration-thickness: .15em; }} ul {{ list-style: none; padding: 0; margin: .35rem 0 0; }} li {{ display: flex; flex-wrap: wrap; gap: .35rem; align-items: baseline; border-top: 1px solid color-mix(in srgb, var(--panel-border) 55%, transparent); padding: .35rem 0; }} li:first-child {{ border-top: 0; }} li time {{ font-variant-numeric: tabular-nums; font-weight: 700; min-width: 3.25rem; }} li span {{ color: var(--muted); }} .format-badge {{ background: var(--panel-accent); color: white !important; border-radius: .2rem; font-size: .82rem; font-weight: 800; line-height: 1.35; padding: .08rem .35rem; }} .action {{ margin-left: auto; }} .action a {{ background: var(--panel-accent); border-radius: .2rem; color: white; display: inline-block; font-weight: 700; padding: .16rem .45rem; text-decoration: none; }} .action a:hover {{ background: var(--panel-dark); color: white; }} footer {{ color: #56615e; font-size: .9rem; }}
    @media (max-width: 34rem) {{ header, main, footer {{ padding: 1rem; }} h1 {{ font-size: 1.45rem; }} [role=tab] {{ padding-inline: .85rem; }} .action {{ margin-left: 0; }} }}
    @media (prefers-color-scheme: dark) {{ :root {{ --page: #101716; --surface: #18211f; --ink: #edf4f0; --muted: #c0cbc6; }} body[data-active-cinema="schauburg"] {{ --accent: #5eead4; --accent-dark: #99f6e4; --accent-light: #134e4a; --accent-soft: #102f2d; --accent-border: #14b8a6; }} .cinema-panel[data-cinema="schauburg"] {{ --panel-accent: #5eead4; --panel-dark: #99f6e4; --panel-soft: #102f2d; --panel-border: #14b8a6; }} .cinema-panel[data-cinema="schauburg"] .format-badge, .cinema-panel[data-cinema="schauburg"] .action a {{ background: #134e4a; }} .cinema-panel[data-cinema="schauburg"] .action a:hover {{ background: #0f766e; }} body[data-active-cinema="filmpalast"] {{ --accent: #93c5fd; --accent-dark: #bfdbfe; --accent-light: #172554; --accent-soft: #111c3d; --accent-border: #3b82f6; }} .cinema-panel[data-cinema="filmpalast"] {{ --panel-accent: #93c5fd; --panel-dark: #bfdbfe; --panel-soft: #111c3d; --panel-border: #3b82f6; }} .cinema-panel[data-cinema="filmpalast"] .format-badge, .cinema-panel[data-cinema="filmpalast"] .action a {{ background: #172554; }} .cinema-panel[data-cinema="filmpalast"] .action a:hover {{ background: #1d4ed8; }} body[data-active-cinema="universum"] {{ --accent: #fca5a5; --accent-dark: #fecaca; --accent-light: #450a0a; --accent-soft: #321010; --accent-border: #ef4444; }} .cinema-panel[data-cinema="universum"] {{ --panel-accent: #fca5a5; --panel-dark: #fecaca; --panel-soft: #321010; --panel-border: #ef4444; }} .cinema-panel[data-cinema="universum"] .format-badge, .cinema-panel[data-cinema="universum"] .action a {{ background: #450a0a; }} .cinema-panel[data-cinema="universum"] .action a:hover {{ background: #b91c1c; }} header {{ background: #17201f; }} [role=tablist] {{ border-color: #4c5a56; }} [role=tab]:hover {{ background: #26312e; }} [role=tab][aria-selected=true] {{ background: color-mix(in srgb, var(--accent-dark) 35%, #18211f); color: #f7fffb; }} .date h2 {{ background: color-mix(in srgb, var(--panel-accent) 16%, #18211f); }} .movie {{ background: #18211f; }} footer {{ color: #c0cbc6; }} }}
    @media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto; transition: none !important; }} }}
  </style>
</head>
<body data-active-cinema="schauburg">
  <header><h1>{escape(site_title)}</h1><p>OV-, OmU- und fremdsprachige Kinovorstellungen in Karlsruhe</p><p>Erstellt <time datetime="{updated_at.isoformat()}">{timestamp}</time> · {start_date.strftime("%d.%m.%Y")} bis {end_date.strftime("%d.%m.%Y")}</p><p>Spielpläne können sich ändern. Bitte prüfe die Angaben beim Kino.</p></header>
  <main><nav aria-label="Kinoauswahl" role="tablist">{"".join(tabs)}</nav>{"".join(panels)}</main>
  <footer>Diese unabhängige Übersicht übernimmt keine Gewähr für die Aktualität der Kinoangaben.</footer>
  <script>(function(){{const ids=['schauburg','filmpalast','universum'],tabs=ids.map(id=>document.getElementById('tab-'+id)),panels=ids.map(id=>document.getElementById('panel-'+id));function select(id,hash){{if(!ids.includes(id))return;document.body.dataset.activeCinema=id;tabs.forEach((tab,i)=>{{const active=tab.dataset.cinema===id;tab.setAttribute('aria-selected',active);tab.tabIndex=active?0:-1;panels[i].hidden=!active;}});try{{localStorage.setItem('schauburg-schedule-cinema',id)}}catch(e){{}}if(hash&&location.hash.slice(1)!==id)history.pushState(null,'','#'+id)}}function initial(){{const hash=location.hash.slice(1);if(ids.includes(hash))return hash;try{{const saved=localStorage.getItem('schauburg-schedule-cinema');if(ids.includes(saved))return saved}}catch(e){{}}return 'schauburg'}}tabs.forEach((tab,index)=>{{tab.addEventListener('click',()=>select(tab.dataset.cinema,true));tab.addEventListener('keydown',event=>{{let next;if(event.key==='ArrowRight')next=(index+1)%ids.length;else if(event.key==='ArrowLeft')next=(index+ids.length-1)%ids.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=ids.length-1;else if(event.key==='Enter'||event.key===' '){{event.preventDefault();select(tab.dataset.cinema,true);return}}else return;event.preventDefault();tabs[next].focus();select(ids[next],true)}})}});window.addEventListener('hashchange',()=>select(location.hash.slice(1),false));select(initial(),false)}})();</script>
</body>
</html>
'''

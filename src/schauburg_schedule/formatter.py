from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from html import escape

from .models import Screening

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def format_text(screenings: Iterable[Screening]) -> str:
    rows = [("Date", "Day", "Title", "Type", "Time")]
    previous_date = previous_title = None
    for item in screenings:
        is_new_date = item.date != previous_date
        rows.append((
            item.date.strftime("%d.%m.%y") if is_new_date else "",
            DAYS[item.date.weekday()] if is_new_date else "",
            item.title if is_new_date or item.title != previous_title else "",
            item.version_label,
            item.time.strftime("%H:%M:%S"),
        ))
        previous_date, previous_title = item.date, item.title
    widths = [max(len(row[index]) for row in rows) for index in range(5)]
    return "\n".join("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in rows)


def format_json(screenings: Iterable[Screening]) -> str:
    return json.dumps([
        {"date": item.date.isoformat(), "time": item.time.isoformat(), "title": item.title,
         "version_label": item.version_label, "movie_url": item.movie_url}
        for item in screenings
    ], ensure_ascii=False, indent=2) + "\n"


def format_html(
    screenings: Iterable[Screening], *, start_date: date, end_date: date, updated_at: datetime
) -> str:
    """Format already-filtered screenings as a self-contained HTML page."""
    grouped: dict[date, dict[str, list[Screening]]] = {}
    for item in screenings:
        if start_date <= item.date <= end_date:
            grouped.setdefault(item.date, {}).setdefault(item.title, []).append(item)

    sections = []
    for screening_date, movies in grouped.items():
        articles = []
        for title, showings in movies.items():
            first = showings[0]
            heading = escape(title)
            if first.movie_url:
                heading = f'<a href="{escape(first.movie_url, quote=True)}" aria-label="Open Schauburg page for {escape(title, quote=True)}">{heading}</a>'
            times = "".join(
                f'<li><time datetime="{item.time.isoformat()}">{item.time.strftime("%H:%M")}</time> <span>{escape(item.version_label)}</span></li>'
                for item in showings
            )
            articles.append(f"<article><h3>{heading}</h3><ul>{times}</ul></article>")
        label = screening_date.strftime("%A, %d %B %Y")
        sections.append(f'<section><h2><time datetime="{screening_date.isoformat()}">{label}</time></h2>{"".join(articles)}</section>')
    content = "".join(sections) or "<p>No matching original-language screenings were found for this period.</p>"
    updated = updated_at.strftime("%d.%m.%Y, %H:%M %Z")
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Schauburg – Originalfassungen</title>
  <style>
    :root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #202124; background: #f7f5f0; }}
    body {{ margin: 0; line-height: 1.5; }}
    header, main, footer {{ max-width: 48rem; margin: auto; padding: 1.25rem; }}
    header {{ background: #282b33; color: #fff; max-width: none; padding-left: max(1.25rem, calc((100% - 48rem) / 2)); padding-right: max(1.25rem, calc((100% - 48rem) / 2)); }}
    h1 {{ margin: 0; font-size: 1.8rem; }} h2 {{ font-size: 1.2rem; margin: 2rem 0 .5rem; }} h3 {{ font-size: 1rem; margin: 0; }}
    article {{ padding: .8rem 0; border-top: 1px solid #d7d3ca; }} ul {{ list-style: none; padding: 0; margin: .35rem 0 0; display: flex; flex-wrap: wrap; gap: .5rem 1rem; }}
    li {{ white-space: nowrap; }} li span {{ color: #a33b18; font-weight: 700; }} a {{ color: #0d5f77; }} header a {{ color: #fff; }} footer {{ color: #5c5d61; font-size: .9rem; }}
  </style>
</head>
<body>
  <header><h1>Schauburg – Originalfassungen</h1><p>OV and subtitled screenings at Schauburg Karlsruhe.</p></header>
  <main>
    <p>Showing {start_date.strftime("%d.%m.%Y")} to {end_date.strftime("%d.%m.%Y")}. Last updated <time datetime="{updated_at.isoformat()}">{updated}</time>.</p>
    {content}
  </main>
  <footer><p>Schedule information may change. Please <a href="https://www.schauburg.de/spielplan" aria-label="Open the official Schauburg schedule">verify details with Schauburg</a> before attending.</p></footer>
</body>
</html>
'''

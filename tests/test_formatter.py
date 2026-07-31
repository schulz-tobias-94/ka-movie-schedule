from datetime import date, datetime, time
import json
from bs4 import BeautifulSoup

from schauburg_schedule.formatter import format_html, format_json, format_text
from schauburg_schedule.models import CinemaResult, Screening


def screening(day, clock, title, label, movie_url=None):
    return Screening("schauburg", "Schauburg Karlsruhe", day, clock, title, label, movie_url=movie_url)


def cinema_result(cinema_id, cinema_name, items=(), *, success=True, fresh=True, error=None):
    return CinemaResult(cinema_id, cinema_name, tuple(items), datetime(2026, 7, 31, 13, 40), success, error, fresh)


def html(results, **kwargs):
    return format_html(results, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7), updated_at=datetime(2026, 7, 31, 13, 45), **kwargs)


def test_text_is_grouped_by_date_and_movie():
    items = [
        screening(date(2026, 7, 31), time(16, 30), "Alpha", "OV"),
        screening(date(2026, 7, 31), time(19), "Alpha", "OV"),
        screening(date(2026, 8, 1), time(20, 45), "Beta", "OmU"),
    ]
    output = format_text(items)
    assert "31.07.26  Friday" in output
    assert "16:30:00" in output and "19:00:00" in output
    assert "01.08.26  Saturday" in output


def test_json_output_is_structured():
    output = json.loads(format_json([screening(date(2026, 7, 31), time(16, 30), "Alpha", "OV", "https://example.test/a")]))
    assert output == [{"date": "2026-07-31", "time": "16:30:00", "title": "Alpha", "version_label": "OV", "movie_url": "https://example.test/a"}]


def test_html_tabs_grouping_links_and_escaping():
    movie = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(16, 30), 'Mädchen < & "Film"', "OmU", "English", "German", "Saal 4", "https://example.test/a?x=1&y=2", "https://tickets.example/a")
    later = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(19), 'Mädchen < & "Film"', "OV")
    output = html([
        cinema_result("schauburg", "Schauburg Karlsruhe", [later, movie]),
        cinema_result("filmpalast", "Filmpalast am ZKM"),
        cinema_result("universum", "Universum City Kinos Karlsruhe"),
    ])
    soup = BeautifulSoup(output, "html.parser")
    assert output.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in output
    assert soup.html["lang"] == "de"
    assert len(soup.select('[role="tab"]')) == 3
    for cinema_id in ("schauburg", "filmpalast", "universum"):
        tab, panel = soup.select_one(f"#tab-{cinema_id}"), soup.select_one(f"#panel-{cinema_id}")
        assert tab["aria-controls"] == panel["id"] and panel["aria-labelledby"] == tab["id"]
    assert soup.select_one("#tab-schauburg")["aria-selected"] == "true"
    assert "Mädchen &lt; &amp; &quot;Film&quot;" in output
    assert "https://example.test/a?x=1&amp;y=2" in output
    assert output.count('<article class="movie">') == 1
    assert "16:30" in output and "19:00" in output
    assert "OmU · Englisch · Deutsche Untertitel · Saal 4" in output
    assert ">Tickets<" in output
    assert "Schauburg Karlsruhe: Mädchen" not in output
    assert "location.hash" in output and "localStorage" in output


def test_html_statuses_empty_results_safe_urls_and_custom_title():
    unsafe = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 30), time(18), "Past", "OV", movie_url="javascript:bad", booking_url="data:text/plain,bad")
    output = html([
        cinema_result("schauburg", "Schauburg Karlsruhe", [unsafe], fresh=False),
        cinema_result("filmpalast", "Filmpalast am ZKM", success=False, error="/tmp/secret token"),
        cinema_result("universum", "Universum City Kinos Karlsruhe"),
    ], site_title='Titel < & "')
    assert "Titel &lt; &amp; &quot;" in output
    assert "letzte erfolgreiche Stand" in output
    assert "Der Spielplan konnte derzeit nicht geladen werden und" in output
    assert "Für diesen Zeitraum wurden keine passenden" in output
    assert "javascript:bad" not in output and "data:text/plain" not in output
    assert "Past" not in output


def test_html_two_failed_sources_keeps_the_successful_panel():
    movie = Screening("universum", "Universum City Kinos Karlsruhe", date(2026, 7, 31), time(20), "Film", "OmU", "Spanish", "German")
    output = html([
        cinema_result("schauburg", "Schauburg Karlsruhe", success=False),
        cinema_result("filmpalast", "Filmpalast am ZKM", success=False),
        cinema_result("universum", "Universum City Kinos Karlsruhe", [movie]),
    ])
    assert output.count("Der Spielplan konnte derzeit nicht geladen werden und") == 2
    assert "Film" in output and "OmU · Spanisch · Deutsche Untertitel" in output

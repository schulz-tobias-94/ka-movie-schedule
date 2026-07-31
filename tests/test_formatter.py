from datetime import date, datetime, time
import json

from schauburg_schedule.formatter import format_html, format_json, format_text
from schauburg_schedule.models import Screening


def test_text_is_grouped_by_date_and_movie():
    items = [
        Screening(date(2026, 7, 31), time(16, 30), "Alpha", "OV"),
        Screening(date(2026, 7, 31), time(19), "Alpha", "OV"),
        Screening(date(2026, 8, 1), time(20, 45), "Beta", "OmU"),
    ]
    output = format_text(items)
    assert "31.07.26  Friday" in output
    assert "16:30:00" in output and "19:00:00" in output
    assert "01.08.26  Saturday" in output


def test_json_output_is_structured():
    output = json.loads(format_json([Screening(date(2026, 7, 31), time(16, 30), "Alpha", "OV", "https://example.test/a")]))
    assert output == [{"date": "2026-07-31", "time": "16:30:00", "title": "Alpha", "version_label": "OV", "movie_url": "https://example.test/a"}]


def test_html_is_standalone_escaped_and_grouped():
    items = [
        Screening(date(2026, 7, 31), time(16, 30), 'Mädchen < & "Film"', "OmU", "https://example.test/a?x=1&y=2"),
        Screening(date(2026, 7, 31), time(19), 'Mädchen < & "Film"', "OV"),
    ]
    output = format_html(items, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7), updated_at=datetime(2026, 7, 31, 12, tzinfo=None))
    assert output.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in output
    assert "<header>" in output and "<main>" in output and "<section>" in output and "<article>" in output and "<footer>" in output
    assert "Mädchen &lt; &amp; &quot;Film&quot;" in output
    assert "https://example.test/a?x=1&amp;y=2" in output
    assert output.count("<article>") == 1
    assert "16:30" in output and "19:00" in output


def test_html_handles_missing_urls_empty_results_and_past_entries():
    output = format_html(
        [Screening(date(2026, 7, 30), time(18), "Past", "OV")],
        start_date=date(2026, 7, 31), end_date=date(2026, 8, 7), updated_at=datetime(2026, 7, 31, 12),
    )
    assert "No matching original-language screenings" in output
    assert "Past" not in output

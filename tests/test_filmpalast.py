from datetime import date
from pathlib import Path

import pytest

from schauburg_schedule.sources.filmpalast import FilmpalastParseError, parse_language_label, parse_weekly_schedule
from schauburg_schedule.formatter import format_html, format_json, format_text
from schauburg_schedule.snapshots import deserialize_snapshot, serialize_snapshot
from schauburg_schedule.models import CinemaResult, Screening
from datetime import datetime, time
import json

FIXTURE = Path(__file__).parent / "fixtures" / "filmpalast-week.html"


@pytest.mark.parametrize("label, expected", [
    (" OV ", (None, None, True)),
    ("OmU", (None, None, True)),
    ("englisch mit deutschen Untertiteln", ("English", "German", True)),
    ("koreanisch mit Untertiteln", ("Korean", None, True)),
    ("Tamil mit englischen Untertiteln", ("Tamil", "English", True)),
    ("Deutsch", (None, None, False)),
    ("Tuerkisch", ("Turkish", None, True)),
])
def test_language_labels(label, expected):
    assert parse_language_label(label) == expected


def test_parses_weekly_program_filters_and_normalizes_fields():
    screenings, parsed = parse_weekly_schedule(FIXTURE.read_text(), today=date(2026, 12, 30), days=4)
    assert parsed == 6
    assert [(item.date, item.time, item.movie_title) for item in screenings] == [
        (date(2026, 12, 30), screenings[0].time, "The Sample"),
        (date(2026, 12, 31), screenings[1].time, "Korean Film"),
        (date(2027, 1, 1), screenings[2].time, "Tamil Film"),
    ]
    english, korean, tamil = screenings
    assert (english.original_language, english.subtitle_language, english.auditorium) == ("English", "German", "Kino 7")
    assert english.movie_url.endswith("the-sample-ov") and english.booking_url == "https://tickets.example/english"
    assert english.format_label == "englisch mit deutschen Untertiteln · OV"
    assert korean.format_label == "OmU · koreanisch mit Untertiteln"
    assert (korean.original_language, korean.subtitle_language) == ("Korean", None)
    assert (tamil.original_language, tamil.subtitle_language) == ("Tamil", "English")


def test_days_trim_fewer_available_days_and_empty_or_changed_programs():
    fixture = FIXTURE.read_text()
    assert len(parse_weekly_schedule(fixture, today=date(2026, 12, 30), days=1)[0]) == 1
    assert len(parse_weekly_schedule(fixture, today=date(2026, 12, 30), days=14)[0]) == 3
    assert parse_weekly_schedule('<script>var pmkinoFrontVars = {"apiData":{"movies":{"items":{}},"performances":{"items":{}}}};\n//# sourceURL</script>', today=date(2026, 12, 30), days=8) == ([], 0)
    with pytest.raises(FilmpalastParseError):
        parse_weekly_schedule("<html></html>", today=date(2026, 12, 30), days=8)


def test_filmpalast_output_and_snapshot_keep_language_metadata():
    item = Screening("filmpalast", "Filmpalast am ZKM", date(2026, 7, 31), time(18, 30), "Film", "englisch mit deutschen Untertiteln", "English", "German")
    assert "englisch mit deutschen Untertiteln" in format_text([item])
    assert json.loads(format_json([item]))[0]["subtitle_language"] == "German"
    result = CinemaResult("filmpalast", "Filmpalast am ZKM", (item,), datetime(2026, 7, 31, 12), True)
    assert "englisch mit deutschen Untertiteln" in format_html([result], start_date=item.date, end_date=item.date, updated_at=datetime(2026, 7, 31, 12))
    escaped = Screening("filmpalast", "Filmpalast am ZKM", item.date, item.time, "Film", 'English < & "subtitles"')
    escaped_result = CinemaResult("filmpalast", "Filmpalast am ZKM", (escaped,), datetime(2026, 7, 31, 12), True)
    assert "English &lt; &amp; &quot;subtitles&quot;" in format_html([escaped_result], start_date=item.date, end_date=item.date, updated_at=datetime(2026, 7, 31, 12))
    restored = deserialize_snapshot(serialize_snapshot(CinemaResult("filmpalast", "Filmpalast am ZKM", (item,), datetime(2026, 7, 31, 12), True)))
    assert restored.screenings[0].original_language == "English"

from datetime import date, datetime
from pathlib import Path

import pytest

from schauburg_schedule.models import CinemaResult
from schauburg_schedule.snapshots import deserialize_snapshot, serialize_snapshot
from schauburg_schedule.sources.universum import UniversumError, _title, parse_program

FIXTURE = Path(__file__).parent / "fixtures" / "universum-program.html"


def test_parses_overview_metadata_prefixes_urls_and_year_transition():
    items, parsed = parse_program(FIXTURE.read_text(), today=date(2026, 12, 30), days=3)
    assert parsed == 3 and len(items) == 2
    spanish, english = items
    assert (spanish.date, spanish.original_language, spanish.subtitle_language) == (date(2026, 12, 30), "Spanish", "German")
    assert (spanish.auditorium, spanish.dimension, spanish.technology) == ("Universum 2", "2D", "D-BOX")
    assert spanish.movie_url.endswith("/de/programm/1") and spanish.booking_url == "https://tickets.example/1"
    assert spanish.screening_url.endswith("/de/programm/1/101")
    assert (english.movie_title, english.format_label, english.original_language) == ("Film Two", "OmU", "English")
    assert english.booking_url == "https://www.universum-city.de/booking/2"


def test_days_trim_empty_and_changed_pages():
    html = FIXTURE.read_text()
    assert len(parse_program(html, today=date(2026, 12, 30), days=1)[0]) == 1
    with pytest.raises(UniversumError):
        parse_program("<html></html>", today=date(2026, 12, 30), days=8)
    assert parse_program("<html>keine Vorstellungen</html>", today=date(2026, 12, 30), days=8) == ([], 0)


def test_title_prefix_cleanup_keeps_the_explicit_metadata_authoritative():
    assert _title("(2D engl.OV) Spider-Man (auch in D-BOX)") == ("Spider-Man", "OV")


def test_universum_snapshot_retains_extended_metadata():
    item = parse_program(FIXTURE.read_text(), today=date(2026, 12, 30), days=3)[0][0]
    restored = deserialize_snapshot(serialize_snapshot(CinemaResult("universum", "Universum City Kinos Karlsruhe", (item,), datetime(2026, 12, 30, 12), True)))
    assert (restored.screenings[0].dimension, restored.screenings[0].technology) == ("2D", "D-BOX")

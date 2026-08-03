from datetime import date, time
from pathlib import Path

import pytest

from schauburg_schedule.sources.schauburg import ScheduleParseError, parse_schedule

FIXTURE = Path(__file__).parent / "fixtures" / "schedule.html"


def test_parses_live_page_fixture_per_screening():
    screenings = parse_schedule(FIXTURE.read_text())

    assert len({item.date for item in screenings}) >= 3
    assert all(item.cinema_id == "schauburg" for item in screenings)
    assert any(item.format_label == "OV" for item in screenings)
    assert any(item.format_label == "OmU" for item in screenings)
    assert not any(item.format_label == "DE" for item in screenings)
    assert all(item.movie_url and item.movie_url.startswith("https://www.schauburg.de/") for item in screenings)


def test_sorts_and_deduplicates():
    html = """
    <input class="selectedDate" value="2026-07-31">
    <div class="row mb-lg-5 mb-3"><div class="schauburg-previewelement-date d-lg-flex">Fr <span class="number">31</span> Jul</div>
      <div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">17.00</div><a class="schauburg-previewelement-title-link" href="/film/z"><div class="schauburg-previewelement-title">Zulu</div><div class="schauburg-previewelement-category"><span>OV</span></div></a></div>
      <div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">21.00</div><a class="schauburg-previewelement-title-link" href="/film/z"><div class="schauburg-previewelement-title">Zulu</div><div class="schauburg-previewelement-category"><span>DE</span></div></a></div>
      <div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">18.00</div><a class="schauburg-previewelement-title-link" href="/film/a"><div class="schauburg-previewelement-title">Alpha</div><div class="schauburg-previewelement-category"><span>OmU</span></div></a></div>
      <div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">17.00</div><a class="schauburg-previewelement-title-link" href="/film/z"><div class="schauburg-previewelement-title">Zulu</div><div class="schauburg-previewelement-category"><span>OV</span></div></a></div>
    </div>"""
    assert parse_schedule(html) == [
        parse_schedule(html)[0], parse_schedule(html)[1]
    ]
    assert [(item.movie_title, item.time) for item in parse_schedule(html)] == [("Zulu", time(17)), ("Alpha", time(18))]


def test_parses_new_year_from_german_month_labels():
    html = """
    <input class="selectedDate" value="2026-12-30">
    <div class="row mb-lg-5 mb-3"><div class="schauburg-previewelement-date d-lg-flex">Mi <span class="number">30</span> Dez</div><div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">19.00</div><a class="schauburg-previewelement-title-link"><div class="schauburg-previewelement-title">One</div><div class="schauburg-previewelement-category"><span>OV</span></div></a></div></div>
    <div class="row mb-lg-5 mb-3"><div class="schauburg-previewelement-date d-lg-flex">Sa <span class="number">02</span> Jan</div><div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">20:00</div><a class="schauburg-previewelement-title-link"><div class="schauburg-previewelement-title">Two</div><div class="schauburg-previewelement-category"><span>OmeU</span></div></a></div></div>"""
    assert [item.date for item in parse_schedule(html)] == [date(2026, 12, 30), date(2027, 1, 2)]


@pytest.mark.parametrize("html", ["", '<input class="selectedDate" value="2026-07-31">', '<input class="selectedDate" value="oops"><div class="row mb-lg-5 mb-3"></div>'])
def test_rejects_empty_or_structurally_changed_html(html):
    with pytest.raises(ScheduleParseError):
        parse_schedule(html)


def test_skips_malformed_entries_without_losing_valid_screenings():
    html = """
    <input class="selectedDate" value="2026-07-31"><div class="row mb-lg-5 mb-3"><div class="schauburg-previewelement-date d-lg-flex">Fr <span class="number">31</span> Jul</div>
    <div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">bad</div><a class="schauburg-previewelement-title-link"><div class="schauburg-previewelement-title">Broken</div><div class="schauburg-previewelement-category"><span>OV</span></div></a></div>
    <div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">18.00</div><a class="schauburg-previewelement-title-link"><div class="schauburg-previewelement-title">Good</div><div class="schauburg-previewelement-category"><span>OV</span></div></a></div></div>"""
    assert [item.movie_title for item in parse_schedule(html)] == ["Good"]


def test_parses_explicit_schedule_runtime():
    html = """<input class="selectedDate" value="2026-07-31"><div class="row mb-lg-5 mb-3"><div class="schauburg-previewelement-date d-lg-flex">Fr <span>31</span> Jul</div><div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">18.00</div><a class="schauburg-previewelement-title-link"><div class="schauburg-previewelement-title">Film</div><div class="schauburg-previewelement-category"><span>OV</span></div></a><span>107 MIN | FSK 12</span></div></div>"""
    assert parse_schedule(html)[0].runtime_minutes == 107


@pytest.mark.parametrize(("label", "expected"), [("1 Std 42 Min", 102), ("2 Std", 120), ("110 Minuten", 110)])
def test_runtime_parser_accepts_explicit_german_forms(label, expected):
    html = f'''<input class="selectedDate" value="2026-07-31"><div class="row mb-lg-5 mb-3"><div class="schauburg-previewelement-date d-lg-flex">Fr <span>31</span> Jul</div><div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">18.00</div><a class="schauburg-previewelement-title-link"><div class="schauburg-previewelement-title">Film</div><div class="schauburg-previewelement-category"><span>OV</span></div></a><span>{label}</span></div></div>'''
    assert parse_schedule(html)[0].runtime_minutes == expected

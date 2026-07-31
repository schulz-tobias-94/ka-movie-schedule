from datetime import date

from schauburg_schedule.sources import schauburg as fetcher
from schauburg_schedule.sources.schauburg import parse_schedule


def page(day, *, month="Jul", title="Film", next_url=None, selected=None):
    selected_input = f'<input class="selectedDate" value="{selected}">' if selected else ""
    load_more = f'<a class="load-more" data-ajax-url="{next_url}">mehr laden</a>' if next_url else ""
    return f'''{selected_input}<div class="row"><div class="col-lg-2"><div class="schauburg-previewelement-date d-lg-flex">Fr <span>{day:02}</span> {month}</div></div><div class="collapse"><div class="row schauburg-previewelement"><div class="d-none d-lg-flex schauburg-previewelement-time">18:00</div><a class="schauburg-previewelement-title-link" href="/film/{title}"><div class="schauburg-previewelement-title">{title}</div><div class="schauburg-previewelement-category"><span>OV</span></div></a></div></div></div>{load_more}'''


class Response:
    def __init__(self, text, url):
        self.text, self.content, self.url = text, text.encode(), url

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, initial, first, pages):
        self.headers = {}
        self.initial, self.first, self.pages = initial, first, pages
        self.get_urls = []

    def get(self, url, timeout):
        self.get_urls.append(url)
        if url.endswith("/spielplan"):
            return Response(self.initial, url)
        return Response(self.pages[url], url)

    def post(self, url, data, timeout):
        return Response(self.first, url)


def install_session(monkeypatch, first, pages):
    initial = '''<form action="/spielplan/filter"><input type="hidden" name="token" value="x"><button name="filter" value="all">Alles ab heute</button></form>'''
    session = Session(initial, first, pages)
    monkeypatch.setattr(fetcher.requests, "Session", lambda: session)
    return session


def test_loads_batches_until_after_requested_date_and_keeps_final_day(monkeypatch):
    first = page(31, title="One", next_url="/more/2", selected="2026-07-31")
    second = page(3, month="Aug", title="Two", next_url="/more/3")
    third = page(7, month="Aug", title="Final") + page(8, month="Aug", title="Later")
    session = install_session(monkeypatch, first, {"https://www.schauburg.de/more/2": second, "https://www.schauburg.de/more/3": third})

    screenings = parse_schedule(fetcher.fetch_schedule_html(days=8, use_cache=False, today=date(2026, 7, 31)))

    assert len(session.get_urls) == 3  # Initial request plus two load-more batches.
    assert any(item.movie_title == "Final" and item.date == date(2026, 8, 7) for item in screenings)
    assert [item.movie_title for item in screenings if item.date <= date(2026, 8, 7)] == ["One", "Two", "Final"]


def test_stops_for_no_results_empty_or_repeated_batches(monkeypatch):
    no_more = page(31, title="One", selected="2026-07-31")
    session = install_session(monkeypatch, no_more, {})
    assert len(parse_schedule(fetcher.fetch_schedule_html(days=8, use_cache=False, today=date(2026, 7, 31)))) == 1
    assert len(session.get_urls) == 1

    first = page(31, title="One", next_url="/more/2", selected="2026-07-31")
    session = install_session(monkeypatch, first, {"https://www.schauburg.de/more/2": ""})
    assert len(parse_schedule(fetcher.fetch_schedule_html(days=8, use_cache=False, today=date(2026, 7, 31)))) == 1
    assert len(session.get_urls) == 2

    session = install_session(monkeypatch, first, {"https://www.schauburg.de/more/2": first})
    assert len(parse_schedule(fetcher.fetch_schedule_html(days=8, use_cache=False, today=date(2026, 7, 31)))) == 1
    assert len(session.get_urls) == 2


def test_deduplicates_across_batches_and_honors_safety_limit(monkeypatch):
    first = page(31, title="One", next_url="/more/2", selected="2026-07-31")
    second = page(31, title="One") + page(2, month="Aug", title="Two", next_url="/more/3")
    third = page(3, month="Aug", title="Three", next_url="/more/4")
    fourth = page(4, month="Aug", title="Four", next_url="/more/5")
    session = install_session(monkeypatch, first, {"https://www.schauburg.de/more/2": second, "https://www.schauburg.de/more/3": third, "https://www.schauburg.de/more/4": fourth})
    monkeypatch.setattr(fetcher, "MAX_LOAD_REQUESTS", 2)

    screenings = parse_schedule(fetcher.fetch_schedule_html(days=14, use_cache=False, today=date(2026, 7, 31)))

    assert [item.movie_title for item in screenings] == ["One", "Two", "Three"]
    assert len(session.get_urls) == 3

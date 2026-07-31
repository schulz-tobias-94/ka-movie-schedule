from datetime import date, time

from schauburg_schedule.coordinator import collect_screenings, successful_screenings
from schauburg_schedule.models import Screening
from schauburg_schedule.sources.base import CinemaSource, SourceError


class FakeSource(CinemaSource):
    def __init__(self, cinema_id, failure=None):
        self.cinema_id, self.cinema_name, self.failure = cinema_id, cinema_id.title(), failure

    def fetch(self, *, days, today, use_cache):
        if self.failure:
            raise SourceError(self.failure)
        return [Screening(self.cinema_id, self.cinema_name, today, time(19), "Film", "OV")]


def test_one_source_failure_does_not_stop_another_source():
    results = collect_screenings(
        [FakeSource("filmpalast", "network failed"), FakeSource("schauburg")],
        days=8, today=date(2026, 7, 31), use_cache=False,
    )
    assert [(item.cinema_id, item.success, item.error) for item in results] == [
        ("filmpalast", False, "network failed"), ("schauburg", True, None),
    ]
    assert [item.cinema_id for item in successful_screenings(results)] == ["schauburg"]


def test_multiple_source_failures_preserve_each_successful_cinema():
    results = collect_screenings(
        [FakeSource("schauburg", "offline"), FakeSource("filmpalast"), FakeSource("universum", "bad response")],
        days=8, today=date(2026, 7, 31), use_cache=False,
    )
    assert [(item.cinema_id, item.success, item.error) for item in results] == [
        ("schauburg", False, "offline"), ("filmpalast", True, None), ("universum", False, "bad response"),
    ]
    assert [item.cinema_id for item in successful_screenings(results)] == ["filmpalast"]

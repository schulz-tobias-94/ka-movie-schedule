from datetime import date, datetime, time, timedelta
import json

from schauburg_schedule import cli
from schauburg_schedule.models import CinemaResult, Screening


def screening(day, clock, title, label):
    return Screening("schauburg", "Schauburg Karlsruhe", day, clock, title, label)


def result(items):
    return [CinemaResult("schauburg", "Schauburg Karlsruhe", tuple(items), datetime(2026, 7, 31, 12), True)]


def test_default_eight_day_range_and_days_one(monkeypatch, capsys, tmp_path):
    calls = []
    items = [screening(date.today(), time(18), "Today", "OV"), screening(date.today() + timedelta(days=8), time(20), "Later", "OV")]
    monkeypatch.setattr(cli, "select_sources", lambda ids: [object()])
    monkeypatch.setattr(cli, "collect_screenings", lambda sources, **kwargs: calls.append(kwargs) or result(items))
    monkeypatch.setattr(cli, "today_in_berlin", lambda: date.today())

    assert cli.main(["--json", "--no-cache", "--snapshot-dir", str(tmp_path)]) == 0
    assert calls[-1]["days"] == 8
    assert [item["title"] for item in json.loads(capsys.readouterr().out)] == ["Today"]
    assert cli.main(["--days", "1", "--json", "--snapshot-dir", str(tmp_path)]) == 0
    assert calls[-1]["days"] == 1


def test_range_filter_crosses_year(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "select_sources", lambda ids: [object()])
    monkeypatch.setattr(cli, "collect_screenings", lambda sources, **kwargs: result([screening(date(2027, 1, 1), time(18), "New year", "OV")]))
    monkeypatch.setattr(cli, "today_in_berlin", lambda: date(2026, 12, 31))

    assert cli.main(["--days", "2", "--json", "--snapshot-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["date"] == "2027-01-01"


def test_html_creates_output_directory_and_uses_berlin_today(monkeypatch, tmp_path):
    requested_today = date(2026, 7, 31)
    calls = []
    monkeypatch.setattr(cli, "today_in_berlin", lambda: requested_today)
    monkeypatch.setattr(cli, "select_sources", lambda ids: [object()])
    monkeypatch.setattr(cli, "resolve_imdb_matches", lambda screenings: {})
    monkeypatch.setattr(cli, "collect_screenings", lambda sources, **kwargs: calls.append(kwargs) or result([
        screening(requested_today - timedelta(days=1), time(18), "Past", "OV"),
        screening(requested_today, time(19), "Heute", "OV"),
    ]))
    target = tmp_path / "site" / "index.html"

    assert cli.main(["--html", "--output", str(target), "--snapshot-dir", str(tmp_path / "snapshots")]) == 0
    assert calls[-1]["today"] == requested_today
    output = target.read_text(encoding="utf-8")
    assert "Heute" in output and "Past" not in output


def test_today_in_berlin_uses_the_berlin_timezone(monkeypatch):
    class FixedDateTime:
        @staticmethod
        def now(zone):
            assert zone.key == "Europe/Berlin"
            return datetime(2026, 7, 31, 0, 30)

    monkeypatch.setattr(cli, "datetime", FixedDateTime)
    assert cli.today_in_berlin() == date(2026, 7, 31)


def test_unknown_and_unimplemented_cinemas_are_clear_errors(capsys):
    assert cli.main(["--cinema", "nope"]) == 2
    assert "Unknown cinema identifier" in capsys.readouterr().err


def test_all_unavailable_sources_return_nonzero(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "select_sources", lambda ids: [object()])
    monkeypatch.setattr(cli, "collect_screenings", lambda *args, **kwargs: [CinemaResult("schauburg", "Schauburg Karlsruhe", (), datetime(2026, 7, 31, 12), False, "offline", False)])
    assert cli.main(["--html", "--output", str(tmp_path / "site" / "index.html"), "--snapshot-dir", str(tmp_path / "snapshots")]) == 1

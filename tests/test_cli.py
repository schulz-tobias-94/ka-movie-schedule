from datetime import date, datetime, time, timedelta
import json

from schauburg_schedule import cli
from schauburg_schedule.models import Screening


def test_default_eight_day_range_and_days_one(monkeypatch, capsys):
    calls = []
    items = [Screening(date.today(), time(18), "Today", "OV"), Screening(date.today() + timedelta(days=8), time(20), "Later", "OV")]
    monkeypatch.setattr(cli, "fetch_schedule_html", lambda **kwargs: calls.append(kwargs) or "html")
    monkeypatch.setattr(cli, "parse_schedule", lambda html: items)
    monkeypatch.setattr(cli, "today_in_berlin", lambda: date.today())

    assert cli.main(["--json", "--no-cache"]) == 0
    assert calls[-1]["days"] == 8
    assert [item["title"] for item in json.loads(capsys.readouterr().out)] == ["Today"]
    assert cli.main(["--days", "1", "--json"]) == 0
    assert calls[-1]["days"] == 1


def test_range_filter_crosses_year(monkeypatch, capsys):
    monkeypatch.setattr(cli, "fetch_schedule_html", lambda **kwargs: "html")
    monkeypatch.setattr(cli, "parse_schedule", lambda html: [Screening(date(2027, 1, 1), time(18), "New year", "OV")])
    monkeypatch.setattr(cli, "today_in_berlin", lambda: date(2026, 12, 31))

    assert cli.main(["--days", "2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["date"] == "2027-01-01"


def test_html_creates_output_directory_and_uses_berlin_today(monkeypatch, tmp_path):
    requested_today = date(2026, 7, 31)
    calls = []
    monkeypatch.setattr(cli, "today_in_berlin", lambda: requested_today)
    monkeypatch.setattr(cli, "fetch_schedule_html", lambda **kwargs: calls.append(kwargs) or "html")
    monkeypatch.setattr(cli, "parse_schedule", lambda html: [
        Screening(requested_today - timedelta(days=1), time(18), "Past", "OV"),
        Screening(requested_today, time(19), "Heute", "OV"),
    ])
    target = tmp_path / "site" / "index.html"

    assert cli.main(["--html", "--output", str(target)]) == 0
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

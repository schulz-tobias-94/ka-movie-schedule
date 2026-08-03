from datetime import date, datetime, time

import pytest

from schauburg_schedule.models import CinemaResult, Screening
from schauburg_schedule.coordinator import persist_and_restore_snapshots
from schauburg_schedule.snapshots import MAX_SNAPSHOT_BYTES, SnapshotError, deserialize_snapshot, load_snapshot, serialize_snapshot, write_snapshot


def test_snapshot_round_trip_is_deterministic_utf8_json():
    result = CinemaResult(
        "schauburg", "Schauburg Karlsruhe",
        (Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(19), "Chéri", "OmU"),),
        datetime(2026, 7, 31, 12), True,
    )
    serialized = serialize_snapshot(result)
    assert "Chéri" in serialized
    assert serialize_snapshot(deserialize_snapshot(serialized)) == serialized


def test_snapshot_round_trip_preserves_optional_movie_metadata():
    item = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 8, 3), time(20), "Film", "OV", release_year=2026, runtime_minutes=107, director_names=("Jane Doe",), original_title="Original", alternate_titles=("Alternative",), production_countries=("Germany",))
    restored = deserialize_snapshot(serialize_snapshot(CinemaResult("schauburg", "Schauburg Karlsruhe", (item,), datetime(2026, 8, 3, 12), True)))
    assert restored.screenings[0] == item


@pytest.mark.parametrize("snapshot", ["not json", '{"schema_version": 2}', '{"schema_version": 1, "cinema": {}}'])
def test_malformed_or_incompatible_snapshots_are_rejected(snapshot):
    with pytest.raises(SnapshotError):
        deserialize_snapshot(snapshot)


def fresh_result(day=date(2026, 7, 31)):
    return CinemaResult("schauburg", "Schauburg Karlsruhe", (Screening("schauburg", "Schauburg Karlsruhe", day, time(19), "Film", "OV", movie_url="https://example.test/film"),), datetime(2026, 7, 31, 12), True)


def test_snapshot_write_is_atomic_and_restoration_trims_past_and_range(tmp_path):
    result = CinemaResult("schauburg", "Schauburg Karlsruhe", (
        fresh_result(date(2026, 7, 30)).screenings[0], fresh_result(date(2026, 8, 1)).screenings[0], fresh_result(date(2026, 8, 9)).screenings[0],
    ), datetime(2026, 7, 31, 12), True)
    write_snapshot(result, tmp_path, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7))
    restored = load_snapshot(tmp_path, cinema_id="schauburg", cinema_name="Schauburg Karlsruhe", today=date(2026, 7, 31), end_date=date(2026, 8, 7))
    assert [item.date for item in restored.screenings] == [date(2026, 8, 1)]
    assert restored.state == "restored" and not list(tmp_path.glob("*.tmp"))


def test_invalid_identity_past_and_oversized_snapshots_are_rejected(tmp_path):
    write_snapshot(fresh_result(date(2026, 7, 30)), tmp_path, start_date=date(2026, 7, 30), end_date=date(2026, 7, 30))
    with pytest.raises(SnapshotError):
        load_snapshot(tmp_path, cinema_id="schauburg", cinema_name="Schauburg Karlsruhe", today=date(2026, 7, 31), end_date=date(2026, 8, 7))
    write_snapshot(fresh_result(), tmp_path, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7))
    with pytest.raises(SnapshotError):
        load_snapshot(tmp_path, cinema_id="schauburg", cinema_name="Wrong", today=date(2026, 7, 31), end_date=date(2026, 8, 7))
    (tmp_path / "schauburg.json").write_bytes(b"x" * (MAX_SNAPSHOT_BYTES + 1))
    with pytest.raises(SnapshotError):
        load_snapshot(tmp_path, cinema_id="schauburg", cinema_name="Schauburg Karlsruhe", today=date(2026, 7, 31), end_date=date(2026, 8, 7))


def test_failed_source_restores_but_successful_empty_result_does_not(tmp_path):
    write_snapshot(fresh_result(), tmp_path, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7))
    failed = CinemaResult("schauburg", "Schauburg Karlsruhe", (), datetime(2026, 7, 31, 13), False, "timeout", False)
    restored = persist_and_restore_snapshots([failed], directory=tmp_path, today=date(2026, 7, 31), end_date=date(2026, 8, 7), fallback=True)[0]
    assert restored.state == "restored" and restored.error == "timeout" and restored.screenings[0].movie_url == "https://example.test/film"
    empty = CinemaResult("schauburg", "Schauburg Karlsruhe", (), datetime(2026, 7, 31, 14), True)
    result = persist_and_restore_snapshots([empty], directory=tmp_path, today=date(2026, 7, 31), end_date=date(2026, 8, 7), fallback=True)[0]
    assert result.state == "success_empty" and not result.screenings


def test_corrupted_snapshot_does_not_prevent_another_cinema_restoring(tmp_path):
    filmpalast = CinemaResult("filmpalast", "Filmpalast am ZKM", (Screening("filmpalast", "Filmpalast am ZKM", date(2026, 8, 1), time(20), "Film", "OV"),), datetime(2026, 7, 31, 12), True)
    write_snapshot(filmpalast, tmp_path, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7))
    (tmp_path / "schauburg.json").write_text("broken", encoding="utf-8")
    failed = [
        CinemaResult("schauburg", "Schauburg Karlsruhe", (), datetime(2026, 7, 31, 13), False),
        CinemaResult("filmpalast", "Filmpalast am ZKM", (), datetime(2026, 7, 31, 13), False),
    ]
    results = persist_and_restore_snapshots(failed, directory=tmp_path, today=date(2026, 7, 31), end_date=date(2026, 8, 7), fallback=True)
    assert [item.state for item in results] == ["failed", "restored"]

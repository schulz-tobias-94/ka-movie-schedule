from datetime import UTC, date, datetime, time
from pathlib import Path
import json

import requests
import pytest

from schauburg_schedule.enrichment.imdb import ImdbMatch, OverrideError, _Evidence, _evidence, _load_cache, _load_overrides, _title_match, imdb_search_url, resolve_imdb_matches
from schauburg_schedule.enrichment.title_normalization import clean_title, lookup_candidates, movie_key
from schauburg_schedule.models import Screening


def film(title, cinema="schauburg", **metadata):
    return Screening(cinema, cinema, date(2026, 8, 3), time(20), title, "OV", **metadata)


def test_title_cleanup_and_safe_search_url_preserve_real_title_content():
    assert clean_title("(engl. OmU) Film: Part 2 (auch in D-BOX)") == "Film: Part 2"
    assert imdb_search_url('A & B') == "https://www.imdb.com/find/?q=A+%26+B&s=tt&ttype=ft"


def test_title_cleanup_removes_operational_suffixes_and_keeps_real_hyphens():
    assert clean_title("Die Odyssee 3.W") == "Die Odyssee"
    assert clean_title("Die Odyssee 3.W.") == "Die Odyssee"
    assert clean_title("Die Odyssee 3. Woche") == "Die Odyssee"
    assert clean_title("Spider-Man: Brand New Day (Ukrainische Sprachfassung)") == "Spider-Man: Brand New Day"
    assert clean_title("Film (Originalfassung)") == "Film"
    assert lookup_candidates("Tränen der Erinnerung - Only Yesterday") == ["Tränen der Erinnerung - Only Yesterday", "Tränen der Erinnerung", "Only Yesterday"]
    assert lookup_candidates("Spider-Man: Brand New Day") == ["Spider-Man: Brand New Day"]


def test_no_token_uses_one_cached_or_search_match_per_cleaned_movie(tmp_path):
    matches = resolve_imdb_matches([film("(OV) Alpha"), film("Alpha", "universum")], token=None, cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")
    assert list(matches) == [movie_key("Alpha")]
    assert matches[movie_key("Alpha")].status == "search_fallback"
    assert (tmp_path / "matches.json").is_file()


def test_manual_override_wins_and_invalid_override_is_rejected(tmp_path):
    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"alpha": {"imdb_id": "tt1234567", "canonical_title": "Alpha"}}', encoding="utf-8")
    match = resolve_imdb_matches([film("Alpha")], token=None, override_path=overrides, cache_path=tmp_path / "matches.json")["alpha"]
    assert (match.status, match.url) == ("manual", "https://www.imdb.com/title/tt1234567/")
    overrides.write_text('{"alpha": {"imdb_id": "bad"}}', encoding="utf-8")
    try:
        _load_overrides(overrides)
    except OverrideError:
        pass
    else:
        raise AssertionError("invalid override was accepted")


def test_exact_tmdb_match_uses_external_imdb_id(monkeypatch, tmp_path):
    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    class Session:
        def get(self, url, **kwargs):
            return Response({"results": [{"id": 7, "title": "Distinctive Alpha", "original_title": "Distinctive Alpha", "release_date": "2026-01-01"}]} if url.endswith("search/movie") else {"imdb_id": "tt7654321"})
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Distinctive Alpha")], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")["distinctive alpha"]
    assert match.status == "confident" and match.imdb_id == "tt7654321"


def test_provider_failure_keeps_a_search_fallback(monkeypatch, tmp_path):
    class Session:
        def get(self, *args, **kwargs):
            raise requests.Timeout("offline")
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Alpha")], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")["alpha"]
    assert match.status == "search_fallback" and match.imdb_id is None


def test_sneak_is_never_sent_to_tmdb(monkeypatch, tmp_path):
    class Session:
        def get(self, *args, **kwargs):
            raise AssertionError("generic sneak should not be resolved")
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("OV Sneak Preview")], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")[movie_key("OV Sneak Preview")]
    assert match.status == "search_fallback" and match.reason == "generic_sneak"


def test_token_free_fallback_retries_when_token_is_added(monkeypatch, tmp_path):
    resolve_imdb_matches([film("Alpha")], token=None, cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": []}
    class Session:
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Alpha")], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")["alpha"]
    assert match.reason == "no_match"


def test_year_director_and_runtime_select_the_correct_remake(monkeypatch, tmp_path):
    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    class Session:
        def get(self, url, **kwargs):
            if url.endswith("search/movie"):
                return Response({"results": [{"id": 1, "title": "The Odyssey", "original_title": "The Odyssey", "release_date": "2026-01-01"}, {"id": 2, "title": "The Odyssey", "original_title": "The Odyssey", "release_date": "1997-01-01"}]})
            if url.endswith("/movie/1"):
                return Response({"id": 1, "title": "The Odyssey", "original_title": "The Odyssey", "release_date": "2026-01-01", "runtime": 180, "credits": {"crew": [{"job": "Director", "name": "Christopher Nolan"}]}})
            if url.endswith("/movie/2"):
                return Response({"id": 2, "title": "The Odyssey", "release_date": "1997-01-01", "runtime": 176, "credits": {"crew": [{"job": "Director", "name": "Other Director"}]}})
            return Response({"imdb_id": "tt7654321"})
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    item = film("The Odyssey", release_year=2026, runtime_minutes=180, director_names=("Christopher Nolan",))
    match = resolve_imdb_matches([item], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")[movie_key("The Odyssey", 2026)]
    assert match.imdb_id == "tt7654321"
    assert {"exact year", "director match", "runtime within five"} <= set(match.matched_by)


def test_tied_exact_titles_fall_back_to_search(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": [{"id": 1, "title": "Ghost in the Shell"}, {"id": 2, "title": "Ghost in the Shell"}]}
    class Session:
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Ghost in the Shell")], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")[movie_key("Ghost in the Shell")]
    assert match.reason == "ambiguous" and match.imdb_id is None


def test_refresh_imdb_revalidates_cached_automatic_match(monkeypatch, tmp_path):
    cache = tmp_path / "matches.json"
    cache.write_text('{"alpha":{"query_title":"Alpha","imdb_id":"tt1234567","status":"confident"}}', encoding="utf-8")
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": []}
    class Session:
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Alpha")], token="secret", cache_path=cache, override_path=tmp_path / "overrides.json", refresh=True)["alpha"]
    assert match.reason == "no_match"


def test_title_only_and_year_metadata_share_one_confident_alias(monkeypatch, tmp_path):
    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    class Session:
        def get(self, url, **kwargs):
            return Response({"results": [{"id": 7, "title": "Die Odyssee", "original_title": "Die Odyssee", "release_date": "2026-01-01"}]} if url.endswith("search/movie") else {"imdb_id": "tt33764258"})
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    items = [film("Die Odyssee", "schauburg"), film("Die Odyssee", "universum", release_year=2026, runtime_minutes=172)]
    matches = resolve_imdb_matches(items, token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")
    assert matches["die odyssee"].imdb_id == matches["die odyssee|2026"].imdb_id == "tt33764258"
    assert _load_cache(tmp_path / "matches.json")["die odyssee"].resolved_via == "die odyssee|2026"


def test_conflicting_years_and_directors_remain_separate():
    year_groups = _evidence([film("The Thing", release_year=1982), film("The Thing", "universum", release_year=2011)])
    director_groups = _evidence([film("Film", director_names=("Jane Doe",)), film("Film", "universum", director_names=("John Doe",))])
    assert {item.key for item in year_groups} == {"the thing|1982", "the thing|2011"}
    assert len(director_groups) == 2 and all(item.key.startswith("film|director:") for item in director_groups)
    assert all("film" not in item.aliases for item in year_groups)


def test_close_runtimes_consolidate_but_distant_runtimes_do_not():
    close = _evidence([film("Film Title", runtime_minutes=100), film("Film Title", "universum", runtime_minutes=112)])
    distant = _evidence([film("Film Title", runtime_minutes=100), film("Film Title", "universum", runtime_minutes=145)])
    assert len(close) == 1 and close[0].runtime == 106
    assert len(distant) == 2


def test_conflicting_screening_audio_does_not_split_an_otherwise_identical_movie():
    groups = _evidence([film("Spider-Man: Brand New Day", release_year=2026, runtime_minutes=150, original_language="English"), film("Spider-Man: Brand New Day", "universum", release_year=2026, runtime_minutes=150, original_language="Ukrainian")])
    assert len(groups) == 1 and groups[0].original_language is None


def test_distinct_source_movie_urls_in_one_cinema_do_not_consolidate():
    groups = _evidence([film("Film", movie_url="https://cinema.example/one"), film("Film", movie_url="https://cinema.example/two")])
    assert len(groups) == 2 and all("film" not in item.aliases for item in groups)


def test_german_localized_title_director_and_runtime_match(monkeypatch, tmp_path, caplog):
    calls = []
    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    class Session:
        def get(self, url, **kwargs):
            calls.append((url, kwargs.get("params", {}).get("language")))
            if url.endswith("search/movie"):
                language = kwargs["params"]["language"]
                return Response({"results": [{"id": 1, "title": "Bitteres Fest" if language == "de-DE" else "Bitter Christmas", "original_title": "Bitter Christmas", "release_date": "2026-01-01"}]})
            if url.endswith("/movie/1"):
                return Response({"id": 1, "title": "Bitter Christmas", "original_title": "Bitter Christmas", "release_date": "2026-01-01", "runtime": 112, "credits": {"crew": [{"job": "Director", "name": "Pedro Almodóvar"}]}})
            if url.endswith("/translations"):
                return Response({"translations": [{"iso_639_1": "de", "data": {"title": "Bitteres Fest"}}]})
            if url.endswith("/alternative_titles"):
                return Response({"titles": []})
            return Response({"imdb_id": "tt1234567"})
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    caplog.set_level("DEBUG")
    match = resolve_imdb_matches([film("Bitteres Fest", runtime_minutes=110, director_names=("Pedro Almodóvar",))], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")["bitteres fest"]
    assert match.imdb_id == "tt1234567" and "German localized title" in match.matched_by
    assert [language for url, language in calls if url.endswith("search/movie")] == ["de-DE", "en-US"]
    assert sum(url.endswith("/movie/1") for url, _ in calls) == 1
    assert "German localized title" in caplog.text


def test_translated_and_alternate_title_variants_are_exact_evidence(monkeypatch, tmp_path):
    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    class Session:
        def get(self, url, **kwargs):
            if url.endswith("search/movie"):
                return Response({"results": [{"id": 1, "title": "English Primary", "original_title": "English Primary"}]})
            if url.endswith("/movie/1"):
                return Response({"id": 1, "title": "English Primary", "original_title": "English Primary"})
            if url.endswith("/translations"):
                return Response({"translations": [{"iso_639_1": "de", "data": {"title": "Deutscher Titel"}}]})
            if url.endswith("/alternative_titles"):
                return Response({"titles": [{"title": "Alternativer Titel"}]})
            return Response({"imdb_id": "tt1234567"})
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    for title, evidence in (("Deutscher Titel", "German localized title"), ("Alternativer Titel", "alternate title")):
        match = resolve_imdb_matches([film(title)], token="secret", cache_path=tmp_path / f"{title}.json", override_path=tmp_path / "overrides.json")[movie_key(title)]
        assert match.imdb_id == "tt1234567" and evidence in match.matched_by


def test_director_and_runtime_without_any_title_variant_stay_rejected(monkeypatch, tmp_path):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": [{"id": 1, "title": "Other Film"}]} if False else {"id": 1, "title": "Other Film", "runtime": 112, "credits": {"crew": [{"job": "Director", "name": "Pedro Almodóvar"}]}}
    class Session:
        def get(self, url, **kwargs):
            if url.endswith("search/movie"): return type("Search", (), {"raise_for_status": lambda self: None, "json": lambda self: {"results": [{"id": 1, "title": "Other Film"}]}})()
            if url.endswith("/translations"): return type("Translations", (), {"raise_for_status": lambda self: None, "json": lambda self: {"translations": []}})()
            if url.endswith("/alternative_titles"): return type("Alternatives", (), {"raise_for_status": lambda self: None, "json": lambda self: {"titles": []}})()
            return Response()
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Bitteres Fest", runtime_minutes=110, director_names=("Pedro Almodóvar",))], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")["bitteres fest"]
    assert match.reason == "no_match" and match.imdb_id is None


@pytest.mark.parametrize("provider", ["Chéri, ich komme! – Die Erfindung der Lust.", "Chéri, ich komme! - Die Erfindung der Lust", "Chéri, ich komme!: Die Erfindung der Lust"])
def test_localized_title_prefix_requires_a_separator_boundary(provider):
    evidence = _Evidence("Chéri, ich komme!", "Chéri, ich komme!", "cheri ich komme", ("Chéri, ich komme!",), None, 90, ("Reem Kherici",), None, ())
    assert _title_match({"_title_variants": ((provider, "German localized title"),)}, evidence)[1:] == ("localized title prefix", 40)


def test_short_or_non_separator_title_prefixes_remain_rejected():
    short = _Evidence("The Last", "The Last", "the last", ("The Last",), None, None, (), None, ())
    unrelated = _Evidence("The Last Voyage", "The Last Voyage", "the last voyage", ("The Last Voyage",), None, None, (), None, ())
    assert _title_match({"_title_variants": (("The Last Voyage - Extended", "German localized title"),)}, short) is None
    assert _title_match({"_title_variants": (("The Last Voyage of Summer", "German localized title"),)}, unrelated) is None


def test_localized_prefix_with_director_and_runtime_is_confident(monkeypatch, tmp_path):
    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body
    class Session:
        def get(self, url, **kwargs):
            if url.endswith("search/movie"): return Response({"results": [{"id": 1, "title": "Chéri, ich komme! – Die Erfindung der Lust.", "original_title": "Aimer, c'est facile", "release_date": "2026-01-01"}]})
            if url.endswith("/movie/1"): return Response({"id": 1, "title": "Bitter Christmas", "runtime": 92, "credits": {"crew": [{"job": "Director", "name": "Reem Kherici"}]}})
            if url.endswith("/translations"): return Response({"translations": [{"iso_639_1": "de", "data": {"title": "Chéri, ich komme! – Die Erfindung der Lust."}}]})
            if url.endswith("/alternative_titles"): return Response({"titles": []})
            return Response({"imdb_id": "tt1234567"})
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    match = resolve_imdb_matches([film("Chéri, ich komme!", runtime_minutes=90, director_names=("Reem Kherici",))], token="secret", cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")["chéri ich komme"]
    assert match.imdb_id == "tt1234567" and "localized title prefix" in match.matched_by


def test_authoritative_tmdb_title_alias_propagates_only_to_current_titles(tmp_path):
    now = datetime.now(UTC).isoformat()
    cache = tmp_path / "matches.json"
    cache.write_text(json.dumps({
        "die odyssee|2026": {"query_title": "Die Odyssee", "imdb_id": "tt33764258", "status": "confident", "verified_at": now, "authoritative_titles": ["Die Odyssee", "The Odyssey"]},
        "the odyssey": {"query_title": "The Odyssey", "imdb_id": None, "status": "search_fallback", "verified_at": now, "reason": "ambiguous"},
    }), encoding="utf-8")
    matches = resolve_imdb_matches([film("Die Odyssee", release_year=2026), film("The Odyssey", "universum")], token=None, cache_path=cache, override_path=tmp_path / "overrides.json")
    assert matches["the odyssey"].imdb_id == "tt33764258"
    assert matches["the odyssey"].resolved_via == "die odyssee|2026"
    assert matches["the odyssey"].matched_by == ("TMDb authoritative title alias",)


def test_alias_propagation_rejects_conflicting_year_or_confident_id(tmp_path):
    now = datetime.now(UTC).isoformat()
    cache = tmp_path / "matches.json"
    cache.write_text(json.dumps({
        "die odyssee|2026": {"query_title": "Die Odyssee", "imdb_id": "tt33764258", "status": "confident", "verified_at": now, "authoritative_titles": ["The Odyssey"]},
        "the odyssey|2025": {"query_title": "The Odyssey", "imdb_id": "tt9999999", "status": "confident", "verified_at": now},
    }), encoding="utf-8")
    matches = resolve_imdb_matches([film("Die Odyssee", release_year=2026), film("The Odyssey", "universum", release_year=2025)], token=None, cache_path=cache, override_path=tmp_path / "overrides.json")
    assert matches["the odyssey|2025"].imdb_id == "tt9999999"


def test_legacy_confident_cache_is_revalidated_when_a_token_can_add_aliases(monkeypatch, tmp_path):
    cache = tmp_path / "matches.json"
    cache.write_text('{"distinctive title":{"query_title":"Distinctive Title","imdb_id":"tt1234567","status":"confident"}}', encoding="utf-8")
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": []}
    class Session:
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr("schauburg_schedule.enrichment.imdb.requests.Session", Session)
    assert resolve_imdb_matches([film("Distinctive Title")], token="secret", cache_path=cache, override_path=tmp_path / "overrides.json")["distinctive title"].reason == "no_match"


def test_translated_titles_are_not_merged_without_independent_confirmation(tmp_path):
    matches = resolve_imdb_matches([film("Die Odyssee"), film("The Odyssey", "universum")], token=None, cache_path=tmp_path / "matches.json", override_path=tmp_path / "overrides.json")
    assert set(matches) == {"die odyssee", "the odyssey"}

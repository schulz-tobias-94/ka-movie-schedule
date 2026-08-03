from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import requests

from ..models import Screening
from .title_normalization import clean_title, is_generic_sneak, lookup_candidates, movie_key

TMDB_API = "https://api.themoviedb.org/3"
USER_AGENT = "schauburg-schedule/0.1 IMDb enrichment"
RETRY_DAYS = 14
IMDB_ID_RE = re.compile(r"tt\d+$")


@dataclass(frozen=True)
class ImdbMatch:
    key: str
    query_title: str
    imdb_id: str | None
    status: str
    matched_title: str | None = None
    matched_year: int | None = None
    verified_at: str | None = None
    reason: str | None = None
    matched_by: tuple[str, ...] = ()
    score: int | None = None
    resolved_via: str | None = None
    authoritative_titles: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        if self.imdb_id:
            return f"https://www.imdb.com/title/{self.imdb_id}/"
        return imdb_search_url(self.query_title)


@dataclass(frozen=True)
class _Evidence:
    displayed: str
    query_title: str
    key: str
    candidates: tuple[str, ...]
    year: int | None
    runtime: int | None
    directors: tuple[str, ...]
    original_language: str | None
    aliases: tuple[str, ...]

def imdb_search_url(title: str) -> str:
    return f"https://www.imdb.com/find/?{urlencode({'q': title, 's': 'tt', 'ttype': 'ft'})}"


class OverrideError(ValueError):
    pass


def _load_overrides(path: Path) -> dict[str, ImdbMatch]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverrideError(f"Invalid IMDb override file: {exc}") from exc
    if not isinstance(data, dict):
        raise OverrideError("IMDb overrides must be an object.")
    matches = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, dict) or not IMDB_ID_RE.fullmatch(str(value.get("imdb_id", ""))):
            raise OverrideError(f"Invalid IMDb override: {key!r}")
        matches[key] = ImdbMatch(key, clean_title(key.rsplit("|", 1)[0]), value["imdb_id"], "manual", value.get("canonical_title"), None)
    return matches


def _load_cache(path: Path) -> dict[str, ImdbMatch]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.getLogger(__name__).debug("Ignoring IMDb cache: %s", exc)
        return {}
    matches = {}
    for key, value in data.items() if isinstance(data, dict) else ():
        try:
            match = ImdbMatch(key, value["query_title"], value.get("imdb_id"), value["status"], value.get("matched_title"), value.get("matched_year"), value.get("verified_at"), value.get("reason"), tuple(value.get("matched_by", ())), value.get("score"), value.get("resolved_via"), tuple(value.get("authoritative_titles", ())))
            if match.status not in {"exact", "confident", "search_fallback", "unresolved", "manual"} or (match.imdb_id and not IMDB_ID_RE.fullmatch(match.imdb_id)):
                raise ValueError
            matches[key] = match
        except (KeyError, TypeError, ValueError):
            logging.getLogger(__name__).debug("Ignoring invalid IMDb cache entry: %r", key)
    return matches


def _write_cache(path: Path, matches: dict[str, ImdbMatch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".imdb-matches.", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump({key: asdict(value) for key, value in sorted(matches.items())}, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def _cache_is_retryable(match: ImdbMatch, *, token_available: bool) -> bool:
    if match.imdb_id:
        return token_available and match.status != "manual" and not match.authoritative_titles
    if match.reason == "generic_sneak":
        return False
    if match.reason == "token_unavailable" and token_available:
        return True
    try:
        return datetime.now(UTC) - datetime.fromisoformat(match.verified_at or "") >= timedelta(days=RETRY_DAYS)
    except ValueError:
        return True


def _year(value: object) -> int | None:
    match = re.match(r"(\d{4})", value) if isinstance(value, str) else None
    return int(match.group(1)) if match and 1888 <= int(match.group(1)) <= 2100 else None


def _name(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


def _comparison_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u2013", "-").replace("\u2014", "-").replace("\u2019", "'").strip().rstrip(".")).casefold()


def _title_match(item: dict, evidence: _Evidence) -> tuple[str, str, int] | None:
    variants = item.get("_title_variants", ())
    for title, label in variants:
        if any(movie_key(title) == movie_key(query) for query in evidence.candidates):
            return title, label, 50
    query = _comparison_title(evidence.query_title)
    meaningful = movie_key(evidence.query_title).split()
    if len(meaningful) < 2 or len("".join(meaningful)) < 8:
        return None
    for title, label in variants:
        provider = _comparison_title(title)
        if label in {"German localized title", "alternate title"} and re.match(rf"^{re.escape(query)}\s*(?:-|:)\s+", provider):
            return title, "localized title prefix", 40
    return None


def _score_candidate(item: dict, evidence: _Evidence) -> tuple[int, tuple[str, ...], str | None]:
    score, reasons = 0, []
    match = _title_match(item, evidence)
    if match:
        score += match[2]; reasons.append(match[1])
    else:
        return -100, (), "weak title"
    candidate_year = _year(item.get("release_date"))
    if evidence.year and candidate_year:
        difference = abs(evidence.year - candidate_year)
        if difference == 0: score += 25; reasons.append("exact year")
        elif difference == 1: score += 10; reasons.append("year within one")
        else: score -= 40; reasons.append("large year difference")
    directors = tuple(_name(item["name"]) for item in item.get("credits", {}).get("crew", []) if isinstance(item, dict) and item.get("job") == "Director" and isinstance(item.get("name"), str))
    if evidence.directors and directors:
        if set(map(_name, evidence.directors)) & set(directors): score += 30; reasons.append("director match")
        else: score -= 30; reasons.append("director mismatch")
    runtime = item.get("runtime")
    if evidence.runtime and isinstance(runtime, int) and runtime > 0:
        difference = abs(evidence.runtime - runtime)
        if difference <= 5: score += 13; reasons.append("runtime within five")
        elif difference <= 15: score += 5; reasons.append("runtime within fifteen")
        elif difference > 30: score -= 20; reasons.append("large runtime difference")
    language = item.get("original_language")
    if evidence.original_language and isinstance(language, str) and language.casefold() == evidence.original_language[:2].casefold():
        score += 6; reasons.append("original language")
    return score, tuple(reasons), None


def _title_variants(item: dict) -> tuple[tuple[str, str], ...]:
    values = []
    for title, label in item.get("_search_titles", ()):
        if isinstance(title, str):
            values.append((title, label))
    for key, label in (("title", "English title"), ("original_title", "original title")):
        if isinstance(item.get(key), str):
            values.append((item[key], label))
    for title in item.get("_translated_titles", ()):
        values.append((title, "German localized title"))
    for title in item.get("_alternate_titles", ()):
        values.append((title, "alternate title"))
    return tuple(dict.fromkeys(values))


def _resolve_remote(session: requests.Session, token: str, evidence: _Evidence) -> ImdbMatch | None:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    logger = logging.getLogger(__name__)
    try:
        results = []
        for query in dict.fromkeys(evidence.candidates):
            for language in ("de-DE", "en-US"):
                params = {"query": query, "language": language}
                if evidence.year:
                    params["year"] = evidence.year
                response = session.get(f"{TMDB_API}/search/movie", params=params, headers=headers, timeout=10)
                response.raise_for_status()
                for item in response.json().get("results", []):
                    if isinstance(item, dict):
                        results.append((item, language))
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.debug("TMDb lookup failed for %r: %s", evidence.query_title, exc)
        return None
    candidates: dict[int, dict] = {}
    for item, language in results:
        if not isinstance(item.get("id"), int):
            continue
        candidate = candidates.setdefault(item["id"], item | {"_search_titles": []})
        title = item.get("title")
        if isinstance(title, str):
            candidate["_search_titles"].append((title, "German localized title" if language == "de-DE" else "English title"))
    if not candidates:
        return ImdbMatch(evidence.key, evidence.query_title, None, "search_fallback", verified_at=datetime.now(UTC).isoformat(), reason="no_match")
    ranked = []
    for candidate in list(candidates.values())[:3]:
        details = candidate
        try:
            response = session.get(f"{TMDB_API}/movie/{candidate['id']}", params={"append_to_response": "credits"}, headers=headers, timeout=10)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and payload.get("id") == candidate["id"]:
                details = candidate | payload | {"_search_titles": candidate["_search_titles"]}
        except (requests.RequestException, ValueError, AttributeError):
            pass
        translated, alternatives = [], []
        if details.get("id") == candidate["id"]:
            try:
                response = session.get(f"{TMDB_API}/movie/{candidate['id']}/translations", headers=headers, timeout=10)
                response.raise_for_status()
                translated = [entry.get("data", {}).get("title") for entry in response.json().get("translations", []) if isinstance(entry, dict) and entry.get("iso_639_1") == "de"]
                response = session.get(f"{TMDB_API}/movie/{candidate['id']}/alternative_titles", headers=headers, timeout=10)
                response.raise_for_status()
                alternatives = [entry.get("title") for entry in response.json().get("titles", []) if isinstance(entry, dict)]
            except (requests.RequestException, ValueError, AttributeError):
                pass
        details = details | {"_translated_titles": tuple(title for title in translated if isinstance(title, str)), "_alternate_titles": tuple(title for title in alternatives if isinstance(title, str))}
        details["_title_variants"] = _title_variants(details)
        score, reasons, rejection = _score_candidate(details, evidence)
        matched = _title_match(details, evidence)
        if matched and matched[1] == "localized title prefix":
            logger.debug("IMDb title variant: cinema=%r provider=%r relation=localized title prefix", evidence.displayed, matched[0])
        logger.debug("IMDb candidate: tmdb_id=%s title=%r original=%r German=%s alternates=%s score=%s evidence=%s%s", candidate["id"], details.get("title"), details.get("original_title"), list(details["_translated_titles"]), list(details["_alternate_titles"]), score, ", ".join(reasons), f" rejection={rejection}" if rejection else "")
        ranked.append((score, reasons, details))
    ranked.sort(key=lambda value: value[0], reverse=True)
    top_score, top_reasons, candidate = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else -100
    distinctive_exact = len(movie_key(evidence.query_title)) >= 10 and len(movie_key(evidence.query_title).split()) >= 2
    minimum_score = 50 if top_score > 50 or distinctive_exact else 60
    if top_score < minimum_score or top_score - runner_up < 15:
        reason = "ambiguous" if top_score >= 50 else "no_match"
        logger.debug("IMDb result: status=search_fallback reason=%s top_score=%s runner_up=%s", reason, top_score, runner_up)
        return ImdbMatch(evidence.key, evidence.query_title, None, "search_fallback", verified_at=datetime.now(UTC).isoformat(), reason=reason, score=top_score)
    try:
        response = session.get(f"{TMDB_API}/movie/{candidate['id']}/external_ids", headers=headers, timeout=10)
        response.raise_for_status()
        imdb_id = response.json().get("imdb_id")
    except (requests.RequestException, ValueError, AttributeError) as exc:
        logger.debug("TMDb external IDs failed for %r: %s", evidence.query_title, exc)
        return None
    if not isinstance(imdb_id, str) or not IMDB_ID_RE.fullmatch(imdb_id):
        return ImdbMatch(evidence.key, evidence.query_title, None, "search_fallback", verified_at=datetime.now(UTC).isoformat(), reason="no_imdb_id", score=top_score)
    year = _year(candidate.get("release_date"))
    return ImdbMatch(evidence.key, evidence.query_title, imdb_id, "confident", candidate.get("title"), year, datetime.now(UTC).isoformat(), matched_by=top_reasons, score=top_score, authoritative_titles=tuple(title for title, _ in candidate.get("_title_variants", ())))


def _conflicts(entries: list[Screening]) -> bool:
    years = {item.release_year for item in entries if item.release_year}
    directors = {tuple(sorted(_name(value) for value in item.director_names)) for item in entries if item.director_names}
    runtimes = [item.runtime_minutes for item in entries if item.runtime_minutes]
    source_movies: dict[str, set[str]] = {}
    for item in entries:
        if item.movie_url:
            source_movies.setdefault(item.cinema_id, set()).add(item.movie_url)
    return len(years) > 1 or len(directors) > 1 or (runtimes and max(runtimes) - min(runtimes) > 30) or any(len(urls) > 1 for urls in source_movies.values())


def _clusters(entries: list[Screening]) -> list[list[Screening]]:
    """Keep only metadata that can describe one film without contradiction."""
    if not _conflicts(entries):
        return [entries]
    clusters: list[list[Screening]] = []
    # Missing metadata must not choose between competing known works.
    for item in entries:
        compatible = next((cluster for cluster in clusters if not _conflicts(cluster + [item])), None)
        if compatible is not None and (item.release_year or not any(other.release_year for other in entries)):
            compatible.append(item)
        else:
            clusters.append([item])
    return clusters


def _evidence(screenings: list[Screening]) -> list[_Evidence]:
    grouped: dict[str, list[Screening]] = {}
    for item in screenings:
        grouped.setdefault(movie_key(item.movie_title), []).append(item)
    result = []
    for base_key, source_entries in grouped.items():
        groups = _clusters(source_entries)
        allow_base_alias = len(groups) == 1
        for entries in groups:
            years = {item.release_year for item in entries if item.release_year}
            runtimes = [item.runtime_minutes for item in entries if item.runtime_minutes]
            directors = {tuple(item.director_names) for item in entries if item.director_names}
            languages = {item.original_language for item in entries if item.original_language}
            year = next(iter(years)) if len(years) == 1 else None
            runtime = round(sum(runtimes) / len(runtimes)) if runtimes and max(runtimes) - min(runtimes) <= 15 else None
            director_names = next(iter(directors)) if len(directors) == 1 else ()
            original_language = next(iter(languages)) if len(languages) == 1 else None
            aliases = {movie_key(item.movie_title, item.release_year) for item in entries}
            if allow_base_alias:
                aliases.add(base_key)
            else:
                aliases.discard(base_key)
            first = entries[0]
            candidates = list(lookup_candidates(first.movie_title))
            for item in entries:
                candidates.extend(value for value in (item.original_title, *item.alternate_titles) if value)
            key = movie_key(first.movie_title, year)
            if len(groups) > 1 and not year:
                discriminator = "director:" + ",".join(_name(value) for value in director_names) if director_names else f"runtime:{runtime}" if runtime else f"source:{first.cinema_id}:{first.movie_url or first.movie_title}"
                key = f"{base_key}|{discriminator}"
            result.append(_Evidence(first.movie_title, clean_title(first.movie_title), key, tuple(dict.fromkeys(clean_title(value) for value in candidates)), year, runtime, director_names, original_language, tuple(sorted(aliases))))
    return result


def _compatible_alias(source: _Evidence, target: _Evidence) -> bool:
    if source.year and target.year and source.year != target.year:
        return False
    if source.directors and target.directors and not (set(map(_name, source.directors)) & set(map(_name, target.directors))):
        return False
    return not (source.runtime and target.runtime and abs(source.runtime - target.runtime) > 30)


def _usable_alias(value: str) -> bool:
    words = movie_key(value).split()
    return len(words) >= 2 and len("".join(words)) >= 8


def resolve_imdb_matches(screenings: list[Screening], *, token: str | None = None, override_path: Path = Path("config/movie-overrides.json"), cache_path: Path = Path("metadata/imdb-matches.json"), refresh: bool = False) -> dict[str, ImdbMatch]:
    """Best-effort IMDb enrichment. Provider failures always return search links."""
    titles = _evidence(screenings)
    try:
        overrides = _load_overrides(override_path)
    except OverrideError as exc:
        logging.getLogger(__name__).warning("%s", exc)
        overrides = {}
    cache, resolved, session = _load_cache(cache_path), {}, requests.Session()
    token = token if token is not None else os.getenv("TMDB_API_TOKEN")
    counts = {name: 0 for name in ("manual", "cache", "confident", "search_fallback", "unresolved", "provider_failures", "ambiguous", "no_match", "generic_event", "year", "director", "runtime")}
    for evidence in titles:
        key = evidence.key
        logging.getLogger(__name__).debug('IMDb lookup: displayed=%r cleaned=%r year=%s runtime=%s directors=%s', evidence.displayed, evidence.query_title, evidence.year, evidence.runtime, ", ".join(evidence.directors) or "none")
        if key in overrides:
            resolved[key] = overrides[key]
            counts["manual"] += 1
        elif (cached := cache.get(key)) and not refresh and not _cache_is_retryable(cached, token_available=bool(token)):
            resolved[key] = cached
            counts["cache"] += 1
            if cached.reason == "generic_sneak":
                counts["generic_event"] += 1
            logging.getLogger(__name__).debug('IMDb cache hit: title=%r', evidence.query_title)
        elif is_generic_sneak(evidence.displayed):
            resolved[key] = cache[key] = ImdbMatch(key, evidence.displayed, None, "search_fallback", verified_at=datetime.now(UTC).isoformat(), reason="generic_sneak")
            counts["search_fallback"] += 1
            counts["generic_event"] += 1
            logging.getLogger(__name__).debug('IMDb fallback: title=%r reason=generic_sneak', evidence.displayed)
        elif token:
            remote = _resolve_remote(session, token, evidence)
            if remote:
                resolved[key] = cache[key] = remote
                counts[remote.status] += 1
                if remote.imdb_id:
                    logging.getLogger(__name__).debug('IMDb match: status=%s imdb_id=%s matched_title=%r', remote.status, remote.imdb_id, remote.matched_title)
                else:
                    counts[remote.reason] = counts.get(remote.reason, 0) + 1
                    logging.getLogger(__name__).debug('IMDb fallback: title=%r reason=%s', evidence.query_title, remote.reason)
            else:
                resolved[key] = ImdbMatch(key, evidence.query_title, None, "search_fallback")
                counts["provider_failures"] += 1
                logging.getLogger(__name__).debug('IMDb fallback: title=%r reason=provider_failure', evidence.query_title)
        else:
            resolved[key] = cache[key] = ImdbMatch(key, evidence.query_title, None, "search_fallback", verified_at=datetime.now(UTC).isoformat(), reason="token_unavailable")
            counts["search_fallback"] += 1
    # A confident rich lookup supersedes compatible title-only fallbacks.
    for evidence in titles:
        match = resolved.get(evidence.key)
        if match and match.imdb_id:
            for alias in evidence.aliases:
                if alias not in overrides:
                    alias_match = ImdbMatch(alias, match.query_title, match.imdb_id, match.status, match.matched_title, match.matched_year, match.verified_at, match.reason, match.matched_by, match.score, evidence.key if alias != evidence.key else None, match.authoritative_titles)
                    resolved[alias] = alias_match
                    cache[alias] = alias_match
    by_base: dict[str, list[_Evidence]] = {}
    for evidence in titles:
        by_base.setdefault(movie_key(evidence.displayed), []).append(evidence)
    for source in titles:
        match = resolved.get(source.key)
        if not match or not match.imdb_id:
            continue
        for title in match.authoritative_titles:
            base = movie_key(title)
            targets = by_base.get(base, [])
            if not _usable_alias(title):
                logging.getLogger(__name__).debug("IMDb alias refused: alias=%r reason=generic title", title)
                continue
            if len(targets) != 1 or targets[0].key == source.key:
                if len(targets) > 1:
                    logging.getLogger(__name__).debug("IMDb alias refused: alias=%r reason=multiple current identities", title)
                continue
            target = targets[0]
            if target.key in overrides or not _compatible_alias(source, target):
                logging.getLogger(__name__).debug("IMDb alias refused: alias=%r reason=metadata conflict", title)
                continue
            existing = resolved.get(target.key)
            if existing and existing.imdb_id and existing.imdb_id != match.imdb_id:
                logging.getLogger(__name__).debug("IMDb alias refused: alias=%r reason=different confident match", title)
                continue
            propagated = ImdbMatch(target.key, target.query_title, match.imdb_id, "confident", match.matched_title, match.matched_year, match.verified_at, None, ("TMDb authoritative title alias",), match.score, source.key, match.authoritative_titles)
            for alias in target.aliases or (target.key,):
                if alias not in overrides:
                    resolved[alias] = cache[alias] = ImdbMatch(alias, propagated.query_title, propagated.imdb_id, propagated.status, propagated.matched_title, propagated.matched_year, propagated.verified_at, propagated.reason, propagated.matched_by, propagated.score, source.key, propagated.authoritative_titles)
            logging.getLogger(__name__).debug("IMDb alias: alias=%r resolved_via=%r imdb_id=%s evidence=TMDb authoritative title alias", title, source.key, match.imdb_id)
    try:
        _write_cache(cache_path, cache)
    except OSError as exc:
        logging.getLogger(__name__).debug("Could not save IMDb cache: %s", exc)
    for match in resolved.values():
        for item in match.matched_by:
            if item == "exact year": counts["year"] += 1
            elif item == "director match": counts["director"] += 1
            elif item.startswith("runtime"): counts["runtime"] += 1
    logging.getLogger(__name__).debug("IMDb summary: manual=%d cache_hits=%d confident=%d ambiguous=%d no_match=%d generic_event=%d provider_failures=%d year=%d director=%d runtime=%d", counts["manual"], counts["cache"], counts["confident"], counts["ambiguous"], counts["no_match"], counts["generic_event"], counts["provider_failures"], counts["year"], counts["director"], counts["runtime"])
    return resolved

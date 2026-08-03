from __future__ import annotations

import re
import unicodedata

_PREFIX = re.compile(r"^\s*(?:\((?:[a-zäöü]{2,12}\.?\s*)?(?:OV|OmU|OmeU|OmdU)\)|(?:OV|OmU|OmeU|OmdU))\s*[-:|·]?\s*", re.I)
_SUFFIX = re.compile(r"\s*(?:[-|·]\s*)?\(?(?:OV|OmU|OmeU|OmdU|2D|3D|D-BOX|Originalfassung|mit deutschen Untertiteln|in analoger 70 mm Präsentation|auch in D-BOX|Preview|Vorpremiere|Sneak Preview|Special|Double Feature)\)?\s*$", re.I)
_WEEK_SUFFIX = re.compile(r"\s+\d+\.\s*(?:W(?:oche)?\.?)\s*$", re.I)
_LANGUAGE_SUFFIX = re.compile(r"\s*\((?:(?:ukrainische|englische|türkische|deutsche|koreanische|japanische)\s+Sprachfassung|Originalfassung|mit deutschen Untertiteln)\)\s*$", re.I)
_GENERIC_SNEAK = re.compile(r"^(?:ov\s+)?(?:sneak(?:\s+preview)?|überraschungsfilm)$", re.I)


def clean_title(value: str) -> str:
    """Remove only clearly separate cinema presentation labels for metadata lookup."""
    title = unicodedata.normalize("NFKC", value).replace("\u2019", "'").replace("\u00a0", " ")
    title = _PREFIX.sub("", title)
    title = _LANGUAGE_SUFFIX.sub("", title)
    title = _WEEK_SUFFIX.sub("", title)
    while _SUFFIX.search(title):
        title = _SUFFIX.sub("", title)
    return title.strip(" .,:;|-_") or value.strip()


def is_generic_sneak(value: str) -> bool:
    return bool(_GENERIC_SNEAK.fullmatch(clean_title(value)))


def lookup_candidates(value: str) -> list[str]:
    """Return conservative alternatives for clearly bilingual cinema titles."""
    cleaned = clean_title(value)
    candidates = [cleaned]
    if " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        if len(left) > 3 and len(right) > 3 and any(char.isalpha() for char in left) and any(char.isalpha() for char in right):
            candidates.extend((left.strip(), right.strip()))
    return list(dict.fromkeys(candidates))


def movie_key(value: str, year: int | None = None) -> str:
    normalized = clean_title(value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()
    return f"{normalized}|{year}" if year else normalized

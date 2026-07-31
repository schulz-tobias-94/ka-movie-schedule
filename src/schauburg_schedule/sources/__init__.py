from .base import CinemaSource, SourceError
from .filmpalast import FilmpalastSource
from .schauburg import SchauburgSource
from .universum import UniversumSource

KNOWN_CINEMA_IDS = frozenset({"schauburg", "filmpalast", "universum"})
IMPLEMENTED_SOURCES = {"schauburg": SchauburgSource, "filmpalast": FilmpalastSource, "universum": UniversumSource}


def select_sources(cinema_ids: list[str] | None = None) -> list[CinemaSource]:
    selected = cinema_ids or list(IMPLEMENTED_SOURCES)
    sources = []
    for cinema_id in selected:
        if cinema_id not in KNOWN_CINEMA_IDS:
            raise ValueError(f"Unknown cinema identifier: {cinema_id}")
        source_type = IMPLEMENTED_SOURCES.get(cinema_id)
        if source_type is None:
            raise ValueError(f"Cinema is not implemented yet: {cinema_id}")
        sources.append(source_type())
    return sources

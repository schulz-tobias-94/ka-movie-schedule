from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..models import Screening


class SourceError(RuntimeError):
    """An expected network or parsing failure from one cinema source."""


class CinemaSource(ABC):
    cinema_id: str
    cinema_name: str

    @abstractmethod
    def fetch(self, *, days: int, today: date, use_cache: bool) -> list[Screening]:
        """Fetch and normalize this cinema's screenings."""

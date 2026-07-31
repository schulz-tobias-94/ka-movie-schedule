from dataclasses import dataclass
from datetime import date, datetime, time


@dataclass(frozen=True)
class Screening:
    cinema_id: str
    cinema_name: str
    date: date
    time: time
    movie_title: str
    format_label: str | None = None
    original_language: str | None = None
    subtitle_language: str | None = None
    auditorium: str | None = None
    movie_url: str | None = None
    booking_url: str | None = None
    dimension: str | None = None
    technology: str | None = None
    screening_url: str | None = None


@dataclass(frozen=True)
class CinemaResult:
    cinema_id: str
    cinema_name: str
    screenings: tuple[Screening, ...]
    retrieved_at: datetime
    success: bool
    error: str | None = None
    fresh: bool = True

    @property
    def state(self) -> str:
        if not self.success:
            return "failed"
        if not self.fresh:
            return "restored"
        return "success_empty" if not self.screenings else "fresh"

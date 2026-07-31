from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True, order=True)
class Screening:
    date: date
    time: time
    title: str
    version_label: str
    movie_url: str | None = None

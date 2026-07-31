"""Compatibility imports for the migrated Schauburg source."""

from .sources.schauburg import (
    ScheduleParseError,
    VERSION_LABELS,
    normalize,
    parse_schedule,
    schedule_dates,
    version_label,
)

__all__ = [
    "ScheduleParseError", "VERSION_LABELS", "normalize", "parse_schedule",
    "schedule_dates", "version_label",
]

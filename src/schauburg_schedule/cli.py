from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .fetcher import FetchError, fetch_schedule_html
from .formatter import format_html, format_json, format_text
from .parser import ScheduleParseError, parse_schedule


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List Schauburg original-language screenings.")
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument("--json", action="store_true", help="write JSON instead of a table")
    output_format.add_argument("--html", action="store_true", help="write a standalone HTML page")
    parser.add_argument("--days", type=int, default=8, metavar="NUMBER", help="include NUMBER calendar days including today (default: 8)")
    parser.add_argument("--output", type=Path, metavar="FILE", help="write output to FILE")
    parser.add_argument("--debug", action="store_true", help="enable diagnostic logging")
    parser.add_argument("--no-cache", action="store_true", help="do not use or update the local cache")
    return parser


def today_in_berlin() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    if args.days is not None and args.days < 1:
        print("error: --days must be at least 1", file=sys.stderr)
        return 2
    try:
        today = today_in_berlin()
        screenings = parse_schedule(fetch_schedule_html(days=args.days, use_cache=not args.no_cache, today=today))
    except (FetchError, ScheduleParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    last_date = today + timedelta(days=args.days - 1)
    screenings = [item for item in screenings if today <= item.date <= last_date]
    if args.html:
        output = format_html(screenings, start_date=today, end_date=last_date, updated_at=datetime.now(ZoneInfo("Europe/Berlin")))
    else:
        output = format_json(screenings) if args.json else format_text(screenings) + "\n"
    try:
        if args.output:
            if args.html:
                args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except OSError as exc:
        print(f"error: could not write output: {exc}", file=sys.stderr)
        return 1
    return 0

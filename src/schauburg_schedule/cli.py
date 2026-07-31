from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .coordinator import collect_screenings, persist_and_restore_snapshots, successful_screenings
from .formatter import format_html, format_json, format_text
from .sources import select_sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List Schauburg original-language screenings.")
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument("--json", action="store_true", help="write JSON instead of a table")
    output_format.add_argument("--html", action="store_true", help="write a standalone HTML page")
    parser.add_argument("--days", type=int, default=8, metavar="NUMBER", help="include NUMBER calendar days including today (default: 8)")
    parser.add_argument("--output", type=Path, metavar="FILE", help="write output to FILE")
    parser.add_argument("--debug", action="store_true", help="enable diagnostic logging")
    parser.add_argument("--no-cache", action="store_true", help="do not use or update the local cache")
    parser.add_argument("--cinema", action="append", metavar="CINEMA_ID", help="include a cinema (repeatable)")
    parser.add_argument("--site-title", default="Karlsruhe Originalfassungen", metavar="TEXT", help="HTML page title")
    parser.add_argument("--snapshot-dir", type=Path, default=Path("snapshots"), metavar="PATH", help="directory for per-cinema snapshots")
    parser.add_argument("--no-snapshot-fallback", action="store_true", help="do not restore failed sources from snapshots")
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
        sources = select_sources(args.cinema)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    today = today_in_berlin()
    results = collect_screenings(sources, days=args.days, today=today, use_cache=not args.no_cache)
    last_date = today + timedelta(days=args.days - 1)
    results = persist_and_restore_snapshots(results, directory=args.snapshot_dir, today=today, end_date=last_date, fallback=not args.no_snapshot_fallback)
    for result in results:
        if not result.success:
            print(f"error: {result.cinema_name}: {result.error}", file=sys.stderr)
    if not any(result.success for result in results):
        return 1
    screenings = successful_screenings(results)
    screenings = [item for item in screenings if today <= item.date <= last_date]
    if args.html:
        output = format_html(results, start_date=today, end_date=last_date, updated_at=datetime.now(ZoneInfo("Europe/Berlin")), site_title=args.site_title)
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
    return 1 if any(not result.success for result in results) else 0

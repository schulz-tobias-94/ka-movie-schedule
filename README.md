# Schauburg Schedule

Lists upcoming Schauburg Karlsruhe screenings marked as original-language or subtitled versions. It follows the site-provided HTML fragment URL behind `mehr laden`; no browser automation is required. By default it retrieves today plus the next seven calendar days.

## Install

```bash
python3 -m pip install .
```

For tests:

```bash
python3 -m pip install -e '.[test]'
pytest
```

## Usage

```bash
python -m schauburg_schedule
python -m schauburg_schedule --days 14
python -m schauburg_schedule --json --output screenings.json
python -m schauburg_schedule --html --output site/index.html
python -m schauburg_schedule --no-cache --debug
```

Example output:

```text
Date      Day       Title        Type  Time
31.07.26  Friday    Die Odyssee  OV    16:30:00
                      The Invite   OmU   19:00:00
```

Supported labels are `OV`, `OmU`, `OmeU`, and `OmdU`, case-insensitively. Add another exact label to `VERSION_LABELS` in `src/schauburg_schedule/parser.py` when the cinema introduces one.

Responses are cached for 15 minutes in the platform user cache directory (typically `~/.cache/schauburg-schedule` on Linux). Use `--no-cache` to bypass it.

`--html` writes a standalone, UTF-8 HTML page for GitHub Pages with no JavaScript or external assets. It includes the same eight-day default range and only original-language screenings.

## Troubleshooting

Use `--debug` to see skipped malformed entries and cache diagnostics. Connection and parser errors are printed to stderr with a nonzero exit status. The cinema can change its website markup; in that case, update the parser selectors and refresh `tests/fixtures/schedule.html` from a representative response.

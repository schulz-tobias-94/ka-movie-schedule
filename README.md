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
python -m schauburg_schedule --cinema schauburg --json
python -m schauburg_schedule --cinema filmpalast --json
python -m schauburg_schedule --cinema universum --json
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

Successful source runs also save publishable per-cinema snapshots in `snapshots/` by default. When a source temporarily fails, the command uses only a valid snapshot that still has screenings within the requested future date range; past entries are removed. Use `--snapshot-dir PATH` to choose another location or `--no-snapshot-fallback` to disable restoration. A successful live result with no matching screenings remains authoritative and does not use older data.

`--html` writes a standalone, UTF-8 HTML page for GitHub Pages. It presents Schauburg, Filmpalast, and Universum in selectable tabs, while retaining all three schedules as vertical sections when JavaScript is disabled. The page uses no external assets and includes the same eight-day default range and only original-language screenings.

Generate it locally with:

```bash
python -m schauburg_schedule --html --output site/index.html
```

Direct links can select a cinema with `#schauburg`, `#filmpalast`, or `#universum`, for example `site/index.html#universum`. The selected tab is also remembered locally when browser storage is available. Each panel reports whether its data is current, restored from an earlier successful snapshot, or unavailable. Text and JSON output are unchanged.

## Cinema Sources

The command uses source adapters so each cinema can keep its own website parsing rules. `schauburg`, `filmpalast`, and `universum` are implemented. With no `--cinema` option, all three sources run independently.

Filmpalast data comes from its [weekly program page](https://filmpalast.net/programmuebersicht/?time=week), which generally exposes about one week of upcoming screenings. The adapter preserves explicit source labels such as `OV`, `OmU`, `englisch mit deutschen Untertiteln`, and `koreanisch mit Untertiteln`, and normalizes named spoken/subtitle languages when stated.

Universum data comes from its [program page](https://www.universum-city.de/de/programm). Its server-rendered Cineamo payload contains the program, ISO showing times, audio/subtitle languages, rooms, and ticket URLs; no browser automation is used. Explicit screening audio and subtitle metadata takes precedence over title prefixes, and optional `3D`/`2D` and technology data such as `D-BOX` are retained in JSON and HTML output. Individual screening detail URLs are included where the overview exposes them. HTML output remains a combined page rather than separate cinema tabs.

## GitHub Pages

GitHub Actions regenerates the schedule page daily at 06:15 UTC and on relevant pushes to `main`. Run it manually from the repository's **Actions** tab by selecting **Update GitHub Pages** and choosing **Run workflow**. Scheduled workflows use UTC and GitHub may occasionally delay them.

After a successful build, the workflow commits changed `snapshots/*.json` files with the GitHub Actions bot identity. Snapshot-only commits do not match the workflow push paths, so they do not create deployment loops.

In repository **Settings** > **Pages**, set the publishing source to **GitHub Actions**. After the first successful deployment, the Pages URL appears in the workflow's deploy job and on that settings page. Open the failed workflow run in the Actions tab to inspect scraper or deployment logs.

## Troubleshooting

Use `--debug` to see skipped malformed entries and cache diagnostics. Connection and parser errors are printed to stderr with a nonzero exit status. The cinema can change its website markup; in that case, update the parser selectors and refresh `tests/fixtures/schedule.html` from a representative response.

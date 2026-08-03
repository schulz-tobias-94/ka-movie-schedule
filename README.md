# Karlsruhe Original-Version Cinema Schedule

Retrieve original-language, subtitled, and explicitly foreign-language screenings from Schauburg Karlsruhe, Filmpalast am ZKM, and Universum City Kinos Karlsruhe. The project produces terminal output, JSON, and a responsive static HTML site that is deployed daily to GitHub Pages.

See the [live cinema schedule](https://schulz-tobias-94.github.io/ka-movie-schedule/). This is an independent project and is not affiliated with any of the cinemas.

## Live site

The published page is available at [Karlsruhe Original-Version Cinema Schedule](https://schulz-tobias-94.github.io/ka-movie-schedule/).

Direct links select a cinema:

- [Schauburg](https://schulz-tobias-94.github.io/ka-movie-schedule/#schauburg)
- [Filmpalast](https://schulz-tobias-94.github.io/ka-movie-schedule/#filmpalast)
- [Universum](https://schulz-tobias-94.github.io/ka-movie-schedule/#universum)

The selected tab is remembered locally when browser storage is available.

## Features

- Three independent cinema source adapters with per-screening filtering.
- Recognition of `OV`, `OmU`, `OmeU`, `OmdU`, and explicit non-German language labels where a source provides them.
- Spoken and subtitle languages preserved when available.
- Inclusive eight-day default range, Europe/Berlin date handling, and no past screenings.
- Terminal, JSON, and standalone HTML output.
- Selectable cinema tabs, hash links, responsive layout, automatic system light/dark mode, and teal, dark-blue, and red cinema themes.
- Keyboard-accessible tabs and a no-JavaScript fallback that shows every cinema section.
- Per-cinema failure isolation and snapshot fallback.
- Best-effort IMDb title links, with safe search links when no exact match is available.
- Daily GitHub Pages deployment.

## Installation

Python 3.12 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

For development and tests:

```bash
python -m pip install -e '.[test]'
```

## Usage

```bash
python -m schauburg_schedule
python -m schauburg_schedule --days 8
python -m schauburg_schedule --cinema schauburg
python -m schauburg_schedule --cinema filmpalast
python -m schauburg_schedule --cinema universum
python -m schauburg_schedule --json
python -m schauburg_schedule --json --output screenings.json
python -m schauburg_schedule --html --output site/index.html
python -m schauburg_schedule --no-cache --debug
python -m schauburg_schedule --html --refresh-imdb --output site/index.html
```

With no `--cinema`, all three sources run. `--days 8` means today plus the following seven calendar days. Past screenings are excluded. A failed cinema does not stop the other cinemas, and a successful live result with no matching screenings is not replaced with older snapshot data.

Additional options:

- `--output FILE`: write output to a file.
- `--snapshot-dir PATH`: use a different per-cinema snapshot directory; the default is `snapshots`.
- `--no-snapshot-fallback`: do not restore data for failed sources.
- `--site-title TEXT`: set the HTML page title only.

Illustrative terminal output:

```text
Date      Day     Cinema                        Title                         Type                                  Time
31.07.26  Friday  Schauburg Karlsruhe            The Invite                    OmU                                   19:00:00
                   Filmpalast am ZKM             Spider-Man: Brand New Day     englisch · OV · Kino 9               20:15:00
                   Universum City Kinos Karlsruhe  Obsession - Du sollst mich lieben  OmU · English · German subtitles  21:00:00
```

## Supported cinemas

### Schauburg Karlsruhe

Source: [Schauburg program](https://www.schauburg.de/spielplan).

The adapter recognizes OV/OmU-style labels and follows the site’s additional-program loading mechanism behind “Mehr Laden”. It loads enough batches to satisfy the requested date range where the site makes them available.

### Filmpalast am ZKM

Source: [Filmpalast weekly program](https://filmpalast.net/programmuebersicht/?time=week).

The current embedded weekly payload reliably provides titles, format labels, performance times, auditoriums, booking links, and movie routes. It does not expose dependable release-year, runtime, director, original-title, country, or original-language movie metadata, so the adapter deliberately leaves those optional matching fields empty rather than deriving them from synopsis text.

The page generally exposes about one week of programming. The adapter recognizes OV/OmU markers and explicit spoken-language labels such as English, Korean, Japanese, and other languages. Original and subtitle languages are retained when supplied.

### Universum City Kinos Karlsruhe

Source: [Universum program](https://www.universum-city.de/de/programm).

The adapter uses explicit audio and subtitle metadata where available and retains auditorium, dimension, technology, and ticket links when supplied. Explicit screening-level metadata takes precedence over title prefixes; fields are not guaranteed for every screening.

## HTML site

Generate one standalone page locally:

```bash
python -m schauburg_schedule --html --output site/index.html
```

The page has selectable Schauburg, Filmpalast, and Universum tabs, with teal, dark-blue, and red identities respectively. It follows the visitor’s system light/dark preference, works on phones and desktops, supports keyboard tab navigation, and accepts the hash links listed above. Without JavaScript, all cinema sections remain visible.

Each panel reports whether its source is current, restored from a snapshot, or unavailable. The page has no external frontend framework, fonts, tracking, or runtime API dependencies.

Movie titles link to a canonical English IMDb title page when a confident match is available. Otherwise they link to IMDb title-search results. Cinema booking, screening, and movie-detail links remain separate `Tickets` or `Details` actions. IMDb resolution is optional and never removes screenings or blocks page generation.

## IMDb enrichment

TMDb is used only as an optional provider for IMDb external title IDs; it does not supply cinema schedules. The generated HTML footer includes the required TMDb attribution and official-logo notice: This product uses the TMDB API but is not endorsed or certified by TMDB. The project is independent and not affiliated with TMDb or IMDb. Set `TMDB_API_TOKEN` locally to enable remote matching. Without it, cached and manual matches are used where available and other titles receive an IMDb search link.

The workflow secret can be added in **Repository Settings -> Secrets and variables -> Actions** as `TMDB_API_TOKEN`. It is optional for local development, tests, pull requests, and deployment.

Manual corrections live in `config/movie-overrides.json`. Resolved publishable metadata is cached in `metadata/imdb-matches.json`; no provider responses or tokens are stored. Uncertain matches use search links, and a provider failure is retried later without affecting the cinema schedule.

Use `--refresh-imdb` to revalidate cached automatic matches after improving metadata or matching rules. Manual overrides remain authoritative.

## Snapshot resilience

Each cinema has a separate publishable JSON snapshot in `snapshots/`; snapshots contain normalized schedule data rather than raw website responses. Successful retrievals update only that cinema’s snapshot.

If a source fails, the program may restore that cinema’s prior snapshot when it still contains usable future screenings in the requested range. Past entries are removed and restored data is visibly marked in the HTML page. Expired snapshots, corrupted snapshots, and snapshots with no future screenings are not used; one broken snapshot does not affect other cinemas. A successful live empty result remains authoritative.

## GitHub Pages automation

The [GitHub Actions workflow](https://github.com/schulz-tobias-94/ka-movie-schedule/actions) runs daily at 06:15 UTC, can be started manually from the Actions tab, and runs on relevant application or workflow pushes. GitHub cron schedules can occasionally be delayed.

The workflow generates the static page, deploys it through GitHub Pages, and commits changed snapshots with `github-actions[bot]`. Snapshot-only commits do not match the workflow push paths, preventing deployment loops. Inspect failed workflow runs in the Actions tab. Forks must configure GitHub Pages to use GitHub Actions as the publishing source.

Changed IMDb-match cache data is committed with the same bot mechanism. The optional TMDb token is not printed or persisted.

## Architecture

```text
src/schauburg_schedule/
├── sources/
│   ├── schauburg.py
│   ├── filmpalast.py
│   └── universum.py
├── coordinator.py
├── snapshots.py
├── formatter.py
└── cli.py
```

Each source owns its website-specific fetching and parsing. Shared models normalize screening data, the coordinator isolates source failures, and formatters consume normalized results. Tests use saved fixtures and mocked responses rather than live cinema websites.

## Testing

Install test dependencies as shown above, then run:

```bash
pytest
```

The automated tests do not depend on live cinema websites.

## Troubleshooting

- Use `--debug` for parser, cache, and source diagnostics.
- Use `--no-cache` when local cached responses may be stale.
- A cinema website may change its markup or data source; update that cinema’s adapter, fixture, and tests.
- A restored tab indicates that its current retrieval failed but usable prior data remains. An unavailable tab has no usable snapshot.
- Run a successful live retrieval to refresh snapshots.
- Inspect failed GitHub Actions runs in the Actions tab for deployment or source diagnostics.

## Contributing and maintenance

Cinema websites and APIs change. When updating an adapter:

1. Change only that source where possible.
2. Refresh its fixture.
3. Add or update parser tests.
4. Run the complete suite.
5. Validate live output locally.

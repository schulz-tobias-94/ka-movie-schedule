from datetime import date, datetime, time
import json
from bs4 import BeautifulSoup

from schauburg_schedule.formatter import format_html, format_json, format_text
from schauburg_schedule.enrichment.imdb import ImdbMatch
from schauburg_schedule.enrichment.title_normalization import movie_key
from schauburg_schedule.models import CinemaResult, Screening


def screening(day, clock, title, label, movie_url=None):
    return Screening("schauburg", "Schauburg Karlsruhe", day, clock, title, label, movie_url=movie_url)


def cinema_result(cinema_id, cinema_name, items=(), *, success=True, fresh=True, error=None):
    return CinemaResult(cinema_id, cinema_name, tuple(items), datetime(2026, 7, 31, 13, 40), success, error, fresh)


def html(results, **kwargs):
    return format_html(results, start_date=date(2026, 7, 31), end_date=date(2026, 8, 7), updated_at=datetime(2026, 7, 31, 13, 45), **kwargs)


def test_text_is_grouped_by_date_and_movie():
    items = [
        screening(date(2026, 7, 31), time(16, 30), "Alpha", "OV"),
        screening(date(2026, 7, 31), time(19), "Alpha", "OV"),
        screening(date(2026, 8, 1), time(20, 45), "Beta", "OmU"),
    ]
    output = format_text(items)
    assert "31.07.26  Friday" in output
    assert "16:30:00" in output and "19:00:00" in output
    assert "01.08.26  Saturday" in output


def test_json_output_is_structured():
    output = json.loads(format_json([screening(date(2026, 7, 31), time(16, 30), "Alpha", "OV", "https://example.test/a")]))
    assert output == [{"date": "2026-07-31", "time": "16:30:00", "title": "Alpha", "version_label": "OV", "movie_url": "https://example.test/a"}]


def test_html_tabs_grouping_links_and_escaping():
    movie = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(16, 30), 'Mädchen < & "Film"', "OmU", "English", "German", "Saal 4", "https://example.test/a?x=1&y=2", "https://tickets.example/a")
    later = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(19), 'Mädchen < & "Film"', "OV")
    output = html([
        cinema_result("schauburg", "Schauburg Karlsruhe", [later, movie]),
        cinema_result("filmpalast", "Filmpalast am ZKM"),
        cinema_result("universum", "Universum City Kinos Karlsruhe"),
    ])
    soup = BeautifulSoup(output, "html.parser")
    assert output.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in output
    assert soup.html["lang"] == "de"
    assert len(soup.select('[role="tab"]')) == 3
    for cinema_id in ("schauburg", "filmpalast", "universum"):
        tab, panel = soup.select_one(f"#tab-{cinema_id}"), soup.select_one(f"#panel-{cinema_id}")
        assert tab["aria-controls"] == panel["id"] and panel["aria-labelledby"] == tab["id"]
    assert soup.select_one("#tab-schauburg")["aria-selected"] == "true"
    assert "Mädchen &lt; &amp; &quot;Film&quot;" in output
    assert "https://example.test/a?x=1&amp;y=2" not in output
    assert "https://www.imdb.com/find/?q=M%C3%A4dchen+%3C+%26+%22Film%22&amp;s=tt&amp;ttype=ft" in output
    assert output.count('<article class="movie">') == 1
    assert "16:30" in output and "19:00" in output
    assert 'class="format-badge">OmU</span>' in output
    assert "Englisch · Deutsche Untertitel · Saal 4" in output
    assert ">Tickets<" in output
    assert 'href="https://tickets.example/a" target="_blank" rel="noopener noreferrer">Tickets</a>' in output
    assert "Schauburg Karlsruhe: Mädchen" not in output
    assert "location.hash" in output and "localStorage" in output


def test_html_statuses_empty_results_safe_urls_and_custom_title():
    unsafe = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 30), time(18), "Past", "OV", movie_url="javascript:bad", booking_url="data:text/plain,bad")
    output = html([
        cinema_result("schauburg", "Schauburg Karlsruhe", [unsafe], fresh=False),
        cinema_result("filmpalast", "Filmpalast am ZKM", success=False, error="/tmp/secret token"),
        cinema_result("universum", "Universum City Kinos Karlsruhe"),
    ], site_title='Titel < & "')
    assert "Titel &lt; &amp; &quot;" in output
    assert "letzte erfolgreiche Stand" in output
    assert "Der Spielplan konnte derzeit nicht geladen werden und" in output
    assert "Für diesen Zeitraum wurden keine passenden" in output
    assert "javascript:bad" not in output and "data:text/plain" not in output
    assert "Past" not in output


def test_html_two_failed_sources_keeps_the_successful_panel():
    movie = Screening("universum", "Universum City Kinos Karlsruhe", date(2026, 7, 31), time(20), "Film", "OmU", "Spanish", "German")
    output = html([
        cinema_result("schauburg", "Schauburg Karlsruhe", success=False),
        cinema_result("filmpalast", "Filmpalast am ZKM", success=False),
        cinema_result("universum", "Universum City Kinos Karlsruhe", [movie]),
    ])
    assert output.count("Der Spielplan konnte derzeit nicht geladen werden und") == 2
    assert "Film" in output and 'class="format-badge">OmU</span>' in output and "Spanisch · Deutsche Untertitel" in output


def test_html_uses_imdb_for_titles_and_details_for_cinema_movie_urls():
    movie = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(20), "Film", "OV", movie_url="https://cinema.example/film")
    match = ImdbMatch(movie_key("Film"), "Film", "tt1234567", "exact")
    output = html([cinema_result("schauburg", "Schauburg Karlsruhe", [movie])], imdb_matches={match.key: match})
    assert 'href="https://www.imdb.com/title/tt1234567/"' in output
    assert 'target="_blank" rel="noopener noreferrer"' in output
    assert 'aria-label="Open Film on IMDb"' in output
    assert 'class="movie-action" href="https://cinema.example/film" target="_blank" rel="noopener noreferrer">Details</a>' in output


def test_html_uses_aliases_for_title_only_and_year_specific_screenings():
    title_only = Screening("schauburg", "Schauburg Karlsruhe", date(2026, 7, 31), time(20), "Die Odyssee", "OmU")
    dated = Screening("universum", "Universum City Kinos Karlsruhe", date(2026, 7, 31), time(21), "Die Odyssee", "OmU", release_year=2026)
    base = ImdbMatch("die odyssee", "Die Odyssee", "tt33764258", "confident")
    rich = ImdbMatch("die odyssee|2026", "Die Odyssee", "tt33764258", "confident", resolved_via="die odyssee|2026")
    output = html([cinema_result("schauburg", "Schauburg Karlsruhe", [title_only]), cinema_result("universum", "Universum City Kinos Karlsruhe", [dated])], imdb_matches={base.key: base, rich.key: rich})
    assert output.count('href="https://www.imdb.com/title/tt33764258/"') == 2


def test_html_cinema_themes_are_progressive_and_accessible():
    output = html([])
    soup = BeautifulSoup(output, "html.parser")
    css, script = soup.style.string, soup.script.string
    assert soup.body["data-active-cinema"] == "schauburg"
    for cinema_id, primary in (("schauburg", "#0f766e"), ("filmpalast", "#1e3a8a"), ("universum", "#b91c1c")):
        assert f'body[data-active-cinema="{cinema_id}"]' in css
        assert f'.cinema-panel[data-cinema="{cinema_id}"]' in css
        assert primary in css
    assert "document.body.dataset.activeCinema=id" in script
    assert "border-bottom-width: 6px" in css and ":focus-visible" in css
    assert "text-decoration: underline" in css and ".format-badge" in css
    assert "--positive" in css and "--warning" in css and "--danger" in css
    assert "prefers-color-scheme: dark" in css and "prefers-reduced-motion: reduce" in css
    for cinema_id, accent, strong in (("schauburg", "#5eead4", "#99f6e4"), ("filmpalast", "#93c5fd", "#bfdbfe"), ("universum", "#fca5a5", "#fecaca")):
        assert f'body[data-active-cinema="{cinema_id}"] {{ --accent: {accent}; --accent-dark: {strong};' in css
        assert f'.cinema-panel[data-cinema="{cinema_id}"] {{ --panel-accent: {accent}; --panel-dark: {strong};' in css
    assert "http" not in script and "Film" not in script


def test_html_includes_visible_tmdb_footer_attribution():
    output = html([])
    soup = BeautifulSoup(output, "html.parser")
    footer = soup.footer
    credits = footer.select_one("section.credits")
    logo_link = credits.select_one('a.tmdb-link[href="https://www.themoviedb.org/"]')

    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in footer.get_text()
    assert "TMDb wird zur Zuordnung von Kinotiteln zu IMDb-Einträgen verwendet." in footer.get_text()
    assert "nicht mit Schauburg, Filmpalast, Universum, IMDb oder TMDb verbunden" in footer.get_text()
    assert logo_link["aria-label"] == "TMDb öffnen"
    assert logo_link.select_one("svg.tmdb-logo[aria-hidden=true]") is not None

    css = soup.style.string
    logo_rule = css.split(".tmdb-logo {", 1)[1].split("}", 1)[0]
    assert "--accent" not in logo_rule
    assert "@media (prefers-color-scheme: dark)" in css and ".credits" in css
    assert "TMDB API" not in soup.script.string

"""Letterboxd crowd-rating backfill: parsing, slug resolution, resume, isolation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import Movie, Profile, ProfileSync
from backend.services.letterboxd_ratings import (
    LetterboxdRatingError,
    LetterboxdRatingFetcher,
    LetterboxdRatingParseError,
    parse_rating_histogram,
    resolve_slug,
    sync_letterboxd_ratings,
)


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


# ---------------------------------------------------------------------------
# Fixtures of the real CSI include shape (letterboxd.com/csi/film/<slug>/rating-histogram/).
# Trimmed to three of the ten half-star buckets; every attribute form is verbatim.
# ---------------------------------------------------------------------------

_BUCKETS = """
<tr class="column" style="--value: 0.012379758286082376;">
  <th scope="row" class="_sr-only">★★</th>
  <td class="cell">
    <a href="/film/the-dark-knight/ratings/rated/2/by/rating/" class="barcolumn tooltip" title="27,617 ★★ ratings (1%)">
      <span class="_sr-only">27.6K (1%)</span>
      <span class="bar"><span class="fill"></span></span>
    </a>
  </td>
</tr>
<tr class="column" style="--value: 0.4703254723937711;">
  <th scope="row" class="_sr-only">★★★★</th>
  <td class="cell">
    <a href="/film/the-dark-knight/ratings/rated/4/by/rating/" class="barcolumn tooltip" title="1,049,211 ★★★★ ratings (23%)">
      <span class="_sr-only">1M (23%)</span>
      <span class="bar"><span class="fill"></span></span>
    </a>
  </td>
</tr>
<tr class="column" style="--value: 1.0;">
  <th scope="row" class="_sr-only">★★★★★</th>
  <td class="cell">
    <a href="/film/the-dark-knight/ratings/rated/5/by/rating/" class="barcolumn tooltip" title="2,230,819 ★★★★★ ratings (48%)">
      <span class="_sr-only">2.2M (48%)</span>
      <span class="bar"><span class="fill"></span></span>
    </a>
  </td>
</tr>
"""


def _histogram(average_anchor: str = "") -> str:
    return f"""
<div class="rating-histogram"> <div class="layout">
<table class="chart">
  <caption class="_sr-only">Rating Distribution</caption>
  <tbody class="plot">{_BUCKETS}</tbody>
</table>
{average_anchor}
</div> </div>
"""


HISTOGRAM_WITH_AVERAGE = _histogram(
    '<a href="/film/the-dark-knight/ratings/" class="averagerating tooltip"'
    ' title="Weighted average of 4.50 based on 4,609,944 ratings"> 4.5 </a>'
)
# Letterboxd withholds the weighted average until a film has enough ratings.
HISTOGRAM_WITHOUT_AVERAGE = _histogram()
# A film with no ratings at all: the include is served 200 but is blank.
EMPTY_INCLUDE = "\n\n\n"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_weighted_average_line_is_the_source_of_truth():
    parsed = parse_rating_histogram(HISTOGRAM_WITH_AVERAGE)
    assert parsed.average == 4.5
    assert parsed.count == 4_609_944
    assert parsed.is_known is True


def test_abbreviated_bucket_labels_are_never_used_as_the_count():
    # "2.2M" and "27.6K" appear in the same document; the count must come from
    # the weighted-average phrase, which is exact.
    assert "2.2M" in HISTOGRAM_WITH_AVERAGE and "27.6K" in HISTOGRAM_WITH_AVERAGE
    parsed = parse_rating_histogram(HISTOGRAM_WITH_AVERAGE)
    assert parsed.count == 4_609_944
    assert parsed.count not in (22, 2_200_000, 27_600, 2_230_819, 1_049_211)


def test_thousands_separators_and_singular_rating_are_parsed():
    document = _histogram(
        '<a class="averagerating tooltip"'
        ' title="Weighted average of 2.75 based on 1,234,567 ratings"> 2.8 </a>'
    )
    assert parse_rating_histogram(document).count == 1_234_567

    singular = _histogram(
        '<a class="averagerating tooltip"'
        ' title="Weighted average of 3.00 based on 1 rating"> 3.0 </a>'
    )
    parsed = parse_rating_histogram(singular)
    assert (parsed.average, parsed.count) == (3.0, 1)


def test_histogram_without_an_average_is_unknown_not_zero():
    parsed = parse_rating_histogram(HISTOGRAM_WITHOUT_AVERAGE)
    assert parsed.average is None
    assert parsed.count is None
    assert parsed.is_known is False


def test_blank_and_missing_includes_are_unknown():
    for document in (EMPTY_INCLUDE, "", None):
        parsed = parse_rating_histogram(document)
        assert (parsed.average, parsed.count) == (None, None)


def test_html_entities_in_the_phrase_are_tolerated():
    document = _histogram(
        '<a class="averagerating tooltip"'
        ' title="Weighted&nbsp;average of 4.05 based on 12,000 ratings"> 4.1 </a>'
    )
    parsed = parse_rating_histogram(document)
    assert (parsed.average, parsed.count) == (4.05, 12_000)


def test_out_of_scale_average_is_loud_markup_drift():
    document = _histogram(
        '<a class="averagerating tooltip"'
        ' title="Weighted average of 45.0 based on 10 ratings"> 45 </a>'
    )
    with pytest.raises(LetterboxdRatingParseError):
        parse_rating_histogram(document)


# ---------------------------------------------------------------------------
# Slug resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "url", "expected"),
    [
        ("the-dark-knight", None, "the-dark-knight"),
        (None, "https://letterboxd.com/film/parasite-2019/", "parasite-2019"),
        (None, "/film/interstellar/", "interstellar"),
        ("", "https://letterboxd.com/film/abigail-2024/", "abigail-2024"),
        ("  the-dark-knight  ", None, "the-dark-knight"),
        (None, "https://letterboxd.com/whiteknight03x/", None),
        (None, None, None),
        ("", "", None),
    ],
)
def test_slug_resolution_falls_back_to_the_film_url(slug, url, expected):
    assert resolve_slug(slug, url) == expected


# ---------------------------------------------------------------------------
# Fetching (no network: a fake session stands in for curl_cffi)
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeHTTPSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _fetcher(responses, **overrides):
    sleeps = []
    kwargs = {
        "session": FakeHTTPSession(responses),
        "impersonates": False,
        "backoff_seconds": 2.0,
        "sleeper": sleeps.append,
    }
    kwargs.update(overrides)
    return LetterboxdRatingFetcher(**kwargs), sleeps


def test_transient_failure_is_retried_with_exponential_backoff():
    fetcher, sleeps = _fetcher(
        [FakeResponse(503), ConnectionError("reset"), FakeResponse(200, HISTOGRAM_WITH_AVERAGE)]
    )
    assert parse_rating_histogram(fetcher.fetch("the-dark-knight")).average == 4.5
    assert sleeps == [2.0, 4.0]


def test_missing_film_page_is_terminal_and_not_retried():
    fetcher, sleeps = _fetcher([FakeResponse(404, "Not Found")])
    assert fetcher.fetch("no-such-film") is None
    assert sleeps == []


def test_exhausted_retries_raise_rather_than_return_a_bad_value():
    fetcher, _ = _fetcher([FakeResponse(500)] * 3, max_retries=3)
    with pytest.raises(LetterboxdRatingError):
        fetcher.fetch("the-dark-knight")


def test_requested_url_is_the_lightweight_csi_include():
    session = FakeHTTPSession([FakeResponse(200, HISTOGRAM_WITH_AVERAGE)])
    LetterboxdRatingFetcher(session=session, impersonates=False, sleeper=lambda _: None).fetch(
        "the-dark-knight"
    )
    assert session.calls == [
        "https://letterboxd.com/csi/film/the-dark-knight/rating-histogram/"
    ]


# ---------------------------------------------------------------------------
# Persistence, resume and isolation
# ---------------------------------------------------------------------------


@pytest.fixture()
def database() -> Session:
    engine = create_engine("sqlite:///:memory:")
    for table in (Profile.__table__, ProfileSync.__table__, Movie.__table__):
        table.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _add_movie(db: Session, movie_id: int, title: str, **overrides) -> Movie:
    values = {
        "id": movie_id,
        "canonical_key": f"test:{movie_id}",
        "title": title,
        "normalized_title": title.casefold(),
        "letterboxd_slug": title.casefold().replace(" ", "-"),
        "letterboxd_url": None,
    }
    values.update(overrides)
    movie = Movie(**values)
    db.add(movie)
    db.commit()
    return movie


class ScriptedFetcher:
    """Returns a queued document (or raises) per slug; records call order."""

    def __init__(self, by_slug):
        self.by_slug = dict(by_slug)
        self.calls = []

    def fetch(self, slug):
        self.calls.append(slug)
        outcome = self.by_slug[slug]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_successful_sync_writes_average_count_and_stamp(database):
    _add_movie(database, 1, "The Dark Knight", letterboxd_slug="the-dark-knight")
    fetcher = ScriptedFetcher({"the-dark-knight": HISTOGRAM_WITH_AVERAGE})

    stats = sync_letterboxd_ratings(database, fetcher, sleeper=lambda _: None)

    movie = database.get(Movie, 1)
    assert movie.letterboxd_average_rating == 4.5
    assert movie.letterboxd_rating_count == 4_609_944
    assert movie.letterboxd_rating_synced_at is not None
    assert (stats.selected, stats.updated, stats.failed) == (1, 1, 0)


def test_confirmed_absence_stamps_the_attempt_so_dead_films_are_not_retried(database):
    _add_movie(database, 1, "Shrek 5", letterboxd_slug="shrek-5")
    _add_movie(database, 2, "Gone", letterboxd_slug="gone-film")
    fetcher = ScriptedFetcher({"shrek-5": EMPTY_INCLUDE, "gone-film": None})

    stats = sync_letterboxd_ratings(database, fetcher, sleeper=lambda _: None)

    assert stats.unavailable == 2 and stats.updated == 0 and stats.failed == 0
    for movie_id in (1, 2):
        movie = database.get(Movie, movie_id)
        assert movie.letterboxd_average_rating is None
        assert movie.letterboxd_rating_count is None
        assert movie.letterboxd_rating_synced_at is not None

    # A second run inside the max-age window has nothing left to do.
    resumed = sync_letterboxd_ratings(
        database, ScriptedFetcher({}), sleeper=lambda _: None
    )
    assert resumed.selected == 0


def test_a_failed_fetch_does_not_corrupt_existing_values_or_stop_the_run(database):
    stamped = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _add_movie(
        database,
        1,
        "Interstellar",
        letterboxd_slug="interstellar",
        letterboxd_average_rating=4.36,
        letterboxd_rating_count=1_000_000,
        letterboxd_rating_synced_at=stamped,
    )
    _add_movie(database, 2, "Parasite", letterboxd_slug="parasite-2019")
    fetcher = ScriptedFetcher(
        {
            "interstellar": LetterboxdRatingError("boom"),
            "parasite-2019": HISTOGRAM_WITH_AVERAGE,
        }
    )

    stats = sync_letterboxd_ratings(
        database, fetcher, refresh=True, sleeper=lambda _: None
    )

    failed = database.get(Movie, 1)
    assert failed.letterboxd_average_rating == 4.36
    assert failed.letterboxd_rating_count == 1_000_000
    # The stale stamp survives too, so the film is retried on the next run.
    assert failed.letterboxd_rating_synced_at.replace(tzinfo=timezone.utc) == stamped

    # The run continued past the failure.
    assert database.get(Movie, 2).letterboxd_average_rating == 4.5
    assert (stats.failed, stats.updated) == (1, 1)
    assert stats.errors[0]["movie_id"] == 1


def test_unknown_result_never_overwrites_a_known_average(database):
    _add_movie(
        database,
        1,
        "Interstellar",
        letterboxd_slug="interstellar",
        letterboxd_average_rating=4.36,
        letterboxd_rating_count=1_000_000,
    )
    fetcher = ScriptedFetcher({"interstellar": HISTOGRAM_WITHOUT_AVERAGE})

    stats = sync_letterboxd_ratings(database, fetcher, sleeper=lambda _: None)

    movie = database.get(Movie, 1)
    assert movie.letterboxd_average_rating == 4.36
    assert movie.letterboxd_rating_count == 1_000_000
    assert movie.letterboxd_rating_synced_at is not None
    assert stats.unavailable == 1


def test_films_without_any_slug_are_reported_and_never_fetched(database):
    _add_movie(database, 1, "No Identity", letterboxd_slug=None, letterboxd_url=None)
    _add_movie(
        database,
        2,
        "Url Only",
        letterboxd_slug=None,
        letterboxd_url="https://letterboxd.com/film/url-only-1999/",
    )
    fetcher = ScriptedFetcher({"url-only-1999": HISTOGRAM_WITH_AVERAGE})

    stats = sync_letterboxd_ratings(database, fetcher, sleeper=lambda _: None)

    assert stats.skipped_no_slug == 1
    assert stats.selected == 1
    assert fetcher.calls == ["url-only-1999"]
    assert database.get(Movie, 2).letterboxd_average_rating == 4.5


def test_fresh_stamps_are_skipped_and_expired_ones_are_refetched(database):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _add_movie(
        database,
        1,
        "Fresh",
        letterboxd_slug="fresh",
        letterboxd_rating_synced_at=now - timedelta(days=3),
    )
    _add_movie(
        database,
        2,
        "Expired",
        letterboxd_slug="expired",
        letterboxd_rating_synced_at=now - timedelta(days=45),
    )
    fetcher = ScriptedFetcher({"expired": HISTOGRAM_WITH_AVERAGE})

    stats = sync_letterboxd_ratings(
        database, fetcher, max_age_days=30, now=now, sleeper=lambda _: None
    )

    assert fetcher.calls == ["expired"]
    assert stats.selected == 1 and stats.updated == 1


def test_refresh_overrides_a_fresh_stamp(database):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _add_movie(
        database,
        1,
        "Fresh",
        letterboxd_slug="fresh",
        letterboxd_rating_synced_at=now - timedelta(days=1),
    )
    fetcher = ScriptedFetcher({"fresh": HISTOGRAM_WITH_AVERAGE})

    stats = sync_letterboxd_ratings(
        database, fetcher, refresh=True, now=now, sleeper=lambda _: None
    )

    assert fetcher.calls == ["fresh"] and stats.updated == 1


def test_limit_bounds_the_run_and_never_synced_films_go_first(database):
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _add_movie(
        database,
        1,
        "Recently Expired",
        letterboxd_slug="recently-expired",
        letterboxd_rating_synced_at=now - timedelta(days=31),
    )
    _add_movie(
        database,
        2,
        "Long Expired",
        letterboxd_slug="long-expired",
        letterboxd_rating_synced_at=now - timedelta(days=400),
    )
    _add_movie(database, 3, "Never Synced", letterboxd_slug="never-synced")
    fetcher = ScriptedFetcher(
        {"never-synced": HISTOGRAM_WITH_AVERAGE, "long-expired": HISTOGRAM_WITH_AVERAGE}
    )

    stats = sync_letterboxd_ratings(
        database, fetcher, limit=2, now=now, sleeper=lambda _: None
    )

    assert fetcher.calls == ["never-synced", "long-expired"]
    assert stats.selected == 2
    assert database.get(Movie, 1).letterboxd_rating_synced_at.replace(
        tzinfo=timezone.utc
    ) == now - timedelta(days=31)


def test_requests_are_paced_between_films(database):
    _add_movie(database, 1, "One", letterboxd_slug="one")
    _add_movie(database, 2, "Two", letterboxd_slug="two")
    _add_movie(database, 3, "Three", letterboxd_slug="three")
    fetcher = ScriptedFetcher({slug: HISTOGRAM_WITH_AVERAGE for slug in ("one", "two", "three")})
    sleeps = []

    sync_letterboxd_ratings(database, fetcher, delay_seconds=1.5, sleeper=sleeps.append)

    # One sleep between requests, none before the first or after the last.
    assert sleeps == [1.5, 1.5]


def test_dry_run_counts_candidates_without_a_fetcher_or_writes(database):
    _add_movie(database, 1, "The Dark Knight", letterboxd_slug="the-dark-knight")
    _add_movie(database, 2, "No Identity", letterboxd_slug=None, letterboxd_url=None)

    stats = sync_letterboxd_ratings(database, None, dry_run=True)

    assert (stats.selected, stats.skipped_no_slug, stats.dry_run) == (1, 1, True)
    assert database.get(Movie, 1).letterboxd_rating_synced_at is None


def test_movie_id_filter_restricts_the_run(database):
    _add_movie(database, 1, "One", letterboxd_slug="one")
    _add_movie(database, 2, "Two", letterboxd_slug="two")
    fetcher = ScriptedFetcher({"two": HISTOGRAM_WITH_AVERAGE})

    stats = sync_letterboxd_ratings(
        database, fetcher, movie_ids=[2], sleeper=lambda _: None
    )

    assert fetcher.calls == ["two"] and stats.selected == 1
    assert database.get(Movie, 1).letterboxd_rating_synced_at is None


def test_markup_drift_is_counted_as_a_failure_not_a_silent_zero(database):
    _add_movie(database, 1, "Drifted", letterboxd_slug="drifted")
    drifted = _histogram(
        '<a class="averagerating tooltip"'
        ' title="Weighted average of 9.10 based on 4,609,944 ratings"> 9.1 </a>'
    )
    fetcher = ScriptedFetcher({"drifted": drifted})

    stats = sync_letterboxd_ratings(database, fetcher, sleeper=lambda _: None)

    assert stats.failed == 1 and stats.updated == 0 and stats.unavailable == 0
    movie = database.get(Movie, 1)
    assert movie.letterboxd_average_rating is None
    assert movie.letterboxd_rating_synced_at is None

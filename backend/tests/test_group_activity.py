"""Group rhythm and first-watch order: what the panels are allowed to claim.

Every assertion here is about a boundary the redesign's copy promises — an
undated entry is excluded rather than placed on a guessed day, an import
artifact is set aside rather than reported as somebody's biggest day, and a tie
credits neither side rather than both.
"""
from __future__ import annotations

from datetime import date
from itertools import count
from typing import Optional

import pytest
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Movie, MovieEnrichment, Profile, ProfileFilm, WatchEvent
from services.first_watches import build_first_watch_order, build_shared_firsts
from services.group_activity import (
    build_logging_lag,
    build_marathons,
    build_season_shape,
    build_weekday_rhythm,
)


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
    Profile.__table__,
    Movie.__table__,
    ProfileFilm.__table__,
    WatchEvent.__table__,
    MovieEnrichment.__table__,
)


@pytest.fixture()
def database() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in TABLES:
        table.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


_MOVIE_IDS = count(1)
_EVENT_IDS = count(1)


def _profile(database: Session, username: str) -> Profile:
    profile = Profile(username=username, scraping_status="completed", is_active=True)
    database.add(profile)
    database.commit()
    return profile


def _movie(database: Session, title: str, *, runtime: Optional[int] = 100) -> Movie:
    movie_id = next(_MOVIE_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{title}-{movie_id}",
        title=title,
        normalized_title=title.casefold(),
        release_year=2000,
    )
    database.add(movie)
    if runtime is not None:
        database.add(MovieEnrichment(movie_id=movie_id, runtime_minutes=runtime))
    database.commit()
    return movie


def _watch(
    database: Session,
    profile: Profile,
    movie: Movie,
    watched_date: Optional[date],
    *,
    logged_date: Optional[date] = None,
) -> None:
    database.add(
        WatchEvent(
            profile_id=profile.id,
            movie_id=movie.id,
            event_key=f"event-{next(_EVENT_IDS)}",
            watched_date=watched_date,
            logged_date=logged_date,
            source_kind="full_html_upload",
        )
    )
    database.commit()


def _film_row(
    database: Session,
    profile: Profile,
    movie: Movie,
    first_watched: Optional[date],
) -> None:
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie.id,
            tags=[],
            watch_count=1,
            first_watched_date=first_watched,
        )
    )
    database.commit()


def test_marathon_day_names_who_it_was(database: Session) -> None:
    viewer = _profile(database, "viewer")
    day = date(2026, 7, 26)
    for title in ("One", "Two", "Three"):
        _watch(database, viewer, _movie(database, title), day)

    result = build_marathons(database, [viewer])

    assert result["count"] == 1
    assert result["marathons"][0]["username"] == "viewer"
    assert result["marathons"][0]["films"] == 3


def test_a_day_holding_more_film_than_a_day_is_set_aside(database: Session) -> None:
    """An export that dates a backlog to its import day is not a viewing session.

    Reporting it as somebody's biggest day would be the panel's most obviously
    wrong number, so it is counted separately and named in the caveat.
    """

    viewer = _profile(database, "viewer")
    day = date(2026, 7, 26)
    # 20 two-hour films is 40 hours inside one day.
    for index in range(20):
        _watch(database, viewer, _movie(database, f"Backlog {index}", runtime=120), day)

    result = build_marathons(database, [viewer])

    assert result["count"] == 0
    assert result["import_artifact_days"] == 1
    assert "import artifact" in result["caveat"]


def test_weekday_rhythm_excludes_undated_films_and_says_so(database: Session) -> None:
    """`watch_events.watched_date` is NOT NULL, so an undated film reaches us as
    a `profile_films` row with no first-watch date and no event at all. That is
    what the coverage line has to count — counting undated events would always
    report zero and imply the weekday split covers everything."""

    viewer = _profile(database, "viewer")
    _watch(database, viewer, _movie(database, "Saturday"), date(2026, 8, 1))
    _film_row(database, viewer, _movie(database, "Undated"), None)

    result = build_weekday_rhythm(database, [viewer])

    assert result["total"] == 1
    assert result["undated"] == 1
    saturday = next(day for day in result["days"] if day["label"] == "Saturday")
    assert saturday["watches"] == 1
    assert "excluded rather than placed on a guessed day" in result["caveat"]


def test_season_shape_folds_every_year_onto_twelve_months(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _watch(database, viewer, _movie(database, "Oct 2024"), date(2024, 10, 3))
    _watch(database, viewer, _movie(database, "Oct 2025"), date(2025, 10, 9))
    _watch(database, viewer, _movie(database, "Dec 2025"), date(2025, 12, 9))

    result = build_season_shape(database, [viewer])

    october = result["months"][9]
    assert october["name"] == "October"
    assert october["watches"] == 2
    assert result["years_covered"] == 2
    assert result["busiest"] == "October"


def test_logging_lag_measures_only_what_carries_a_log_date(database: Session) -> None:
    """`logged_date` exists only on an official export.

    A scraped event has a watch date and nothing else, so it cannot contribute a
    lag. The response says how much of the selection was measurable rather than
    letting the buckets imply full coverage.
    """

    viewer = _profile(database, "viewer")
    _watch(
        database,
        viewer,
        _movie(database, "Exported"),
        date(2026, 7, 1),
        logged_date=date(2026, 7, 1),
    )
    _watch(database, viewer, _movie(database, "Scraped"), date(2026, 7, 2))

    result = build_logging_lag(database, [viewer])

    assert result["measured"] == 1
    assert result["total"] == 2
    same_day = next(bucket for bucket in result["buckets"] if bucket["label"] == "Same day")
    assert same_day["events"] == 1
    assert "official export only" in result["caveat"]


def test_first_watch_order_ignores_pairs_missing_a_date(database: Session) -> None:
    early = _profile(database, "early")
    late = _profile(database, "late")
    shared = _movie(database, "Shared")
    undated = _movie(database, "Undated")

    _film_row(database, early, shared, date(2024, 1, 1))
    _film_row(database, late, shared, date(2024, 6, 1))
    _film_row(database, early, undated, date(2024, 1, 1))
    _film_row(database, late, undated, None)

    result = build_first_watch_order(database, [early, late])

    by_name = {entry["username"]: entry for entry in result["profiles"]}
    assert by_name["early"]["firsts"] == 1
    assert by_name["early"]["comparable"] == 1
    assert by_name["late"]["firsts"] == 0
    assert result["undated_pairs"] == 1
    assert "excluded rather than assumed late" in result["caveat"]


def test_a_tie_credits_neither_side(database: Session) -> None:
    """Two people who first watched something on the same day both arrived
    first, which is the same as neither arriving first. Crediting both would
    push every share above what the comparable count can support."""

    left = _profile(database, "left")
    right = _profile(database, "right")
    shared = _movie(database, "Simultaneous")
    _film_row(database, left, shared, date(2024, 3, 14))
    _film_row(database, right, shared, date(2024, 3, 14))

    result = build_first_watch_order(database, [left, right])

    assert all(entry["firsts"] == 0 for entry in result["profiles"])
    assert all(entry["comparable"] == 1 for entry in result["profiles"])


def test_shared_firsts_needs_a_first_watch_date_on_both_sides(database: Session) -> None:
    left = _profile(database, "left")
    right = _profile(database, "right")
    together = _movie(database, "Together")
    half = _movie(database, "HalfDated")

    _film_row(database, left, together, date(2024, 3, 14))
    _film_row(database, right, together, date(2024, 3, 14))
    _film_row(database, left, half, date(2024, 3, 14))
    _film_row(database, right, half, None)

    result = build_shared_firsts(database, [left, right])

    assert result["count"] == 1
    entry = result["shared_firsts"][0]
    assert entry["title"] == "Together"
    assert entry["usernames"] == ["left", "right"]
    assert entry["date"] == "2024-03-14"


def test_shared_firsts_ignores_a_different_day(database: Session) -> None:
    left = _profile(database, "left")
    right = _profile(database, "right")
    apart = _movie(database, "Apart")
    _film_row(database, left, apart, date(2024, 3, 14))
    _film_row(database, right, apart, date(2024, 3, 15))

    assert build_shared_firsts(database, [left, right])["count"] == 0


def test_a_soft_removed_film_is_history_not_a_current_watch(database: Session) -> None:
    left = _profile(database, "left")
    right = _profile(database, "right")
    gone = _movie(database, "Gone")
    _film_row(database, left, gone, date(2024, 3, 14))
    _film_row(database, right, gone, date(2024, 3, 14))

    removed = (
        database.query(ProfileFilm)
        .filter(ProfileFilm.profile_id == right.id, ProfileFilm.movie_id == gone.id)
        .one()
    )
    removed.removed_at = date(2026, 1, 1)
    database.commit()

    assert build_shared_firsts(database, [left, right])["count"] == 0


def test_longest_marathon_days_are_longest_not_most_recent(database: Session) -> None:
    """Sorted by recency and then cut, the panel titled "longest marathon
    days" could be missing the longest days entirely."""

    viewer = _profile(database, "viewer")
    # An older, much bigger day, and a newer, smaller one.
    for index in range(6):
        _watch(database, viewer, _movie(database, f"Old {index}"), date(2024, 1, 5))
    for index in range(3):
        _watch(database, viewer, _movie(database, f"New {index}"), date(2026, 7, 1))

    result = build_marathons(database, [viewer], limit=1)

    assert result["marathons"][0]["films"] == 6
    assert result["marathons"][0]["date"] == "2024-01-05"
    # The count still reflects everything that qualified, not the slice.
    assert result["count"] == 2

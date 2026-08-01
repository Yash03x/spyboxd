"""Watchlist insights: a dead list ranked by the circle that already watched."""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.watchlist_insights import router as watchlist_insights_router
from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import (
    AppUser,
    Movie,
    MovieEnrichment,
    Profile,
    ProfileAccessRequest,
    ProfileFilm,
    UserTrackedProfile,
    WatchlistItem,
)
from services.watchlist_insights import (
    MAX_LIMIT,
    MAX_RATERS_LISTED,
    MAX_SECONDARY_ENTRIES,
    _clamp_limit,
    build_watchlist_insights,
    median_days_waiting,
)


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
    Profile.__table__,
    Movie.__table__,
    ProfileFilm.__table__,
    MovieEnrichment.__table__,
    WatchlistItem.__table__,
    AppUser.__table__,
    UserTrackedProfile.__table__,
    ProfileAccessRequest.__table__,
)

TODAY = date(2026, 8, 1)


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


def _profile(
    database: Session,
    username: str,
    *,
    is_active: bool = True,
    scraping_status: str = "completed",
) -> Profile:
    profile = Profile(
        username=username,
        scraping_status=scraping_status,
        is_active=is_active,
    )
    database.add(profile)
    database.commit()
    return profile


def _film(
    database: Session,
    title: str,
    *,
    year: Optional[int] = 2000,
    letterboxd_average: Optional[float] = None,
    genres: Optional[list[str]] = None,
) -> Movie:
    movie_id = next(_MOVIE_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{title}-{movie_id}",
        title=title,
        normalized_title=title.casefold(),
        release_year=year,
        letterboxd_url=f"https://letterboxd.com/film/{movie_id}/",
        letterboxd_average_rating=letterboxd_average,
    )
    database.add(movie)
    if genres is not None:
        database.add(
            MovieEnrichment(
                movie_id=movie_id,
                genres=[{"name": name} for name in genres],
                keywords=[],
                credits={},
                production_countries=[],
                raw_payload={},
            )
        )
    database.commit()
    return movie


def _watchlist(
    database: Session,
    profile: Profile,
    movie: Movie,
    *,
    added: Optional[date] = date(2026, 7, 2),
    removed: bool = False,
) -> WatchlistItem:
    item = WatchlistItem(
        profile_id=profile.id,
        movie_id=movie.id,
        added_date=added,
        removed_at=datetime(2026, 7, 20, tzinfo=timezone.utc) if removed else None,
    )
    database.add(item)
    database.commit()
    return item


def _watched(
    database: Session,
    profile: Profile,
    movie: Movie,
    *,
    rating: Optional[float] = None,
    liked: bool = False,
    removed: bool = False,
) -> None:
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie.id,
            rating=rating,
            is_liked=liked,
            tags=[],
            watch_count=1,
            rewatch_count=0,
            removed_at=datetime(2026, 7, 20, tzinfo=timezone.utc) if removed else None,
        )
    )
    database.commit()


def _circle(database: Session, size: int = 3) -> list[Profile]:
    return [_profile(database, f"other{index}") for index in range(size)]


def _queued(
    database: Session,
    subject: Profile,
    circle: list[Profile],
    title: str,
    *,
    other_ratings: list[Optional[float]],
    likes: Optional[list[bool]] = None,
    added: Optional[date] = date(2026, 7, 2),
    **film_kwargs: Any,
) -> Movie:
    """One film on the subject's watchlist that ``circle`` has already seen."""

    movie = _film(database, title, **film_kwargs)
    _watchlist(database, subject, movie, added=added)
    flags = likes or [False] * len(other_ratings)
    for profile, rating, liked in zip(circle, other_ratings, flags):
        _watched(database, profile, movie, rating=rating, liked=liked)
    return movie


def _insights(database: Session, profile: Profile, **kwargs: Any) -> dict:
    return build_watchlist_insights(database, profile, today=TODAY, **kwargs)


# --- only unwatched films are recommended -----------------------------------


def test_a_watchlist_film_the_profile_already_watched_is_not_a_candidate(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    stale = _queued(database, subject, circle, "Already Seen", other_ratings=[4.5, 4.5])
    _queued(database, subject, circle, "Still Waiting", other_ratings=[4.0, 4.0])
    # The member watched it after adding it; the watchlist row was never cleaned up.
    _watched(database, subject, stale, rating=5.0)

    payload = _insights(database, subject)

    assert [entry["title"] for entry in payload["recommendations"]] == ["Still Waiting"]
    assert [entry["title"] for entry in payload["longest_waiting"]] == ["Still Waiting"]
    # The stale row is out of the denominator too, not merely out of the list.
    assert payload["coverage"]["watchlist_films"] == 1


def test_a_library_row_that_was_later_removed_still_means_watched(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    dropped = _queued(database, subject, circle, "Dropped Later", other_ratings=[4.5])
    _watched(database, subject, dropped, rating=4.0, removed=True)

    payload = _insights(database, subject)

    assert payload["coverage"]["watchlist_films"] == 0
    assert payload["recommendations"] == []


def test_a_removed_watchlist_row_is_not_a_candidate(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    taken_off = _film(database, "Taken Off")
    _watchlist(database, subject, taken_off, removed=True)
    _watched(database, circle[0], taken_off, rating=5.0)
    _queued(database, subject, circle, "Kept", other_ratings=[3.0])

    payload = _insights(database, subject)

    assert payload["coverage"]["watchlist_films"] == 1
    assert [entry["title"] for entry in payload["recommendations"]] == ["Kept"]


# --- the group is other people ----------------------------------------------


def test_the_group_average_is_taken_over_other_members_only(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(database, subject, circle, "Group Verdict", other_ratings=[5.0, 4.0, 3.0])

    payload = _insights(database, subject)
    recommendation = payload["recommendations"][0]

    assert recommendation["group_average"] == 4.0
    assert recommendation["group_raters"] == 3
    assert [rater["username"] for rater in recommendation["raters"]] == [
        "other0",
        "other1",
        "other2",
    ]


def test_inactive_and_unfinished_profiles_are_not_part_of_the_group(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    trusted = _profile(database, "trusted")
    inactive = _profile(database, "inactive", is_active=False)
    pending = _profile(database, "pending", scraping_status="in_progress")
    movie = _film(database, "Mixed Sources")
    _watchlist(database, subject, movie)
    _watched(database, trusted, movie, rating=3.0)
    _watched(database, inactive, movie, rating=5.0, liked=True)
    _watched(database, pending, movie, rating=5.0, liked=True)

    payload = _insights(database, subject)
    recommendation = payload["recommendations"][0]

    assert recommendation["group_average"] == 3.0
    assert recommendation["group_raters"] == 1
    assert recommendation["liked_by"] == 0


def test_a_film_no_other_member_rated_is_never_recommended(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    # Seen by somebody, but nobody put a number on it.
    _queued(database, subject, circle, "Unrated By All", other_ratings=[None])
    _queued(database, subject, circle, "Rated Once", other_ratings=[2.5])

    payload = _insights(database, subject)

    assert [entry["title"] for entry in payload["recommendations"]] == ["Rated Once"]
    # It is still a real watchlist film: counted, and still shown as waiting.
    assert payload["coverage"]["watchlist_films"] == 2
    assert payload["coverage"]["rated_by_group"] == 1
    assert {entry["title"] for entry in payload["longest_waiting"]} == {
        "Unrated By All",
        "Rated Once",
    }


def test_one_other_rater_is_enough_to_rank_on(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(database, subject, circle, "Lone Verdict", other_ratings=[4.5])

    payload = _insights(database, subject)

    assert payload["recommendations"][0]["group_raters"] == 1
    assert payload["recommendations"][0]["group_average"] == 4.5


# --- ranking -----------------------------------------------------------------


def test_recommendations_rank_by_group_average_then_by_how_many_are_behind_it(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(database, subject, circle, "Thin Four Five", other_ratings=[4.5])
    _queued(database, subject, circle, "Backed Four Five", other_ratings=[4.5, 4.5, 4.5])
    _queued(database, subject, circle, "Merely Good", other_ratings=[3.5, 3.5])

    payload = _insights(database, subject)

    assert [entry["title"] for entry in payload["recommendations"]] == [
        "Backed Four Five",
        "Thin Four Five",
        "Merely Good",
    ]


def test_the_limit_trims_the_queue_without_reshuffling_it(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    for index, rating in enumerate([5.0, 4.5, 4.0, 3.5, 3.0]):
        _queued(database, subject, circle, f"Film {index}", other_ratings=[rating])

    payload = _insights(database, subject, limit=2)

    assert [entry["title"] for entry in payload["recommendations"]] == ["Film 0", "Film 1"]
    # Trimming the queue never trims the honesty about how big it was.
    assert payload["coverage"]["rated_by_group"] == 5


def test_limits_are_clamped_into_range() -> None:
    assert _clamp_limit(0) == 1
    assert _clamp_limit(MAX_LIMIT + 40) == MAX_LIMIT
    assert _clamp_limit("nonsense") == 20
    assert _clamp_limit(None) == 20


# --- raters and likes --------------------------------------------------------


def test_raters_are_capped_and_ordered_by_rating(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=8)
    _queued(
        database,
        subject,
        circle,
        "Crowded",
        other_ratings=[1.0, 5.0, 2.0, 4.5, 3.0, 4.0, 2.5, 3.5],
    )

    recommendation = _insights(database, subject)["recommendations"][0]

    assert recommendation["group_raters"] == 8
    assert len(recommendation["raters"]) == MAX_RATERS_LISTED
    ratings = [rater["rating"] for rater in recommendation["raters"]]
    assert ratings == sorted(ratings, reverse=True)
    assert ratings == [5.0, 4.5, 4.0, 3.5, 3.0, 2.5]


def test_a_like_without_a_rating_counts_as_a_like_and_not_as_a_rater(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(
        database,
        subject,
        circle,
        "Liked Quietly",
        other_ratings=[4.0, None, 4.0],
        likes=[True, True, False],
    )

    recommendation = _insights(database, subject)["recommendations"][0]

    assert recommendation["group_raters"] == 2
    assert recommendation["liked_by"] == 2


# --- the Letterboxd crowd average is optional -------------------------------


def test_the_letterboxd_average_is_null_until_the_backfill_reaches_the_film(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(
        database,
        subject,
        circle,
        "Backfilled",
        other_ratings=[4.0],
        letterboxd_average=3.87,
    )
    _queued(database, subject, circle, "Pending", other_ratings=[4.0])
    # A stored zero is the absence of a crowd rating, not a crowd score of zero.
    _queued(database, subject, circle, "Zeroed", other_ratings=[4.0], letterboxd_average=0.0)

    payload = _insights(database, subject)
    averages = {
        entry["title"]: entry["letterboxd_average"] for entry in payload["recommendations"]
    }

    assert averages == {"Backfilled": 3.87, "Pending": None, "Zeroed": None}
    assert payload["coverage"]["with_letterboxd_average"] == 1


# --- waiting time ------------------------------------------------------------


def test_days_waiting_counts_from_the_added_date(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(
        database,
        subject,
        circle,
        "Old Queue Entry",
        other_ratings=[4.0],
        added=date(2024, 8, 1),
    )

    recommendation = _insights(database, subject)["recommendations"][0]

    assert recommendation["added_date"] == "2024-08-01"
    assert recommendation["days_waiting"] == 730


def test_an_undated_row_has_an_unknown_wait_and_stays_out_of_the_totals(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(database, subject, circle, "Undated", other_ratings=[4.5], added=None)
    _queued(
        database,
        subject,
        circle,
        "Dated",
        other_ratings=[4.0],
        added=date(2026, 7, 22),
    )

    payload = _insights(database, subject)
    recommendation = next(
        entry for entry in payload["recommendations"] if entry["title"] == "Undated"
    )

    assert recommendation["added_date"] is None
    assert recommendation["days_waiting"] is None
    # Undated rows are absent from the wait statistics, never folded in as zero.
    assert [entry["title"] for entry in payload["longest_waiting"]] == ["Dated"]
    assert payload["totals"] == {"median_days_waiting": 10, "oldest_days_waiting": 10}


def test_wait_totals_are_unknown_when_nothing_carries_a_date(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(database, subject, circle, "Undated", other_ratings=[4.5], added=None)

    payload = _insights(database, subject)

    assert payload["longest_waiting"] == []
    assert payload["totals"] == {
        "median_days_waiting": None,
        "oldest_days_waiting": None,
    }


def test_longest_waiting_is_ordered_by_wait_and_capped(database: Session) -> None:
    subject = _profile(database, "subject")
    for index in range(MAX_SECONDARY_ENTRIES + 4):
        movie = _film(database, f"Queued {index:02d}")
        _watchlist(database, subject, movie, added=date(2026, 1, 1 + index))

    payload = _insights(database, subject)

    assert len(payload["longest_waiting"]) == MAX_SECONDARY_ENTRIES
    assert payload["longest_waiting"][0]["title"] == "Queued 00"
    waits = [entry["days_waiting"] for entry in payload["longest_waiting"]]
    assert waits == sorted(waits, reverse=True)


def test_a_future_added_date_is_zero_days_waiting_not_a_negative_one(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(
        database,
        subject,
        circle,
        "Clock Skew",
        other_ratings=[4.0],
        added=date(2026, 9, 1),
    )

    assert _insights(database, subject)["recommendations"][0]["days_waiting"] == 0


def test_the_median_wait_is_the_middle_of_the_dated_rows() -> None:
    assert median_days_waiting([]) is None
    assert median_days_waiting([5]) == 5
    assert median_days_waiting([1, 10, 100]) == 10
    # Half-day medians round up rather than to the nearest even day.
    assert median_days_waiting([10, 11]) == 11
    assert median_days_waiting([2, 3]) == 3


# --- genre skew --------------------------------------------------------------


def test_genre_skew_counts_the_unwatched_pile_not_the_recommended_slice(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    for index in range(3):
        _queued(
            database,
            subject,
            circle,
            f"Horror {index}",
            other_ratings=[None],
            genres=["Horror"],
        )
    _queued(database, subject, circle, "Rated Drama", other_ratings=[4.0], genres=["Drama"])
    _queued(database, subject, circle, "Unenriched", other_ratings=[4.0])

    payload = _insights(database, subject)

    assert payload["genre_skew"] == [
        {"label": "Horror", "count": 3},
        {"label": "Drama", "count": 1},
    ]
    # Films enrichment never reached simply contribute no genre.
    assert payload["coverage"]["watchlist_films"] == 5


def test_a_watched_film_does_not_skew_the_genres(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    seen = _queued(database, subject, circle, "Seen Horror", other_ratings=[4.0], genres=["Horror"])
    _watched(database, subject, seen)
    _queued(database, subject, circle, "Queued Drama", other_ratings=[4.0], genres=["Drama"])

    payload = _insights(database, subject)

    assert payload["genre_skew"] == [{"label": "Drama", "count": 1}]


# --- empty and degenerate profiles ------------------------------------------


def test_an_empty_watchlist_returns_a_complete_payload(database: Session) -> None:
    subject = _profile(database, "subject")

    payload = _insights(database, subject)

    assert payload == {
        "username": "subject",
        "coverage": {
            "watchlist_films": 0,
            "rated_by_group": 0,
            "with_letterboxd_average": 0,
        },
        "recommendations": [],
        "longest_waiting": [],
        "genre_skew": [],
        "totals": {"median_days_waiting": None, "oldest_days_waiting": None},
    }


def test_another_profiles_watchlist_never_leaks_into_this_one(database: Session) -> None:
    subject = _profile(database, "subject")
    neighbour = _profile(database, "neighbour")
    circle = _circle(database)
    theirs = _film(database, "Their Queue")
    _watchlist(database, neighbour, theirs)
    _watched(database, circle[0], theirs, rating=5.0)
    _queued(database, subject, circle, "My Queue", other_ratings=[3.0])

    payload = _insights(database, subject)

    assert [entry["title"] for entry in payload["recommendations"]] == ["My Queue"]
    assert payload["coverage"]["watchlist_films"] == 1


# --- bulk loading ------------------------------------------------------------


def test_the_payload_costs_the_same_number_of_queries_at_any_size(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(database, subject, circle, "Only Film", other_ratings=[4.0, 3.5], genres=["Drama"])

    statements: list[str] = []

    @event.listens_for(database.get_bind(), "before_cursor_execute")
    def _record(_conn, _cursor, statement, *_args):  # noqa: ANN001
        statements.append(statement)

    _insights(database, subject)
    small = len(statements)
    statements.clear()

    for index in range(40):
        _queued(
            database,
            subject,
            circle,
            f"Bulk {index:02d}",
            other_ratings=[4.0, 3.0, 2.0],
            genres=["Drama", "Thriller"],
        )
    statements.clear()
    _insights(database, subject)
    large = len(statements)

    assert small == large, statements


# --- route -------------------------------------------------------------------


@pytest.fixture()
def app(database: Session) -> FastAPI:
    """The router as the orchestrator will mount it, on its own app.

    ``backend/main.py`` wires routers in a later phase, so this exercises the
    router itself -- its path, its query validation and its auth dependency --
    without depending on that registration having happened yet.
    """

    application = FastAPI()
    application.include_router(watchlist_insights_router)
    application.dependency_overrides[get_db] = lambda: database
    return application


def _tracked_user(database: Session, profile: Optional[Profile]) -> ClerkUser:
    app_user = AppUser(clerk_user_id="user_one", primary_profile_required=False)
    database.add(app_user)
    database.flush()
    if profile is not None:
        database.add(
            UserTrackedProfile(
                user_id=app_user.id,
                profile_id=profile.id,
                source="direct",
            )
        )
    database.commit()
    return ClerkUser(
        user_id="user_one",
        session_id="session",
        is_admin=False,
        letterboxd_username=None,
    )


def test_route_serves_the_payload_for_a_tracked_profile(
    database: Session,
    app: FastAPI,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _queued(
        database,
        subject,
        circle,
        "Tracked Film",
        other_ratings=[4.5, 4.0],
        likes=[True, False],
        letterboxd_average=4.1,
        genres=["Drama"],
    )
    user = _tracked_user(database, subject)
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/api/profiles/subject/watchlist-insights")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "username",
        "coverage",
        "recommendations",
        "longest_waiting",
        "genre_skew",
        "totals",
    }
    assert set(payload["coverage"]) == {
        "watchlist_films",
        "rated_by_group",
        "with_letterboxd_average",
    }
    assert set(payload["recommendations"][0]) == {
        "title",
        "year",
        "poster_url",
        "letterboxd_url",
        "group_average",
        "group_raters",
        "liked_by",
        "letterboxd_average",
        # The distribution behind the average: two films can share a mean while
        # one has a real chance of being loved and the other reliably does not.
        "crowd_ceiling",
        "crowd_floor",
        "added_date",
        "days_waiting",
        "raters",
    }
    assert set(payload["recommendations"][0]["raters"][0]) == {"username", "rating"}
    assert set(payload["longest_waiting"][0]) == {
        "title",
        "year",
        "poster_url",
        "letterboxd_url",
        "added_date",
        "days_waiting",
    }
    assert set(payload["genre_skew"][0]) == {"label", "count"}
    assert set(payload["totals"]) == {"median_days_waiting", "oldest_days_waiting"}
    assert payload["recommendations"][0]["group_average"] == 4.25
    assert payload["recommendations"][0]["liked_by"] == 1
    assert payload["recommendations"][0]["letterboxd_url"].startswith("https://letterboxd.com/")


def test_route_honours_the_limit_query_parameter(
    database: Session,
    app: FastAPI,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    for index in range(4):
        _queued(database, subject, circle, f"Film {index}", other_ratings=[4.0])
    user = _tracked_user(database, subject)
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    response = client.get("/api/profiles/subject/watchlist-insights?limit=2")
    rejected = client.get(f"/api/profiles/subject/watchlist-insights?limit={MAX_LIMIT + 1}")

    assert response.status_code == 200
    assert len(response.json()["recommendations"]) == 2
    assert rejected.status_code == 422


def test_route_refuses_an_untracked_profile(database: Session, app: FastAPI) -> None:
    _profile(database, "subject")
    user = _tracked_user(database, None)
    app.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(app).get("/api/profiles/subject/watchlist-insights")

    assert response.status_code == 403


def test_route_requires_an_authenticated_user() -> None:
    route = next(
        route
        for route in watchlist_insights_router.routes
        if route.path == "/api/profiles/{username}/watchlist-insights"
    )

    assert "get_current_user" in {
        dependency.call.__name__ for dependency in route.dependant.dependencies
    }


def test_a_lone_five_star_does_not_outrank_a_corroborated_favourite(
    database: Session,
) -> None:
    """Ranking must weigh how many people vouched for a film.

    Sorting on the raw group average put a single 5.0 above a five-person
    4.6, which is the opposite of a useful recommendation: across the real
    tracked set most of what surfaced that way rested on one rater.
    """
    subject = _profile(database, "viewer")
    circle = _circle(database, size=5)
    # The circle needs a normal rating history, or the baseline the ranking
    # shrinks toward is just the mean of these two films and cannot separate
    # them. Real circles average around 3.5.
    for index in range(6):
        background = _film(database, f"Background {index}")
        for profile in circle:
            _watched(database, profile, background, rating=3.5)
    _queued(database, subject, circle, "Lone Favourite", other_ratings=[5.0])
    _queued(
        database,
        subject,
        circle,
        "Crowd Favourite",
        other_ratings=[4.5, 4.5, 4.5, 5.0, 4.5],
    )

    result = _insights(database, subject)
    titles = [entry["title"] for entry in result["recommendations"]]
    assert titles.index("Crowd Favourite") < titles.index("Lone Favourite")

    # The raw figures stay honest, so the panel can still show both.
    rows = {entry["title"]: entry for entry in result["recommendations"]}
    assert rows["Lone Favourite"]["group_average"] == 5.0
    assert rows["Lone Favourite"]["group_raters"] == 1
    assert rows["Crowd Favourite"]["group_raters"] == 5


def test_the_crowd_shape_separates_two_films_with_the_same_average(
    database: Session,
) -> None:
    """A mean cannot tell a divisive film from a uniformly mediocre one."""
    subject = _profile(database, "viewer")
    circle = _circle(database, size=3)
    polarising = _queued(database, subject, circle, "Polarising", other_ratings=[4.0])
    flat = _queued(database, subject, circle, "Flat", other_ratings=[4.0])
    # Same crowd average, very different shapes.
    polarising.letterboxd_average_rating = 3.5
    polarising.letterboxd_rating_distribution = {
        "0.5": 50, "1.0": 50, "1.5": 0, "2.0": 100, "2.5": 0,
        "3.0": 100, "3.5": 0, "4.0": 100, "4.5": 300, "5.0": 300,
    }
    flat.letterboxd_average_rating = 3.5
    flat.letterboxd_rating_distribution = {
        "0.5": 0, "1.0": 0, "1.5": 0, "2.0": 0, "2.5": 200,
        "3.0": 300, "3.5": 400, "4.0": 100, "4.5": 0, "5.0": 0,
    }
    database.commit()

    entries = {
        entry["title"]: entry
        for entry in _insights(database, subject)["recommendations"]
    }

    assert entries["Polarising"]["crowd_ceiling"] > entries["Flat"]["crowd_ceiling"]
    assert entries["Polarising"]["crowd_floor"] > entries["Flat"]["crowd_floor"]
    assert entries["Flat"]["crowd_ceiling"] == 0.0


def test_a_film_with_no_histogram_reports_no_shape_rather_than_zero(
    database: Session,
) -> None:
    """"Nobody rated it highly" and "we have not looked" are different answers."""
    subject = _profile(database, "viewer")
    circle = _circle(database, size=3)
    _queued(database, subject, circle, "Unscraped", other_ratings=[4.0])

    entry = _insights(database, subject)["recommendations"][0]

    assert entry["crowd_ceiling"] is None
    assert entry["crowd_floor"] is None

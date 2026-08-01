"""Rating comparison: a profile measured against a circle it is not part of."""
from __future__ import annotations

from itertools import count
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from auth import ClerkUser
from backend import main as backend_main
from database.models import (
    AppUser,
    Movie,
    MovieEnrichment,
    Profile,
    ProfileAccessRequest,
    ProfileFilm,
    UserTrackedProfile,
)
from services.rating_comparison import MAX_LIMIT, _clamp_limit, build_rating_comparison


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
    Profile.__table__,
    Movie.__table__,
    ProfileFilm.__table__,
    MovieEnrichment.__table__,
    AppUser.__table__,
    UserTrackedProfile.__table__,
    ProfileAccessRequest.__table__,
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
    database.commit()
    return movie


def _rate(
    database: Session,
    profile: Profile,
    movie: Movie,
    rating: Optional[float],
) -> None:
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie.id,
            rating=rating,
            tags=[],
            watch_count=1,
            rewatch_count=0,
        )
    )
    database.commit()


def _circle(database: Session, size: int = 2) -> list[Profile]:
    return [_profile(database, f"other{index}") for index in range(size)]


def _shared(
    database: Session,
    subject: Profile,
    circle: list[Profile],
    title: str,
    *,
    subject_rating: Optional[float],
    other_ratings: list[Optional[float]],
    **film_kwargs: Any,
) -> Movie:
    """One film rated by the subject and by ``len(other_ratings)`` others."""

    movie = _film(database, title, **film_kwargs)
    _rate(database, subject, movie, subject_rating)
    for profile, rating in zip(circle, other_ratings):
        _rate(database, profile, movie, rating)
    return movie


# --- the group never contains the profile being measured --------------------


def test_the_group_average_excludes_the_profile_being_measured(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    # Both others said 3.0. Excluding the subject the group is exactly 3.0;
    # folding the subject in would drag it to 3.67 / 2.33 and halve both deltas.
    _shared(
        database,
        subject,
        circle,
        "Loved It",
        subject_rating=5.0,
        other_ratings=[3.0, 3.0],
    )
    _shared(
        database,
        subject,
        circle,
        "Hated It",
        subject_rating=1.0,
        other_ratings=[3.0, 3.0],
    )

    payload = build_rating_comparison(database, subject)

    assert payload["most_generous"][0]["title"] == "Loved It"
    assert payload["most_generous"][0]["group_average"] == 3.0
    assert payload["most_generous"][0]["delta"] == 2.0
    assert payload["most_harsh"][0]["title"] == "Hated It"
    assert payload["most_harsh"][0]["group_average"] == 3.0
    assert payload["most_harsh"][0]["delta"] == -2.0
    assert payload["summary"]["group_delta"] == 0.0
    assert payload["summary"]["lean"] == "aligned"


def test_a_profile_is_not_correlated_with_itself(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    # Everyone else rated every shared film 3.0, so the group has no variance
    # to agree or disagree with. Leaving the subject inside its own group
    # average would manufacture a perfect 1.0 correlation out of nothing.
    for title, rating in (("First", 5.0), ("Second", 4.0), ("Third", 2.0)):
        _shared(
            database,
            subject,
            circle,
            title,
            subject_rating=rating,
            other_ratings=[3.0, 3.0],
        )

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["compared_films"] == 3
    assert payload["summary"]["agreement"] is None
    assert payload["summary"]["group_delta"] == 0.67
    assert payload["summary"]["lean"] == "generous"


def test_agreement_needs_three_paired_films(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    for title, subject_rating, others in (
        ("Low", 1.0, [1.0, 1.5]),
        ("High", 5.0, [4.5, 5.0]),
    ):
        _shared(
            database,
            subject,
            circle,
            title,
            subject_rating=subject_rating,
            other_ratings=others,
        )

    # Two points always correlate perfectly; that is arithmetic, not agreement.
    assert build_rating_comparison(database, subject)["summary"]["agreement"] is None

    _shared(
        database,
        subject,
        circle,
        "Middle",
        subject_rating=3.0,
        other_ratings=[3.0, 3.5],
    )

    assert build_rating_comparison(database, subject)["summary"]["agreement"] == 1.0


# --- the two-other-raters floor ---------------------------------------------


def test_a_film_needs_two_other_raters_before_it_is_compared(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=2)
    _shared(
        database,
        subject,
        circle,
        "One Other Opinion",
        subject_rating=5.0,
        other_ratings=[1.0],
    )
    _shared(
        database,
        subject,
        circle,
        "An Actual Group",
        subject_rating=4.0,
        other_ratings=[3.0, 3.0],
    )

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["rated_films"] == 2
    assert payload["coverage"]["compared_films"] == 1
    assert payload["coverage"]["min_raters"] == 2
    # The lone-other film carried the bigger gap and is still excluded.
    assert [entry["title"] for entry in payload["most_generous"]] == ["An Actual Group"]
    assert payload["most_generous"][0]["rater_count"] == 2
    assert payload["summary"]["group_delta"] == 1.0


def test_an_unrated_row_is_not_a_rater(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _shared(
        database,
        subject,
        circle,
        "Logged But Unrated",
        subject_rating=5.0,
        other_ratings=[3.0, None],
    )

    payload = build_rating_comparison(database, subject)

    # Only one of the two others actually rated it, so it is not comparable.
    assert payload["coverage"]["compared_films"] == 0
    assert payload["summary"]["group_delta"] is None
    assert payload["summary"]["lean"] is None


def test_only_active_completed_profiles_count_towards_the_group(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    usable = _circle(database)
    pending = _profile(database, "pending", scraping_status="pending")
    retired = _profile(database, "retired", is_active=False)
    movie = _shared(
        database,
        subject,
        usable,
        "Shared",
        subject_rating=4.0,
        other_ratings=[3.0, 3.0],
    )
    _rate(database, pending, movie, 1.0)
    _rate(database, retired, movie, 1.0)

    payload = build_rating_comparison(database, subject)

    assert payload["most_generous"][0]["rater_count"] == 2
    assert payload["most_generous"][0]["group_average"] == 3.0


# --- Letterboxd is the only external reference ------------------------------


def test_letterboxd_delta_covers_every_rated_film_with_an_average(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    # Rated by the subject alone: no group to compare against, but Letterboxd's
    # crowd still has an opinion, so the film counts towards that reference.
    lonely = _film(database, "Solo Watch", letterboxd_average=3.0)
    _rate(database, subject, lonely, 4.0)
    _shared(
        database,
        subject,
        circle,
        "Shared Watch",
        subject_rating=3.0,
        other_ratings=[3.0, 3.0],
        letterboxd_average=3.5,
    )

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["letterboxd_average_films"] == 2
    # (4.0 - 3.0) and (3.0 - 3.5) average to +0.25.
    assert payload["summary"]["letterboxd_delta"] == 0.25
    assert payload["coverage"]["compared_films"] == 1


def test_a_zero_letterboxd_average_is_an_absent_opinion(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _shared(
        database,
        subject,
        circle,
        "Zeroed Out",
        subject_rating=4.0,
        other_ratings=[3.0, 3.0],
        letterboxd_average=0.0,
    )

    payload = build_rating_comparison(database, subject)

    # Letterboxd never publishes a 0.0 crowd average -- no film can be rated
    # below half a star -- so a stored zero is a missing figure. Comparing
    # against it would invent a +4.0 delta out of an absent opinion.
    assert payload["coverage"]["letterboxd_average_films"] == 0
    assert payload["summary"]["letterboxd_delta"] is None
    assert payload["most_generous"][0]["letterboxd_average"] is None


# --- Letterboxd degrades to null until its backfill lands -------------------


def test_letterboxd_fields_are_null_before_the_backfill(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _shared(
        database,
        subject,
        circle,
        "Unbackfilled",
        subject_rating=4.5,
        other_ratings=[3.0, 3.0],
    )

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["letterboxd_average_films"] == 0
    assert payload["summary"]["letterboxd_delta"] is None
    assert payload["most_generous"][0]["letterboxd_average"] is None
    # The local comparison is unaffected by the missing crowd average.
    assert payload["summary"]["group_delta"] == 1.5
    assert payload["summary"]["lean"] == "generous"


def test_letterboxd_delta_is_computed_once_the_average_exists(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _shared(
        database,
        subject,
        circle,
        "Backfilled",
        subject_rating=4.0,
        other_ratings=[3.0, 3.0],
        letterboxd_average=3.5,
    )
    _shared(
        database,
        subject,
        circle,
        "Still Pending",
        subject_rating=4.0,
        other_ratings=[3.0, 3.0],
    )

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["letterboxd_average_films"] == 1
    assert payload["summary"]["letterboxd_delta"] == 0.5
    assert payload["most_generous"][0]["letterboxd_average"] == 3.5
    assert payload["most_generous"][1]["letterboxd_average"] is None


# --- divisiveness is a property of the whole group --------------------------


def test_a_spread_needs_three_raters(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=2)
    _shared(
        database,
        subject,
        circle,
        "Two Raters Wide Apart",
        subject_rating=5.0,
        other_ratings=[1.0],
    )
    _shared(
        database,
        subject,
        circle,
        "Three Raters Close Together",
        subject_rating=4.5,
        other_ratings=[4.5, 4.0],
    )

    payload = build_rating_comparison(database, subject)

    # The four-star gap between two people is not a divided audience.
    assert [entry["title"] for entry in payload["most_divisive"]] == [
        "Three Raters Close Together"
    ]
    assert payload["most_divisive"][0]["rating_spread"] == 0.5
    assert payload["most_divisive"][0]["rater_count"] == 3


def test_divisiveness_is_the_group_spread_not_this_profiles_delta(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=3)
    _shared(
        database,
        subject,
        circle,
        "Split Down The Middle",
        subject_rating=3.0,
        other_ratings=[5.0, 1.0, 3.0],
    )
    _shared(
        database,
        subject,
        circle,
        "One Holdout",
        subject_rating=4.0,
        other_ratings=[5.0, 5.0, 2.0],
    )

    payload = build_rating_comparison(database, subject)

    # The subject sits on the group average for both films -- zero delta each --
    # yet both are contested, and the four-star split outranks the holdout.
    assert [entry["title"] for entry in payload["most_divisive"]] == [
        "Split Down The Middle",
        "One Holdout",
    ]
    assert payload["most_divisive"][0]["rating_spread"] == 4.0
    assert payload["most_divisive"][0]["rater_count"] == 4
    assert payload["most_divisive"][0]["profile_rating"] == 3.0
    assert payload["most_divisive"][1]["rating_spread"] == 3.0
    assert payload["most_generous"] == []
    assert payload["most_harsh"] == []


def test_a_divisive_film_the_profile_never_rated_reports_a_null_rating(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=3)
    _shared(
        database,
        subject,
        circle,
        "Logged Not Rated",
        subject_rating=None,
        other_ratings=[5.0, 3.0, 1.0],
    )

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["rated_films"] == 0
    entry = payload["most_divisive"][0]
    assert entry["profile_rating"] is None
    assert entry["rating_spread"] == 4.0
    assert entry["rater_count"] == 3
    assert entry["group_average"] == 3.0


# --- lean thresholds --------------------------------------------------------


@pytest.mark.parametrize(
    ("subject_rating", "expected_delta", "expected_lean"),
    [
        (3.5, 0.5, "generous"),
        (3.16, 0.16, "generous"),
        (3.15, 0.15, "aligned"),
        (3.0, 0.0, "aligned"),
        (2.85, -0.15, "aligned"),
        (2.84, -0.16, "harsh"),
        (2.5, -0.5, "harsh"),
    ],
)
def test_lean_thresholds(
    database: Session,
    subject_rating: float,
    expected_delta: float,
    expected_lean: str,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _shared(
        database,
        subject,
        circle,
        "Benchmark",
        subject_rating=subject_rating,
        other_ratings=[3.0, 3.0],
    )

    summary = build_rating_comparison(database, subject)["summary"]

    assert summary["group_delta"] == expected_delta
    # The lean reads the reported delta, so the label and the number agree.
    assert summary["lean"] == expected_lean


# --- list construction ------------------------------------------------------


def test_generous_and_harsh_lists_only_hold_films_pointing_that_way(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    for title, rating in (("Harsher", 1.0), ("Harsh", 2.0), ("Level", 3.0)):
        _shared(
            database,
            subject,
            circle,
            title,
            subject_rating=rating,
            other_ratings=[3.0, 3.0],
        )

    payload = build_rating_comparison(database, subject)

    # A uniformly harsh profile has no generous films; its least-harsh film is
    # not a generous one.
    assert payload["most_generous"] == []
    assert [entry["title"] for entry in payload["most_harsh"]] == ["Harsher", "Harsh"]
    assert payload["summary"]["lean"] == "harsh"


def test_lists_respect_the_limit(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=3)
    for index in range(15):
        _shared(
            database,
            subject,
            circle,
            f"Film {index:02d}",
            subject_rating=5.0,
            other_ratings=[1.0, 2.0, 3.0],
        )

    default_payload = build_rating_comparison(database, subject)
    limited = build_rating_comparison(database, subject, limit=3)

    assert len(default_payload["most_generous"]) == 10
    assert len(default_payload["most_divisive"]) == 10
    assert len(limited["most_generous"]) == 3
    assert len(limited["most_divisive"]) == 3
    # The coverage counts are never truncated by the display limit.
    assert limited["coverage"]["compared_films"] == 15


def test_the_limit_is_clamped_to_the_documented_range() -> None:
    assert _clamp_limit(None) == 10
    assert _clamp_limit(0) == 1
    assert _clamp_limit(500) == MAX_LIMIT
    assert _clamp_limit("not a number") == 10


def test_film_entries_carry_their_display_identity(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    movie = _shared(
        database,
        subject,
        circle,
        "Identified",
        subject_rating=5.0,
        other_ratings=[3.0, 3.0],
        year=1994,
    )

    entry = build_rating_comparison(database, subject)["most_generous"][0]

    assert entry["title"] == "Identified"
    assert entry["year"] == 1994
    assert entry["letterboxd_url"] == f"https://letterboxd.com/film/{movie.id}/"
    assert entry["poster_url"] is None


# --- graceful degradation ---------------------------------------------------


def test_a_profile_with_no_overlap_returns_a_valid_payload(database: Session) -> None:
    subject = _profile(database, "subject")
    _circle(database)
    for title in ("Alone One", "Alone Two"):
        movie = _film(database, title)
        _rate(database, subject, movie, 4.0)

    payload = build_rating_comparison(database, subject)

    assert payload["username"] == "subject"
    assert payload["coverage"] == {
        "rated_films": 2,
        "compared_films": 0,
        "min_raters": 2,
        "letterboxd_average_films": 0,
    }
    assert payload["summary"] == {
        "group_delta": None,
        "letterboxd_delta": None,
        "lean": None,
        "agreement": None,
    }
    assert payload["most_generous"] == []
    assert payload["most_harsh"] == []
    assert payload["most_divisive"] == []


def test_a_profile_with_no_films_at_all_returns_a_valid_payload(
    database: Session,
) -> None:
    subject = _profile(database, "subject")

    payload = build_rating_comparison(database, subject)

    assert payload["coverage"]["rated_films"] == 0
    assert payload["summary"]["group_delta"] is None
    assert payload["most_divisive"] == []


# --- route ------------------------------------------------------------------


@pytest.fixture()
def client(database: Session):
    backend_main.app.dependency_overrides[backend_main.get_db] = lambda: database
    try:
        yield lambda: TestClient(backend_main.app)
    finally:
        backend_main.app.dependency_overrides.clear()


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
    client,
) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    _shared(
        database,
        subject,
        circle,
        "Tracked Film",
        subject_rating=5.0,
        other_ratings=[3.0, 3.0],
    )
    user = _tracked_user(database, subject)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client().get("/api/profiles/subject/rating-comparison")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "username",
        "coverage",
        "summary",
        "most_generous",
        "most_harsh",
        "most_divisive",
    }
    assert set(payload["most_generous"][0]) == {
        "title",
        "year",
        "poster_url",
        "letterboxd_url",
        "profile_rating",
        "group_average",
        "delta",
        "rater_count",
        "letterboxd_average",
    }
    assert set(payload["most_divisive"][0]) == {
        "title",
        "year",
        "poster_url",
        "letterboxd_url",
        "rating_spread",
        # The spread spans every rater; the group average excludes the profile
        # being viewed. Each figure carries its own denominator.
        "rater_count",
        "group_rater_count",
        # How settled the wider crowd is, so a split this circle owns can be
        # told apart from a film the world argues about too.
        "crowd_consensus",
        "group_average",
        "profile_rating",
    }
    assert payload["summary"]["lean"] == "generous"


def test_route_honours_the_limit_query_parameter(database: Session, client) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database)
    for index in range(4):
        _shared(
            database,
            subject,
            circle,
            f"Film {index}",
            subject_rating=5.0,
            other_ratings=[3.0, 3.0],
        )
    user = _tracked_user(database, subject)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client().get("/api/profiles/subject/rating-comparison?limit=2")
    rejected = client().get("/api/profiles/subject/rating-comparison?limit=51")

    assert response.status_code == 200
    assert len(response.json()["most_generous"]) == 2
    assert rejected.status_code == 422


def test_route_refuses_an_untracked_profile(database: Session, client) -> None:
    _profile(database, "subject")
    user = _tracked_user(database, None)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client().get("/api/profiles/subject/rating-comparison")

    assert response.status_code == 403


def test_the_group_average_reports_its_own_denominator(database: Session) -> None:
    """The spread counts everyone; the group average excludes the viewer.

    One count served both, so a four-person average was presented beside
    "5 raters" and read as a five-person one.
    """
    subject = _profile(database, "subject")
    circle = _circle(database, size=4)
    _shared(database, subject, circle, "Argued About", subject_rating=1.0,
            other_ratings=[5.0, 4.5, 4.0, 3.5])

    payload = build_rating_comparison(database, subject, limit=5)
    entry = payload["most_divisive"][0]

    assert entry["rater_count"] == 5          # the spread spans all five
    assert entry["group_rater_count"] == 4    # the average is over the others
    assert entry["group_average"] == 4.25


def test_a_settled_crowd_is_distinguished_from_one_that_argues_too(
    database: Session,
) -> None:
    """A split this circle owns is more interesting than a split everyone has.

    Consensus is the share of the crowd sitting in the single most popular
    half-star bucket: a film the world agrees on concentrates there.
    """
    subject = _profile(database, "subject")
    circle = _circle(database, size=3)
    settled = _shared(database, subject, circle, "World Agrees",
                      subject_rating=1.0, other_ratings=[5.0, 4.5, 4.0])
    contested = _shared(database, subject, circle, "World Argues Too",
                        subject_rating=1.0, other_ratings=[5.0, 4.5, 4.0])
    settled.letterboxd_rating_distribution = {
        "0.5": 0, "1.0": 0, "1.5": 0, "2.0": 0, "2.5": 0,
        "3.0": 0, "3.5": 0, "4.0": 900, "4.5": 50, "5.0": 50,
    }
    contested.letterboxd_rating_distribution = {
        "0.5": 100, "1.0": 100, "1.5": 100, "2.0": 100, "2.5": 100,
        "3.0": 100, "3.5": 100, "4.0": 100, "4.5": 100, "5.0": 100,
    }
    database.commit()

    entries = {
        entry["title"]: entry
        for entry in build_rating_comparison(database, subject, limit=5)["most_divisive"]
    }

    assert entries["World Agrees"]["crowd_consensus"] == 0.9
    assert entries["World Argues Too"]["crowd_consensus"] == 0.1


def test_a_film_with_no_histogram_reports_no_consensus(database: Session) -> None:
    subject = _profile(database, "subject")
    circle = _circle(database, size=3)
    _shared(database, subject, circle, "Unscraped",
            subject_rating=1.0, other_ratings=[5.0, 4.5, 4.0])

    entry = build_rating_comparison(database, subject, limit=5)["most_divisive"][0]

    assert entry["crowd_consensus"] is None

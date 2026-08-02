"""Obscurity index: a taste measured in audience size, not in stars.

The properties under test are the ones that make the number honest: the median
resists a single blockbuster, unsynced films are absent rather than zero, the
percentile places a profile against peers it is not itself part of, and
``crowd_position`` degrades to an empty list while distributions are missing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.obscurity import router as obscurity_router
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
)
from services.obscurity import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    _clamp_limit,
    _percentile_vs_group,
    _share_at_or_below,
    build_obscurity_index,
)


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
    rating_count: Optional[int] = None,
    crowd_average: Optional[float] = None,
    distribution: Optional[Dict[str, int]] = None,
    year: Optional[int] = 2000,
) -> Movie:
    movie_id = next(_MOVIE_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{title}-{movie_id}",
        title=title,
        normalized_title=title.casefold(),
        release_year=year,
        letterboxd_url=f"https://letterboxd.com/film/{movie_id}/",
        letterboxd_rating_count=rating_count,
        letterboxd_average_rating=crowd_average,
        letterboxd_rating_distribution=distribution,
    )
    database.add(movie)
    database.commit()
    return movie


def _rate(
    database: Session,
    profile: Profile,
    movie: Movie,
    rating: Optional[float],
    *,
    removed_at: Any = None,
) -> None:
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie.id,
            rating=rating,
            tags=[],
            watch_count=1,
            rewatch_count=0,
            removed_at=removed_at,
        )
    )
    database.commit()


def _library(database: Session, profile: Profile, audiences, **film_kwargs) -> None:
    """Give a profile one rated film per audience size."""

    for index, audience in enumerate(audiences):
        movie = _film(
            database,
            f"{profile.username} film {index}",
            rating_count=audience,
            **film_kwargs,
        )
        _rate(database, profile, movie, 4.0)


# --- the median is the headline ---------------------------------------------


def test_one_blockbuster_cannot_drag_the_headline_off_an_obscure_taste(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    # Nine films nobody watched, and one everybody did.
    _library(database, subject, [800] * 9 + [6_000_000])

    payload = build_obscurity_index(database, subject)

    # The median stays where this person actually lives.
    assert payload["index"]["median_rating_count"] == 800
    # The mean is reported beside it precisely so the skew is visible: it lands
    # 750x above the typical film and describes a taste nobody here has.
    assert payload["index"]["mean_rating_count"] == 600_720


def test_an_even_library_takes_the_midpoint_of_the_two_middle_films(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [100, 200, 300, 500])

    assert build_obscurity_index(database, subject)["index"][
        "median_rating_count"
    ] == 250


def test_a_fractional_median_is_reported_as_a_whole_audience(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    # A midpoint of 150.5 people is not a thing; it rounds away from zero.
    _library(database, subject, [100, 201])

    assert build_obscurity_index(database, subject)["index"][
        "median_rating_count"
    ] == 151


# --- unknown is null, never zero --------------------------------------------


def test_films_the_backfill_has_not_reached_are_excluded_not_counted_as_zero(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [1_000, 1_000, 1_000])
    for index in range(7):
        movie = _film(database, f"unsynced {index}", rating_count=None)
        _rate(database, subject, movie, 3.5)

    payload = build_obscurity_index(database, subject)

    # Seven zeros would have pulled the median to 0 and called this the most
    # obscure taste on the site.
    assert payload["index"]["median_rating_count"] == 1_000
    assert payload["coverage"] == {"rated_films": 10, "films_with_rating_count": 3}
    assert [entry["title"] for entry in payload["most_obscure"]] == [
        "subject film 0",
        "subject film 1",
        "subject film 2",
    ]


def test_a_profile_with_no_synced_films_reports_nulls_and_empty_lists(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    for index in range(3):
        movie = _film(database, f"unsynced {index}", rating_count=None)
        _rate(database, subject, movie, 4.0)

    payload = build_obscurity_index(database, subject)

    assert payload["index"] == {
        "median_rating_count": None,
        "mean_rating_count": None,
        "percentile_vs_group": None,
        "lean": None,
    }
    assert payload["coverage"] == {"rated_films": 3, "films_with_rating_count": 0}
    assert payload["most_obscure"] == []
    assert payload["most_mainstream"] == []
    assert payload["crowd_position"] == []


def test_a_zero_rating_count_is_treated_as_unsynced_not_as_an_empty_crowd(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [0, 5_000, 7_000])

    payload = build_obscurity_index(database, subject)

    assert payload["coverage"]["films_with_rating_count"] == 2
    assert payload["index"]["median_rating_count"] == 6_000
    assert [entry["rating_count"] for entry in payload["most_obscure"]] == [5_000, 7_000]


def test_unrated_and_removed_films_are_outside_the_measured_library(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [1_000, 1_000])
    _rate(database, subject, _film(database, "Watched", rating_count=9), None)
    _rate(
        database,
        subject,
        _film(database, "Removed", rating_count=9),
        5.0,
        removed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    payload = build_obscurity_index(database, subject)

    assert payload["coverage"] == {"rated_films": 2, "films_with_rating_count": 2}
    assert payload["index"]["median_rating_count"] == 1_000


# --- placement against the group --------------------------------------------


def test_the_percentile_measures_this_profile_against_every_other_profile(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [500, 500, 500])
    for index, audience in enumerate((1_000, 2_000, 3_000)):
        _library(database, _profile(database, f"other{index}"), [audience] * 3)

    payload = build_obscurity_index(database, subject)

    # Every one of the three others watches bigger films.
    assert payload["index"]["percentile_vs_group"] == 100.0
    assert payload["index"]["lean"] == "obscure"


def test_the_most_mainstream_profile_sits_at_the_bottom_of_the_percentile(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [4_000_000] * 3)
    for index, audience in enumerate((900, 1_000, 1_100)):
        _library(database, _profile(database, f"other{index}"), [audience] * 3)

    payload = build_obscurity_index(database, subject)

    assert payload["index"]["percentile_vs_group"] == 0.0
    assert payload["index"]["lean"] == "mainstream"


def test_a_profile_is_never_part_of_the_group_it_is_placed_against(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [500] * 3)
    _library(database, _profile(database, "other"), [5_000] * 3)

    payload = build_obscurity_index(database, subject)

    # With one other profile, all of which is more mainstream, the subject is
    # at 100. Folding the subject into its own comparison group would halve
    # that to 50 and report a profile as average against itself.
    assert payload["index"]["percentile_vs_group"] == 100.0


def test_a_profile_level_with_its_whole_group_lands_in_the_middle(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [2_000] * 3)
    for index in range(4):
        _library(database, _profile(database, f"other{index}"), [2_000] * 3)

    payload = build_obscurity_index(database, subject)

    # Ties count at their midpoint: level with everybody is the middle of the
    # pack, not the obscure end of it and not the mainstream end.
    assert payload["index"]["percentile_vs_group"] == 50.0
    assert payload["index"]["lean"] == "balanced"


def test_a_profile_with_no_group_gets_a_median_but_no_lean(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [700] * 3)

    payload = build_obscurity_index(database, subject)

    # 700 is small, but "mainstream" only means anything relative to somebody.
    assert payload["index"]["median_rating_count"] == 700
    assert payload["index"]["percentile_vs_group"] is None
    assert payload["index"]["lean"] is None


def test_only_active_completed_profiles_form_the_comparison_group(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [500] * 3)
    _library(
        database,
        _profile(database, "pending", scraping_status="pending"),
        [5_000_000] * 3,
    )
    _library(
        database,
        _profile(database, "disabled", is_active=False),
        [5_000_000] * 3,
    )

    payload = build_obscurity_index(database, subject)

    assert payload["index"]["percentile_vs_group"] is None
    assert payload["index"]["lean"] is None


def test_a_group_member_with_no_synced_films_contributes_no_median(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [500] * 3)
    unsynced = _profile(database, "unsynced")
    for index in range(3):
        _rate(database, unsynced, _film(database, f"blank {index}"), 4.0)

    assert (
        build_obscurity_index(database, subject)["index"]["percentile_vs_group"] is None
    )


@pytest.mark.parametrize(
    ("subject_median", "others", "expected"),
    [
        (100.0, [], None),
        (None, [1.0, 2.0], None),
        (100.0, [200.0, 300.0], 100.0),
        (100.0, [50.0, 60.0], 0.0),
        (100.0, [50.0, 200.0], 50.0),
        (100.0, [100.0, 100.0], 50.0),
        (100.0, [100.0, 500.0], 75.0),
    ],
)
def test_percentile_arithmetic(subject_median, others, expected) -> None:
    assert _percentile_vs_group(subject_median, others) == expected


# --- the two ends of the ordering -------------------------------------------


def test_the_two_lists_are_the_two_ends_of_one_ordering(database: Session) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [10, 20, 30, 400_000, 500_000])

    payload = build_obscurity_index(database, subject, limit=2)

    assert [entry["rating_count"] for entry in payload["most_obscure"]] == [10, 20]
    assert [entry["rating_count"] for entry in payload["most_mainstream"]] == [
        500_000,
        400_000,
    ]


def test_a_library_smaller_than_twice_the_limit_still_fills_both_lists(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [10, 20, 30])

    payload = build_obscurity_index(database, subject, limit=10)

    # Both ends describe the same three films; neither list is truncated by the
    # other having consumed them.
    assert len(payload["most_obscure"]) == 3
    assert len(payload["most_mainstream"]) == 3


def test_film_entries_carry_their_identity_and_the_profile_rating(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    movie = _film(database, "Rare One", rating_count=205, year=1974)
    _rate(database, subject, movie, 4.5)

    entry = build_obscurity_index(database, subject)["most_obscure"][0]

    assert entry == {
        "title": "Rare One",
        "year": 1974,
        "poster_url": None,
        "letterboxd_url": f"https://letterboxd.com/film/{movie.id}/",
        "rating_count": 205,
        "profile_rating": 4.5,
    }


# --- crowd position ---------------------------------------------------------


_CROWD = {
    "0.5": 10,
    "1.0": 10,
    "1.5": 10,
    "2.0": 10,
    "2.5": 10,
    "3.0": 10,
    "3.5": 10,
    "4.0": 10,
    "4.5": 10,
    "5.0": 10,
}


def test_crowd_position_is_empty_while_distributions_are_unpopulated(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [1_000, 2_000, 3_000])

    payload = build_obscurity_index(database, subject)

    # Empty list, not null: the endpoint is useful before the re-backfill.
    assert payload["crowd_position"] == []
    assert payload["index"]["median_rating_count"] == 2_000


def test_the_share_is_the_fraction_of_the_crowd_at_or_below_this_rating(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    movie = _film(
        database,
        "Flat Crowd",
        rating_count=100,
        crowd_average=2.75,
        distribution=_CROWD,
    )
    _rate(database, subject, movie, 3.0)

    entry = build_obscurity_index(database, subject)["crowd_position"][0]

    # Six of the ten equal buckets sit at or below three stars.
    assert entry["share_at_or_below"] == 0.6
    assert entry["profile_rating"] == 3.0
    assert entry["crowd_average"] == 2.75


def test_the_most_contrarian_film_comes_first(database: Session) -> None:
    subject = _profile(database, "subject")
    crowd_loved_it = {"0.5": 0, "5.0": 100}
    crowd_hated_it = {"0.5": 100, "5.0": 0}
    _rate(
        database,
        subject,
        _film(database, "Agreed", rating_count=100, distribution=crowd_loved_it),
        5.0,
    )
    _rate(
        database,
        subject,
        _film(database, "Alone", rating_count=100, distribution=crowd_loved_it),
        0.5,
    )
    _rate(
        database,
        subject,
        _film(database, "Piled On", rating_count=100, distribution=crowd_hated_it),
        0.5,
    )

    titles = [
        entry["title"]
        for entry in build_obscurity_index(database, subject)["crowd_position"]
    ]

    # "Alone" rated a beloved film half a star: almost none of the crowd is at
    # or below it. "Agreed" and "Piled On" both sit at the top of their crowd.
    assert titles[0] == "Alone"
    assert set(titles[1:]) == {"Agreed", "Piled On"}


def test_ties_on_share_break_towards_the_larger_crowd(database: Session) -> None:
    subject = _profile(database, "subject")
    for title, audience in (("Small", 500), ("Huge", 4_000_000), ("Middling", 9_000)):
        _rate(
            database,
            subject,
            _film(database, title, rating_count=audience, distribution=_CROWD),
            3.0,
        )

    titles = [
        entry["title"]
        for entry in build_obscurity_index(database, subject)["crowd_position"]
    ]

    assert titles == ["Huge", "Middling", "Small"]


def test_a_film_with_an_all_zero_distribution_has_no_position(
    database: Session,
) -> None:
    subject = _profile(database, "subject")
    _rate(
        database,
        subject,
        _film(database, "Zeroed", rating_count=100, distribution={"0.5": 0, "5.0": 0}),
        4.0,
    )

    # Dividing by an empty crowd would be a fabricated share, not a zero one.
    assert build_obscurity_index(database, subject)["crowd_position"] == []


def test_crowd_position_needs_no_rating_count(database: Session) -> None:
    subject = _profile(database, "subject")
    _rate(
        database,
        subject,
        _film(database, "Shape Only", rating_count=None, distribution=_CROWD),
        5.0,
    )

    payload = build_obscurity_index(database, subject)

    assert payload["coverage"]["films_with_rating_count"] == 0
    assert payload["index"]["median_rating_count"] is None
    assert payload["crowd_position"][0]["share_at_or_below"] == 1.0


@pytest.mark.parametrize(
    ("distribution", "rating", "expected"),
    [
        ({"0.5": 1, "5.0": 3}, 0.5, 0.25),
        ({"0.5": 1, "5.0": 3}, 5.0, 1.0),
        ({"3.5": 4}, 3.5, 1.0),  # the rating's own bucket counts as "at or below"
        ({"3.5": 4}, 3.0, 0.0),
        (None, 4.0, None),
        ({}, 4.0, None),
        ("not a mapping", 4.0, None),
        ({"junk": 5, "4.0": 5}, 4.0, 1.0),  # unplaceable keys are dropped
    ],
)
def test_share_arithmetic(distribution, rating, expected) -> None:
    assert _share_at_or_below(distribution, rating) == expected


# --- limits -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, DEFAULT_LIMIT),
        (0, 1),
        (-5, 1),
        (3, 3),
        (MAX_LIMIT + 100, MAX_LIMIT),
        ("nonsense", DEFAULT_LIMIT),
    ],
)
def test_limit_is_clamped(value, expected) -> None:
    assert _clamp_limit(value) == expected


# --- route ------------------------------------------------------------------


@pytest.fixture()
def client(database: Session):
    """Mount the router standalone; registering it in main.py is not our file."""

    app = FastAPI()
    app.include_router(obscurity_router)
    app.dependency_overrides[get_db] = lambda: database
    yield app


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


def test_route_serves_the_frozen_contract(database: Session, client) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [500, 900], distribution=_CROWD)
    _library(database, _profile(database, "other"), [90_000] * 3)
    user = _tracked_user(database, subject)
    client.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(client).get("/api/profiles/subject/obscurity?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "username",
        "coverage",
        "index",
        "most_obscure",
        "most_mainstream",
        "crowd_position",
        # The other tail, and the whole distribution behind both.
        "crowd_position_below",
        "crowd_percentile",
    }
    assert payload["username"] == "subject"
    assert set(payload["coverage"]) == {"rated_films", "films_with_rating_count"}
    assert set(payload["index"]) == {
        "median_rating_count",
        "mean_rating_count",
        "percentile_vs_group",
        "lean",
    }
    for key in ("most_obscure", "most_mainstream"):
        assert set(payload[key][0]) == {
            "title",
            "year",
            "poster_url",
            "letterboxd_url",
            "rating_count",
            "profile_rating",
        }
    assert set(payload["crowd_position"][0]) == {
        "title",
        "year",
        "poster_url",
        "letterboxd_url",
        "profile_rating",
        "share_at_or_below",
        "crowd_average",
    }
    assert payload["index"]["lean"] == "obscure"


def test_route_honours_the_limit_query_parameter(database: Session, client) -> None:
    subject = _profile(database, "subject")
    _library(database, subject, [10, 20, 30, 40])
    user = _tracked_user(database, subject)
    client.dependency_overrides[get_current_user] = lambda: user
    http = TestClient(client)

    assert len(http.get("/api/profiles/subject/obscurity?limit=2").json()["most_obscure"]) == 2
    assert http.get("/api/profiles/subject/obscurity?limit=0").status_code == 422
    assert (
        http.get(f"/api/profiles/subject/obscurity?limit={MAX_LIMIT + 1}").status_code
        == 422
    )


def test_route_refuses_an_untracked_profile(database: Session, client) -> None:
    _profile(database, "subject")
    user = _tracked_user(database, None)
    client.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(client).get("/api/profiles/subject/obscurity")

    assert response.status_code == 403


def test_route_is_404_for_a_profile_that_does_not_exist(
    database: Session, client
) -> None:
    user = _tracked_user(database, None)
    client.dependency_overrides[get_current_user] = lambda: user

    response = TestClient(client).get("/api/profiles/nobody/obscurity")

    assert response.status_code == 404


def test_route_requires_an_authenticated_user() -> None:
    route = next(
        route
        for route in obscurity_router.routes
        if route.path == "/api/profiles/{username}/obscurity"
    )
    assert "get_current_user" in {
        dependency.call.__name__ for dependency in route.dependant.dependencies
    }


def test_the_crowd_percentile_says_where_a_profile_usually_lands(database: Session) -> None:
    """Showing only the contrarian tail told half the story.

    The median share across everything rated says whether somebody generally
    sits above or below the crowds they join.
    """
    profile = _profile(database, "generous")
    flat = {str(index / 2): 100 for index in range(1, 11)}
    for index in range(3):
        movie = _film(database, f"Loved {index}", rating_count=1000, distribution=flat)
        _rate(database, profile, movie, 5.0)

    percentile = build_obscurity_index(database, profile, limit=5)["crowd_percentile"]

    assert percentile["measured_films"] == 3
    assert percentile["typical_share"] == 1.0
    assert percentile["lean"] == "generous"


def test_both_tails_are_returned_so_a_profile_can_be_out_on_a_limb_either_way(
    database: Session,
) -> None:
    profile = _profile(database, "mixed")
    flat = {str(index / 2): 100 for index in range(1, 11)}
    adored = _film(database, "Adored", rating_count=1000, distribution=flat)
    hated = _film(database, "Hated", rating_count=1000, distribution=flat)
    _rate(database, profile, adored, 5.0)
    _rate(database, profile, hated, 0.5)

    payload = build_obscurity_index(database, profile, limit=5)

    assert payload["crowd_position"][0]["title"] == "Hated"
    assert payload["crowd_position_below"][0]["title"] == "Adored"


def test_a_profile_whose_films_carry_no_histogram_has_no_percentile(
    database: Session,
) -> None:
    """Never measured is not the same as exactly average."""
    profile = _profile(database, "unscraped")
    movie = _film(database, "No Histogram")
    _rate(database, profile, movie, 4.0)

    percentile = build_obscurity_index(database, profile, limit=5)["crowd_percentile"]

    assert percentile["measured_films"] == 0
    assert percentile["typical_share"] is None
    assert percentile["lean"] is None

"""People: the holes in the evidence, and the panels that stay empty on purpose.

The assertions here are about what a panel is allowed to claim. A rating change
that was never observed is not "no change". A tag surface an old importer never
read is not "no tags". A profile with no header read is not a profile with zero
followers. Each of those distinctions is a sentence in the product's copy, and
each one is pinned by a test below.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import count
from typing import Optional

import pytest
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import (
    Movie,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
    ProfileFilm,
    ProfileSync,
    Review,
    WatchEvent,
)
from services.people import (
    build_decade_drift,
    build_favourites,
    build_member_card,
    build_pair_blind_spots,
    build_quiet,
    build_reach,
    build_rename_resilience,
    build_reviews_per_watch,
    build_rewatch_shifts,
    build_silent_fives,
    build_tag_overlap,
    build_unrated,
)


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
    Profile.__table__,
    ProfileSync.__table__,
    Movie.__table__,
    ProfileFilm.__table__,
    ProfileFavoriteMovie.__table__,
    ProfileDataChange.__table__,
    WatchEvent.__table__,
    Review.__table__,
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
_CHANGE_IDS = count(1)


def _profile(database: Session, username: str, **kwargs) -> Profile:
    profile = Profile(username=username, scraping_status="completed", is_active=True, **kwargs)
    database.add(profile)
    database.commit()
    return profile


def _movie(database: Session, title: str) -> Movie:
    movie_id = next(_MOVIE_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{title}-{movie_id}",
        title=title,
        normalized_title=title.casefold(),
        release_year=2000,
    )
    database.add(movie)
    database.commit()
    return movie


def _film(
    database: Session,
    profile: Profile,
    movie: Movie,
    *,
    rating: Optional[float] = None,
    has_review: bool = False,
    tags: Optional[list[str]] = None,
    removed: bool = False,
) -> ProfileFilm:
    film = ProfileFilm(
        profile_id=profile.id,
        movie_id=movie.id,
        rating=rating,
        has_review=has_review,
        tags=tags or [],
        watch_count=1,
        removed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) if removed else None,
    )
    database.add(film)
    database.commit()
    return film


def _sync(database: Session, profile: Profile) -> ProfileSync:
    sync = ProfileSync(
        profile_id=profile.id,
        source_kind="full_html_upload",
        source_fingerprint=f"fingerprint-{profile.id}",
        importer_version=1,
        status="completed",
    )
    database.add(sync)
    database.commit()
    return sync


def _change(
    database: Session,
    profile: Profile,
    sync: ProfileSync,
    *,
    change_type: str,
    entity_type: str,
    movie: Optional[Movie] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
) -> None:
    index = next(_CHANGE_IDS)
    database.add(
        ProfileDataChange(
            profile_id=profile.id,
            profile_sync_id=sync.id,
            change_key=f"change-{index}",
            change_type=change_type,
            entity_type=entity_type,
            entity_key=f"entity-{index}",
            source_kind="full_html_upload",
            movie_id=movie.id if movie else None,
            before_payload=before or {},
            after_payload=after or {},
            detected_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
    )
    database.commit()


def _watch(database: Session, profile: Profile, movie: Movie, watched: date) -> None:
    database.add(
        WatchEvent(
            profile_id=profile.id,
            movie_id=movie.id,
            event_key=f"event-{next(_EVENT_IDS)}",
            watched_date=watched,
            source_kind="full_html_upload",
        )
    )
    database.commit()


def test_unrated_counts_the_hole_against_the_library(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Rated"), rating=4.0)
    _film(database, viewer, _movie(database, "Unrated"))

    result = build_unrated(database, viewer)

    assert result["unrated"] == 1
    assert result["library"] == 2
    assert result["share"] == 0.5
    assert "skips these rather than treating an absent rating as a low one" in result["caveat"]


def test_a_soft_removed_film_is_not_part_of_the_library(database: Session) -> None:
    """Absence is not deletion, but it is also not a current fact.

    A row that stopped appearing is history and belongs in Lost & found — it
    must not inflate either half of this ratio.
    """

    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Present"), rating=4.0)
    _film(database, viewer, _movie(database, "Gone"), removed=True)

    result = build_unrated(database, viewer)

    assert result["library"] == 1
    assert result["unrated"] == 0


def test_silent_fives_are_top_of_scale_with_no_review(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Silent"), rating=5.0, has_review=False)
    _film(database, viewer, _movie(database, "Written About"), rating=5.0, has_review=True)
    _film(database, viewer, _movie(database, "Merely Good"), rating=4.0, has_review=False)

    result = build_silent_fives(database, viewer)

    assert result["silent"] == 1
    assert result["top_rated"] == 2
    assert [film["title"] for film in result["films"]] == ["Silent"]


def test_rewatch_shifts_are_empty_by_design_before_a_second_read(database: Session) -> None:
    """A first import is a baseline and records no change at all.

    The distinction the caveat has to carry is between "we looked and their
    ratings held" and "we have only looked once" — those are opposite facts and
    an empty table cannot tell them apart on its own.
    """

    viewer = _profile(database, "viewer")

    result = build_rewatch_shifts(database, viewer)

    assert result["count"] == 0
    assert "a first import establishes the baseline and emits nothing" in result["caveat"]


def test_rewatch_shifts_read_the_before_and_after_payloads(database: Session) -> None:
    viewer = _profile(database, "viewer")
    sync = _sync(database, viewer)
    movie = _movie(database, "Reconsidered")
    _change(
        database,
        viewer,
        sync,
        change_type="rating_changed",
        entity_type="film",
        movie=movie,
        before={"rating": 3.5},
        after={"rating": 4.5},
    )

    result = build_rewatch_shifts(database, viewer)

    assert result["count"] == 1
    assert result["rose"] == 1
    assert result["fell"] == 0
    assert result["shifts"][0]["shift"] == 1.0


def test_a_change_with_no_rating_on_either_side_is_skipped(database: Session) -> None:
    viewer = _profile(database, "viewer")
    sync = _sync(database, viewer)
    _change(
        database,
        viewer,
        sync,
        change_type="rating_changed",
        entity_type="film",
        movie=_movie(database, "Half Recorded"),
        before={"rating": None},
        after={"rating": 4.0},
    )

    # Going from unrated to rated is a rating being *added*, not a mind being
    # changed, and rendering it as "— → 4.0" in a shift column would be a
    # different claim from the one the panel makes.
    assert build_rewatch_shifts(database, viewer)["count"] == 0


def test_favourites_read_changes_from_the_change_log(database: Session) -> None:
    """`profile_favorite_movies` carries no removal timestamp, so a swap is only
    visible in the change log. Reading a column the table does not have would
    return nothing forever and look like nobody ever swaps."""

    viewer = _profile(database, "viewer")
    sync = _sync(database, viewer)
    movie = _movie(database, "Dropped Favourite")
    database.add(ProfileFavoriteMovie(profile_id=viewer.id, movie_id=movie.id, position=1))
    database.commit()
    _change(database, viewer, sync, change_type="favorite_removed", entity_type="favorite", movie=movie)

    result = build_favourites(database, viewer)

    assert len(result["favourites"]) == 1
    assert len(result["changes"]) == 1
    assert result["changes"][0]["change_type"] == "favorite_removed"


def test_quiet_measures_against_the_profiles_own_rhythm(database: Session) -> None:
    viewer = _profile(database, "viewer")
    today = datetime.now(timezone.utc).date()
    # A weekly logger, silent for two months.
    for weeks_ago in range(12, 2, -1):
        _watch(database, viewer, _movie(database, f"Week {weeks_ago}"), today - timedelta(weeks=weeks_ago))

    entry = build_quiet(database, [viewer])["profiles"][0]

    assert entry["usual_gap_days"] == 7
    assert entry["silent_days"] >= 20
    assert entry["multiple"] is not None and entry["multiple"] > 2


def test_too_few_gaps_reports_no_rhythm_rather_than_a_fake_one(database: Session) -> None:
    viewer = _profile(database, "viewer")
    today = datetime.now(timezone.utc).date()
    _watch(database, viewer, _movie(database, "One"), today - timedelta(days=40))
    _watch(database, viewer, _movie(database, "Two"), today - timedelta(days=39))

    entry = build_quiet(database, [viewer])["profiles"][0]

    assert entry["usual_gap_days"] is None
    assert "normal gap" in entry["read"]


def test_tag_overlap_reports_who_carries_tags_at_all(database: Session) -> None:
    """A profile read by an importer that never collected tags shows none, and
    that is not the same as using none. The caveat has to separate them."""

    tagger = _profile(database, "tagger")
    other = _profile(database, "other")
    untagged = _profile(database, "untagged")
    shared = _movie(database, "Shared")
    _film(database, tagger, shared, tags=["rewatch"])
    _film(database, other, _movie(database, "Second"), tags=["rewatch"])
    _film(database, untagged, _movie(database, "Third"))

    result = build_tag_overlap(database, [tagger, other, untagged])

    assert result["count"] == 1
    assert result["tags"][0]["tag"] == "rewatch"
    assert set(result["profiles_with_tags"]) == {"tagger", "other"}
    assert "2 of 3 selected profiles carry any tags at all" in result["caveat"]


def test_decade_drift_excludes_films_with_no_release_year(database: Session) -> None:
    viewer = _profile(database, "viewer")
    dated = _movie(database, "Dated")
    undated = _movie(database, "Undated")
    undated.release_year = None
    database.commit()
    _watch(database, viewer, dated, date(2026, 5, 1))
    _watch(database, viewer, undated, date(2026, 5, 2))

    points = build_decade_drift(database, [viewer])["profiles"]["viewer"]

    assert len(points) == 1
    assert points[0]["films"] == 1


def test_pair_blind_spots_exclude_anything_either_of_them_logged(database: Session) -> None:
    left = _profile(database, "left")
    right = _profile(database, "right")
    third = _profile(database, "third")
    fourth = _profile(database, "fourth")

    unseen = _movie(database, "Unseen")
    seen_by_left = _movie(database, "Seen By Left")
    for rater in (third, fourth):
        _film(database, rater, unseen, rating=4.5)
        _film(database, rater, seen_by_left, rating=5.0)
    _film(database, left, seen_by_left, rating=3.0)

    result = build_pair_blind_spots(database, [left, right], [left, right, third, fourth])

    assert [film["title"] for film in result["films"]] == ["Unseen"]


def test_reviews_per_watch_is_null_for_an_empty_library(database: Session) -> None:
    empty = _profile(database, "empty")

    entry = build_reviews_per_watch(database, [empty])["profiles"][0]

    # No films is no rate, not a rate of zero -- dividing by an empty library
    # would print 0.00 and read as "never writes".
    assert entry["ratio"] is None


def test_reach_keeps_an_unread_header_as_null(database: Session) -> None:
    read = _profile(database, "read", followers_count=741, following_count=268)
    unread = _profile(database, "unread")

    entries = {entry["username"]: entry for entry in build_reach(database, [read, unread])["profiles"]}

    assert entries["read"]["followers"] == 741
    assert entries["unread"]["followers"] is None
    assert "which is not the same as zero" in build_reach(database, [read, unread])["caveat"]


def test_rename_resilience_separates_survivable_from_fragile(database: Session) -> None:
    resilient = _profile(database, "resilient", letterboxd_person_id=123456)
    fragile = _profile(database, "fragile")

    result = build_rename_resilience(database, [resilient, fragile])

    assert result["resilient"] == ["resilient"]
    assert result["fragile"] == ["fragile"]
    assert "the row is updated, not versioned" in result["caveat"]


def test_member_card_prefers_the_first_diary_entry_over_a_join_date(database: Session) -> None:
    """Letterboxd publishes no join date on a public page. The earliest dated
    diary entry answers the same question and we hold it for everyone."""

    viewer = _profile(database, "viewer")
    _watch(database, viewer, _movie(database, "Earliest"), date(2019, 3, 4))
    _watch(database, viewer, _movie(database, "Later"), date(2024, 1, 1))

    card = build_member_card(database, viewer)

    assert card["first_logged_date"] == "2019-03-04"
    assert card["join_date"] is None
    assert card["pronoun"] is None

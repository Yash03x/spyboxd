"""Profile stats: honest arithmetic over whatever enrichment we actually hold."""
from __future__ import annotations

from datetime import date
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
    WatchEvent,
)
from services.profile_stats import (
    build_profile_stats,
    longest_streak_weeks,
    multi_film_days,
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
_EVENT_IDS = count(1)


def _profile(database: Session, username: str = "viewer") -> Profile:
    profile = Profile(username=username, scraping_status="completed", is_active=True)
    database.add(profile)
    database.commit()
    return profile


def _person(name: str, *, job: Optional[str] = None, order: Optional[int] = None) -> dict:
    member: dict[str, Any] = {"id": abs(hash(name)) % 100000, "name": name}
    if job is not None:
        member["job"] = job
        member["department"] = "Directing" if job == "Director" else "Production"
    if order is not None:
        member["order"] = order
    return member


def _film(
    database: Session,
    profile: Profile,
    *,
    title: str,
    year: Optional[int] = 2000,
    rating: Optional[float] = None,
    rewatch_count: int = 0,
    enrich: bool = True,
    runtime: Optional[int] = 100,
    genres: Optional[list[str]] = None,
    language: Optional[str] = "en",
    spoken_languages: Optional[list[dict]] = None,
    countries: Optional[list[dict]] = None,
    crew: Optional[list[dict]] = None,
    cast: Optional[list[dict]] = None,
    studios: Optional[list[dict]] = None,
) -> Movie:
    movie_id = next(_MOVIE_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{title}-{movie_id}",
        title=title,
        normalized_title=title.casefold(),
        release_year=year,
    )
    database.add(movie)
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie_id,
            rating=rating,
            tags=[],
            watch_count=max(1, rewatch_count + 1),
            rewatch_count=rewatch_count,
        )
    )
    if enrich:
        details: dict[str, Any] = {}
        if studios is not None:
            details["production_companies"] = studios
        if spoken_languages is not None:
            details["spoken_languages"] = spoken_languages
        database.add(
            MovieEnrichment(
                movie_id=movie_id,
                runtime_minutes=runtime,
                original_language=language,
                genres=[{"name": name} for name in (genres or [])],
                keywords=[],
                credits={"cast": cast or [], "crew": crew or []},
                production_countries=countries or [],
                raw_payload={"details": details} if details else {},
            )
        )
    database.commit()
    return movie


def _watch(database: Session, profile: Profile, movie: Movie, watched: date) -> None:
    event_id = next(_EVENT_IDS)
    database.add(
        WatchEvent(
            id=event_id,
            profile_id=profile.id,
            movie_id=movie.id,
            event_key=f"event-{event_id}",
            watched_date=watched,
            tags=[],
            source_kind="diary_csv",
        )
    )
    database.commit()


# --- streak and multi-film-day arithmetic -----------------------------------


def test_a_gap_week_breaks_the_streak_and_the_longest_run_wins() -> None:
    # Three consecutive weeks, a skipped week, then two consecutive weeks.
    dates = [
        date(2026, 1, 5),   # week starting Mon 5 Jan
        date(2026, 1, 13),  # week starting Mon 12 Jan
        date(2026, 1, 19),  # week starting Mon 19 Jan
        # week starting Mon 26 Jan deliberately empty
        date(2026, 2, 2),
        date(2026, 2, 9),
    ]

    assert longest_streak_weeks(dates) == 3


def test_many_watches_in_one_week_are_still_a_single_week_streak() -> None:
    week = [date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 8)]

    assert longest_streak_weeks(week) == 1


def test_a_streak_survives_the_iso_year_boundary() -> None:
    # ISO week numbers restart in January; the run does not.
    boundary = [date(2025, 12, 22), date(2025, 12, 29), date(2026, 1, 5)]

    assert longest_streak_weeks(boundary) == 3


def test_streak_and_multi_film_days_are_unknown_without_dated_events() -> None:
    assert longest_streak_weeks([]) is None
    assert multi_film_days([]) is None


def test_multi_film_days_counts_only_days_with_two_or_more_events() -> None:
    dates = [
        date(2026, 4, 1),
        date(2026, 4, 1),
        date(2026, 4, 2),
        date(2026, 4, 3),
        date(2026, 4, 3),
        date(2026, 4, 3),
    ]

    assert multi_film_days(dates) == 2


def test_streaks_and_multi_film_days_read_the_profile_watch_events(database: Session) -> None:
    profile = _profile(database)
    first = _film(database, profile, title="First")
    second = _film(database, profile, title="Second")
    _watch(database, profile, first, date(2026, 1, 5))
    _watch(database, profile, second, date(2026, 1, 5))
    _watch(database, profile, first, date(2026, 1, 12))

    stats = build_profile_stats(database, profile)

    assert stats["coverage"]["dated_events"] == 3
    assert stats["totals"]["longest_streak_weeks"] == 2
    assert stats["totals"]["multi_film_days"] == 1


# --- runtime honesty --------------------------------------------------------


def test_hours_watched_sums_only_known_runtimes_and_reports_coverage(
    database: Session,
) -> None:
    profile = _profile(database)
    _film(database, profile, title="Ninety", runtime=90)
    _film(database, profile, title="Thirty", runtime=30)
    _film(database, profile, title="Unknown Runtime", runtime=None)
    _film(database, profile, title="No Enrichment", enrich=False)

    stats = build_profile_stats(database, profile)

    # 120 known minutes over 4 films: two hours, never extrapolated to four films.
    assert stats["totals"]["hours_watched"] == 2.0
    assert stats["totals"]["runtime_coverage"] == 0.5
    assert stats["coverage"]["films_total"] == 4
    assert stats["coverage"]["films_enriched"] == 3
    assert stats["coverage"]["enrichment_ratio"] == 0.75


def test_hours_watched_is_null_when_no_runtime_is_known(database: Session) -> None:
    profile = _profile(database)
    _film(database, profile, title="Unmatched", enrich=False)

    stats = build_profile_stats(database, profile)

    assert stats["totals"]["hours_watched"] is None
    assert stats["totals"]["runtime_coverage"] == 0.0


# --- credits extraction -----------------------------------------------------


def test_only_the_director_job_counts_as_a_director(database: Session) -> None:
    profile = _profile(database)
    _film(
        database,
        profile,
        title="Crewed",
        rating=4.0,
        crew=[
            _person("Assistant Director", job="Assistant Director"),
            _person("Director of Photography", job="Director of Photography"),
            _person("Real Director", job="Director"),
            _person("Second Unit Director", job="Second Unit Director"),
            _person("Producer Person", job="Producer"),
        ],
    )

    stats = build_profile_stats(database, profile)

    assert [entry["name"] for entry in stats["top_directors"]] == ["Real Director"]
    assert stats["totals"]["distinct_directors"] == 1


def test_co_directors_both_count_once_each(database: Session) -> None:
    profile = _profile(database)
    _film(
        database,
        profile,
        title="Co-directed",
        crew=[
            _person("Joel Coen", job="Director"),
            _person("Ethan Coen", job="Director"),
            # A duplicated credit row must not double-count one person.
            _person("Joel Coen", job="Director"),
        ],
    )

    stats = build_profile_stats(database, profile)

    assert {entry["name"]: entry["count"] for entry in stats["top_directors"]} == {
        "Joel Coen": 1,
        "Ethan Coen": 1,
    }


def test_only_top_billed_cast_counts_as_an_actor(database: Session) -> None:
    profile = _profile(database)
    _film(
        database,
        profile,
        title="Ensemble",
        cast=[_person(f"Actor {index}", order=index) for index in range(40)],
    )

    stats = build_profile_stats(database, profile)

    assert [entry["name"] for entry in stats["top_actors"]] == [
        "Actor 0",
        "Actor 1",
        "Actor 2",
        "Actor 3",
        "Actor 4",
    ]
    assert stats["totals"]["distinct_actors"] == 5


def test_studios_come_from_the_raw_payload_production_companies(database: Session) -> None:
    profile = _profile(database)
    _film(
        database,
        profile,
        title="Studio Film",
        studios=[{"id": 1, "name": "A24"}, {"id": 2, "name": "Universal Pictures"}],
    )
    _film(database, profile, title="Second Studio Film", studios=[{"id": 1, "name": "A24"}])
    # A film whose payload never listed companies simply contributes nothing.
    _film(database, profile, title="No Companies")

    stats = build_profile_stats(database, profile)

    assert stats["top_studios"][0] == {
        "name": "A24",
        "count": 2,
        "average_rating": None,
    }
    assert stats["totals"]["distinct_studios"] == 2


# --- the credible-sample floor ---------------------------------------------


def test_highest_rated_ignores_buckets_below_three_rated_films(database: Session) -> None:
    profile = _profile(database)
    # One perfect film in a genre is not a favourite genre.
    _film(database, profile, title="Lone Masterpiece", rating=5.0, genres=["Western"])
    for index in range(3):
        _film(
            database,
            profile,
            title=f"Drama {index}",
            rating=4.0,
            genres=["Drama"],
        )

    stats = build_profile_stats(database, profile)

    assert stats["highest_rated"]["genre"] == {
        "label": "Drama",
        "count": 3,
        "average_rating": 4.0,
    }


def test_highest_rated_is_null_when_nothing_clears_the_floor(database: Session) -> None:
    profile = _profile(database)
    _film(database, profile, title="Only Rated Film", rating=5.0, genres=["Horror"])
    _film(database, profile, title="Unrated Horror", genres=["Horror"])

    stats = build_profile_stats(database, profile)

    # Two rated films would still be too thin; one is definitely too thin.
    assert stats["highest_rated"] == {"genre": None, "decade": None, "director": None}
    # The genre still appears in the distribution, with its honest average.
    assert stats["genres"] == [
        {"label": "Horror", "count": 2, "average_rating": 5.0}
    ]


def test_bucket_averages_use_only_rated_films(database: Session) -> None:
    profile = _profile(database)
    _film(database, profile, title="Rated", rating=3.0, genres=["Comedy"])
    _film(database, profile, title="Also Rated", rating=5.0, genres=["Comedy"])
    _film(database, profile, title="Unrated", genres=["Comedy"])

    stats = build_profile_stats(database, profile)

    assert stats["genres"] == [
        {"label": "Comedy", "count": 3, "average_rating": 4.0}
    ]
    assert stats["coverage"]["rated_films"] == 2
    assert stats["totals"]["average_rating"] == 4.0


# --- graceful degradation ---------------------------------------------------


def test_a_profile_with_no_enrichment_returns_nulls_not_zeros(database: Session) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Unmatched", rating=4.5, enrich=False)
    _watch(database, profile, movie, date(2026, 5, 4))

    stats = build_profile_stats(database, profile)

    assert stats["coverage"] == {
        "films_total": 1,
        "films_enriched": 0,
        "enrichment_ratio": 0.0,
        "dated_events": 1,
        "rated_films": 1,
    }
    totals = stats["totals"]
    assert totals["films"] == 1
    assert totals["hours_watched"] is None
    assert totals["runtime_coverage"] == 0.0
    for dimension in (
        "distinct_directors",
        "distinct_actors",
        "distinct_countries",
        "distinct_languages",
        "distinct_studios",
    ):
        assert totals[dimension] is None, dimension
    # Decade survives without TMDB: the release year comes from the film row.
    assert stats["decades"] == [{"label": "2000s", "count": 1, "average_rating": 4.5}]
    assert stats["top_directors"] == []
    assert stats["highest_rated"]["director"] is None
    assert stats["letterboxd_reported"] is None


def test_a_profile_with_no_films_at_all_returns_a_valid_payload(database: Session) -> None:
    profile = _profile(database)

    stats = build_profile_stats(database, profile)

    assert stats["coverage"]["films_total"] == 0
    assert stats["coverage"]["enrichment_ratio"] == 0.0
    assert stats["totals"]["runtime_coverage"] == 0.0
    assert stats["totals"]["average_rating"] is None
    assert stats["totals"]["longest_streak_weeks"] is None
    assert stats["totals"]["rewatches"] == 0
    assert stats["genres"] == []
    assert stats["highest_rated"] == {"genre": None, "decade": None, "director": None}


def test_malformed_enrichment_payloads_never_crash(database: Session) -> None:
    profile = _profile(database)
    movie_id = next(_MOVIE_IDS)
    database.add(
        Movie(
            id=movie_id,
            canonical_key=f"letterboxd:junk-{movie_id}",
            title="Junk",
            normalized_title="junk",
            release_year=None,
        )
    )
    database.add(ProfileFilm(profile_id=profile.id, movie_id=movie_id, tags=[]))
    database.add(
        MovieEnrichment(
            movie_id=movie_id,
            runtime_minutes=None,
            original_language="",
            genres=["Drama", None, {"no_name": 1}],
            keywords=[],
            # credits arriving as a list, cast members as bare strings.
            credits={"cast": ["not a dict"], "crew": "not a list"},
            production_countries=[{"iso_3166_1": "US"}, "France"],
            raw_payload={"details": {"production_companies": "not a list"}},
        )
    )
    database.commit()

    stats = build_profile_stats(database, profile)

    assert stats["genres"] == [{"label": "Drama", "count": 1, "average_rating": None}]
    assert stats["top_directors"] == []
    assert stats["top_studios"] == []
    assert stats["decades"] == []
    assert [entry["label"] for entry in stats["countries"]] == ["France"]
    assert stats["languages"] == []


# --- distributions ----------------------------------------------------------


def test_countries_carry_their_iso_code_and_languages_are_named(database: Session) -> None:
    profile = _profile(database)
    _film(
        database,
        profile,
        title="Parasite",
        language="ko",
        spoken_languages=[{"iso_639_1": "ko", "english_name": "Korean"}],
        countries=[{"name": "South Korea", "iso_3166_1": "KR"}],
    )
    _film(
        database,
        profile,
        title="Unnamed Language",
        language="lv",
        countries=[{"name": "Latvia", "iso_3166_1": "LV"}],
    )

    stats = build_profile_stats(database, profile)

    assert stats["countries"] == [
        {"label": "Latvia", "code": "LV", "count": 1, "average_rating": None},
        {"label": "South Korea", "code": "KR", "count": 1, "average_rating": None},
    ]
    # A code the payload never names falls back to the uppercased code itself.
    assert sorted(entry["label"] for entry in stats["languages"]) == ["Korean", "LV"]


def test_decades_are_returned_in_chronological_order(database: Session) -> None:
    profile = _profile(database)
    for year in (2011, 2015, 1994, 1999, 1987):
        _film(database, profile, title=f"Film {year}", year=year)

    stats = build_profile_stats(database, profile)

    assert [entry["label"] for entry in stats["decades"]] == ["1980s", "1990s", "2010s"]
    assert [entry["count"] for entry in stats["decades"]] == [1, 2, 2]


def test_lists_are_capped_at_ten_entries_ranked_by_count(database: Session) -> None:
    profile = _profile(database)
    for index in range(12):
        # Genre 0 appears once, genre 11 twelve times.
        for _ in range(index + 1):
            _film(database, profile, title=f"Film {index}", genres=[f"Genre {index}"])

    stats = build_profile_stats(database, profile)

    assert len(stats["genres"]) == 10
    assert stats["genres"][0]["label"] == "Genre 11"
    assert stats["genres"][-1]["label"] == "Genre 2"
    assert stats["totals"]["distinct_directors"] is None


def test_rewatches_come_from_the_film_state_rows(database: Session) -> None:
    profile = _profile(database)
    _film(database, profile, title="Seen Thrice", rewatch_count=2)
    _film(database, profile, title="Seen Once")

    stats = build_profile_stats(database, profile)

    assert stats["totals"]["rewatches"] == 2


def test_letterboxd_reported_snapshot_is_returned_verbatim(database: Session) -> None:
    profile = _profile(database)
    profile.stats_snapshot = {"films": 1197, "hours": 2403, "directors": 779}
    database.commit()

    stats = build_profile_stats(database, profile)

    assert stats["letterboxd_reported"] == {
        "films": 1197,
        "hours": 2403,
        "directors": 779,
    }


# --- route ------------------------------------------------------------------


@pytest.fixture()
def client(database: Session):
    backend_main.app.dependency_overrides[backend_main.get_db] = lambda: database
    try:
        yield lambda user: TestClient(backend_main.app)
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


def test_route_serves_the_payload_for_a_tracked_profile(database: Session, client) -> None:
    profile = _profile(database)
    _film(database, profile, title="Tracked Film", rating=4.0, runtime=120)
    user = _tracked_user(database, profile)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client(user).get(f"/api/profiles/{profile.username}/stats")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == profile.username
    assert payload["totals"]["hours_watched"] == 2.0
    assert set(payload) == {
        "username",
        "coverage",
        "totals",
        "top_directors",
        "top_actors",
        "top_studios",
        "genres",
        "countries",
        "languages",
        "decades",
        "highest_rated",
        "letterboxd_reported",
    }


def test_route_refuses_an_untracked_profile(database: Session, client) -> None:
    profile = _profile(database)
    user = _tracked_user(database, None)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client(user).get(f"/api/profiles/{profile.username}/stats")

    assert response.status_code == 403

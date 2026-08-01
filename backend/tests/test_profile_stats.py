"""Profile stats: honest arithmetic over whatever enrichment we actually hold."""
from __future__ import annotations

from datetime import date, datetime, timezone
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
    Review,
    UserTrackedProfile,
    WatchEvent,
)
from services.profile_stats import (
    build_profile_stats,
    longest_streak_weeks,
    median_length_chars,
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
    Review.__table__,
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
    watch_count: Optional[int] = None,
    poster_url: Optional[str] = None,
    letterboxd_url: Optional[str] = None,
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
        poster_url=poster_url,
        letterboxd_url=letterboxd_url,
    )
    database.add(movie)
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie_id,
            rating=rating,
            tags=[],
            watch_count=(
                watch_count if watch_count is not None else max(1, rewatch_count + 1)
            ),
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


def _review(
    database: Session,
    profile: Profile,
    *,
    movie: Optional[Movie] = None,
    title: str = "Unmatched Film",
    year: Optional[int] = None,
    text: Optional[str] = "A fine watch.",
    spoilers: bool = False,
    likes: int = 0,
    published: Optional[date] = None,
    removed: bool = False,
) -> Review:
    review = Review(
        profile_id=profile.id,
        movie_id=movie.id if movie is not None else None,
        movie_title=movie.title if movie is not None else title,
        movie_year=movie.release_year if movie is not None else year,
        review_text=text,
        contains_spoilers=spoilers,
        likes_count=likes,
        comments_count=0,
        published_date=published,
        tags=[],
        removed_at=datetime(2026, 6, 1, tzinfo=timezone.utc) if removed else None,
    )
    database.add(review)
    database.commit()
    return review


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
        "rated_count": 0,
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
        "rated_count": 3,
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
        {"label": "Horror", "count": 2, "rated_count": 1, "average_rating": 5.0}
    ]


def test_bucket_averages_use_only_rated_films(database: Session) -> None:
    profile = _profile(database)
    _film(database, profile, title="Rated", rating=3.0, genres=["Comedy"])
    _film(database, profile, title="Also Rated", rating=5.0, genres=["Comedy"])
    _film(database, profile, title="Unrated", genres=["Comedy"])

    stats = build_profile_stats(database, profile)

    assert stats["genres"] == [
        {"label": "Comedy", "count": 3, "rated_count": 2, "average_rating": 4.0}
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
        "reviews_total": 0,
        "reviews_matched_to_films": 0,
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
    assert stats["decades"] == [{"label": "2000s", "count": 1, "rated_count": 1, "average_rating": 4.5}]
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

    assert stats["genres"] == [{"label": "Drama", "count": 1, "rated_count": 0, "average_rating": None}]
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
        {"label": "Latvia", "code": "LV", "count": 1, "rated_count": 0, "average_rating": None},
        {"label": "South Korea", "code": "KR", "count": 1, "rated_count": 0, "average_rating": None},
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


# --- rewatches --------------------------------------------------------------


def test_the_rewatch_block_counts_returns_and_averages_both_sides(
    database: Session,
) -> None:
    profile = _profile(database)
    _film(database, profile, title="Returned To", rating=5.0, rewatch_count=2)
    _film(database, profile, title="Revisited", rating=4.5, rewatch_count=1)
    _film(database, profile, title="Seen Once", rating=3.0)
    _film(database, profile, title="Also Once", rating=4.0)
    _film(database, profile, title="Once, Unrated")

    rewatches = build_profile_stats(database, profile)["rewatches"]

    assert rewatches["total_rewatches"] == 3
    assert rewatches["films_rewatched"] == 2
    # Two of five films, never rounded up to "most of the library".
    assert rewatches["rewatch_rate"] == 0.4
    assert rewatches["average_rating_rewatched"] == 4.75
    # The unrated film sits in neither average; 3.0 and 4.0 make 3.5.
    assert rewatches["average_rating_once"] == 3.5


def test_most_rewatched_ranks_by_watch_count_and_omits_films_seen_once(
    database: Session,
) -> None:
    profile = _profile(database)
    _film(
        database,
        profile,
        title="Comfort Film",
        year=1994,
        rating=4.5,
        rewatch_count=1,
        watch_count=5,
        poster_url="https://image.example/comfort.jpg",
        letterboxd_url="https://letterboxd.com/film/comfort/",
    )
    _film(database, profile, title="Second Favourite", rewatch_count=3, watch_count=4)
    _film(database, profile, title="Seen Once", watch_count=1)

    most_rewatched = build_profile_stats(database, profile)["rewatches"]["most_rewatched"]

    assert [entry["title"] for entry in most_rewatched] == [
        "Comfort Film",
        "Second Favourite",
    ]
    assert most_rewatched[0] == {
        "title": "Comfort Film",
        "year": 1994,
        "poster_url": "https://image.example/comfort.jpg",
        "letterboxd_url": "https://letterboxd.com/film/comfort/",
        "watch_count": 5,
        "rating": 4.5,
    }


def test_equal_watch_counts_fall_back_to_the_deeper_rewatch(database: Session) -> None:
    profile = _profile(database)
    _film(database, profile, title="Shallow", rewatch_count=1, watch_count=4)
    _film(database, profile, title="Deep", rewatch_count=3, watch_count=4)

    most_rewatched = build_profile_stats(database, profile)["rewatches"]["most_rewatched"]

    assert [entry["title"] for entry in most_rewatched] == ["Deep", "Shallow"]


def test_a_rewatch_whose_first_viewing_was_never_logged_still_counts(
    database: Session,
) -> None:
    # Letterboxd lets a diary entry be marked "rewatch" without the original
    # watch ever being logged, so watch_count can be 1 alongside a rewatch.
    # The count is reported as held, not nudged up to the viewing nobody logged.
    profile = _profile(database)
    _film(database, profile, title="Rewatch Only", rating=4.0, rewatch_count=1, watch_count=1)
    _film(database, profile, title="Seen Once", rating=2.0, watch_count=1)

    rewatches = build_profile_stats(database, profile)["rewatches"]

    assert rewatches["films_rewatched"] == 1
    assert rewatches["most_rewatched"] == [
        {
            "title": "Rewatch Only",
            "year": 2000,
            "poster_url": None,
            "letterboxd_url": None,
            "watch_count": 1,
            "rating": 4.0,
        }
    ]
    assert rewatches["average_rating_rewatched"] == 4.0
    assert rewatches["average_rating_once"] == 2.0


def test_most_rewatched_is_capped_at_ten_films(database: Session) -> None:
    profile = _profile(database)
    for index in range(14):
        _film(
            database,
            profile,
            title=f"Rewatch {index:02d}",
            rewatch_count=1,
            watch_count=index + 2,
        )

    most_rewatched = build_profile_stats(database, profile)["rewatches"]["most_rewatched"]

    assert len(most_rewatched) == 10
    assert most_rewatched[0]["title"] == "Rewatch 13"
    assert most_rewatched[-1]["title"] == "Rewatch 04"


def test_a_profile_that_never_rewatches_reports_zero_and_nulls_not_absence(
    database: Session,
) -> None:
    profile = _profile(database)
    _film(database, profile, title="Only Watch", rating=4.0)

    rewatches = build_profile_stats(database, profile)["rewatches"]

    assert rewatches["total_rewatches"] == 0
    assert rewatches["films_rewatched"] == 0
    assert rewatches["rewatch_rate"] == 0.0
    assert rewatches["most_rewatched"] == []
    # Nothing was rewatched, so there is no rewatched average to report -- but
    # the one-time average is perfectly knowable.
    assert rewatches["average_rating_rewatched"] is None
    assert rewatches["average_rating_once"] == 4.0


def test_an_empty_library_has_no_rewatch_rate_rather_than_a_rate_of_zero(
    database: Session,
) -> None:
    profile = _profile(database)

    rewatches = build_profile_stats(database, profile)["rewatches"]

    assert rewatches["total_rewatches"] == 0
    assert rewatches["films_rewatched"] == 0
    assert rewatches["rewatch_rate"] is None
    assert rewatches["most_rewatched"] == []
    assert rewatches["average_rating_rewatched"] is None
    assert rewatches["average_rating_once"] is None


def test_the_rewatch_totals_agree_with_the_existing_totals_block(
    database: Session,
) -> None:
    profile = _profile(database)
    _film(database, profile, title="Twice", rewatch_count=1)
    _film(database, profile, title="Thrice", rewatch_count=2)

    stats = build_profile_stats(database, profile)

    assert stats["rewatches"]["total_rewatches"] == stats["totals"]["rewatches"] == 3


# --- reviews ----------------------------------------------------------------


def test_median_length_is_the_middle_review_and_unknown_without_reviews() -> None:
    assert median_length_chars([]) is None
    assert median_length_chars([42]) == 42
    assert median_length_chars([30, 10, 20]) == 20
    # No single middle review: the two middle lengths average out, floored,
    # because a review is never half a character long.
    assert median_length_chars([10, 20, 30, 41]) == 25


def test_the_review_block_counts_text_spoilers_and_median_length(
    database: Session,
) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Reviewed", rating=4.0)
    _review(database, profile, movie=movie, text="x" * 100)
    _review(database, profile, movie=movie, text="y" * 300, spoilers=True)
    _review(database, profile, movie=movie, text="z" * 500)
    # A rating logged with no prose is still a review row, but not writing.
    _review(database, profile, movie=movie, text="   ")

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["total_reviews"] == 4
    assert reviews["with_text"] == 3
    assert reviews["spoiler_reviews"] == 1
    assert reviews["median_length_chars"] == 300


def test_the_longest_review_names_its_film(database: Session) -> None:
    profile = _profile(database)
    short = _film(database, profile, title="Short Take", year=2011)
    essay = _film(database, profile, title="The Essay", year=1999)
    _review(database, profile, movie=short, text="Fun.")
    _review(database, profile, movie=essay, text="w" * 4000)

    longest = build_profile_stats(database, profile)["reviews"]["longest"]

    assert longest == {"title": "The Essay", "year": 1999, "length_chars": 4000}


def test_review_length_ignores_surrounding_whitespace(database: Session) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Padded")
    _review(database, profile, movie=movie, text="\n\n  four  \n\n")

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["longest"]["length_chars"] == 4
    assert reviews["median_length_chars"] == 4


def test_most_liked_is_capped_at_five_and_skips_reviews_nobody_liked(
    database: Session,
) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Popular", year=2004)
    for likes in range(8):
        _review(
            database,
            profile,
            movie=movie,
            likes=likes,
            published=date(2026, 1, 1 + likes),
        )

    most_liked = build_profile_stats(database, profile)["reviews"]["most_liked"]

    assert [entry["likes_count"] for entry in most_liked] == [7, 6, 5, 4, 3]
    assert most_liked[0] == {
        "title": "Popular",
        "year": 2004,
        "likes_count": 7,
        "published_date": "2026-01-08",
    }


def test_a_profile_whose_reviews_were_never_liked_gets_an_empty_shortlist(
    database: Session,
) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Quiet")
    _review(database, profile, movie=movie, likes=0)

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["total_reviews"] == 1
    assert reviews["most_liked"] == []


def test_reviews_by_year_is_ascending_and_leaves_out_undated_reviews(
    database: Session,
) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Dated")
    for published in (
        date(2024, 5, 1),
        date(2022, 2, 2),
        date(2024, 8, 9),
        date(2023, 1, 1),
        date(2024, 12, 25),
    ):
        _review(database, profile, movie=movie, published=published)
    # No publication date: this review belongs to no year and is not guessed
    # into one, though it still counts in the total.
    _review(database, profile, movie=movie, published=None)

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["reviews_by_year"] == [
        {"year": 2022, "count": 1},
        {"year": 2023, "count": 1},
        {"year": 2024, "count": 3},
    ]
    assert reviews["total_reviews"] == 6


def test_reviewed_and_unreviewed_averages_split_the_same_library(
    database: Session,
) -> None:
    profile = _profile(database)
    moved = _film(database, profile, title="Moved Me", rating=5.0)
    also_moved = _film(database, profile, title="Also Moved Me", rating=4.5)
    _film(database, profile, title="Just Watched", rating=3.0)
    _film(database, profile, title="Also Just Watched", rating=2.0)
    _film(database, profile, title="Unrated")
    _review(database, profile, movie=moved)
    _review(database, profile, movie=also_moved)

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["average_rating_reviewed"] == 4.75
    assert reviews["average_rating_unreviewed"] == 2.5


def test_two_reviews_of_one_film_move_that_film_across_the_split_once(
    database: Session,
) -> None:
    profile = _profile(database)
    twice_reviewed = _film(database, profile, title="Written Up Twice", rating=5.0)
    _film(database, profile, title="Never Written Up", rating=3.0)
    _review(database, profile, movie=twice_reviewed, text="First pass.")
    _review(database, profile, movie=twice_reviewed, text="Second pass.")

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["total_reviews"] == 2
    # One film either side, however many times it was written about.
    assert reviews["average_rating_reviewed"] == 5.0
    assert reviews["average_rating_unreviewed"] == 3.0


def test_a_review_that_matched_no_film_counts_but_moves_no_rating(
    database: Session,
) -> None:
    profile = _profile(database)
    _film(database, profile, title="In The Library", rating=4.0)
    _review(database, profile, movie=None, title="Never Matched", year=1975)

    stats = build_profile_stats(database, profile)

    assert stats["reviews"]["total_reviews"] == 1
    assert stats["reviews"]["longest"]["title"] == "Never Matched"
    # It resolved to no film, so it cannot place one on the reviewed side.
    assert stats["reviews"]["average_rating_reviewed"] is None
    assert stats["reviews"]["average_rating_unreviewed"] == 4.0
    # ...and the coverage block says so rather than leaving the gap silent.
    assert stats["coverage"]["reviews_total"] == 1
    assert stats["coverage"]["reviews_matched_to_films"] == 0


def test_a_review_prefers_the_canonical_film_title_over_its_own_copy(
    database: Session,
) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Renamed Since", year=2018)
    review = _review(database, profile, movie=movie)
    review.movie_title = "Stale Scraped Title"
    review.movie_year = 1900
    database.commit()

    longest = build_profile_stats(database, profile)["reviews"]["longest"]

    assert longest["title"] == "Renamed Since"
    assert longest["year"] == 2018


def test_removed_reviews_are_not_counted(database: Session) -> None:
    profile = _profile(database)
    movie = _film(database, profile, title="Deleted Take", rating=4.0)
    _review(database, profile, movie=movie, text="Kept.", likes=3)
    _review(database, profile, movie=movie, text="Deleted." * 50, likes=99, removed=True)

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["total_reviews"] == 1
    assert reviews["longest"]["length_chars"] == len("Kept.")
    assert [entry["likes_count"] for entry in reviews["most_liked"]] == [3]


def test_another_profiles_reviews_never_leak_in(database: Session) -> None:
    profile = _profile(database)
    other = _profile(database, username="stranger")
    movie = _film(database, profile, title="Shared Film", rating=4.0)
    _review(database, other, movie=movie, text="Not theirs.", likes=50)

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews["total_reviews"] == 0
    assert reviews["most_liked"] == []
    assert reviews["average_rating_reviewed"] is None
    assert reviews["average_rating_unreviewed"] == 4.0


def test_a_profile_with_no_reviews_returns_the_block_with_nulls_not_absence(
    database: Session,
) -> None:
    profile = _profile(database)

    reviews = build_profile_stats(database, profile)["reviews"]

    assert reviews == {
        "total_reviews": 0,
        "with_text": 0,
        "spoiler_reviews": 0,
        "median_length_chars": None,
        "longest": None,
        "most_liked": [],
        "reviews_by_year": [],
        # No watching to measure the writing against.
        "writing_rate_by_year": [],
        "average_rating_reviewed": None,
        "average_rating_unreviewed": None,
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
    movie = _film(
        database,
        profile,
        title="Tracked Film",
        rating=4.0,
        runtime=120,
        rewatch_count=1,
    )
    _review(database, profile, movie=movie, text="Worth returning to.", likes=2)
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
        "rewatches",
        "reviews",
        "letterboxd_reported",
    }
    assert set(payload["rewatches"]) == {
        "total_rewatches",
        "films_rewatched",
        "rewatch_rate",
        "most_rewatched",
        "average_rating_rewatched",
        "average_rating_once",
    }
    assert set(payload["reviews"]) == {
        "total_reviews",
        "with_text",
        "spoiler_reviews",
        "median_length_chars",
        "longest",
        "most_liked",
        "reviews_by_year",
        # Share of each year's watching that got written about.
        "writing_rate_by_year",
        "average_rating_reviewed",
        "average_rating_unreviewed",
    }
    assert payload["rewatches"]["most_rewatched"][0]["title"] == "Tracked Film"
    assert payload["reviews"]["total_reviews"] == 1


def test_the_route_serves_both_blocks_for_a_profile_with_neither(
    database: Session, client
) -> None:
    profile = _profile(database)
    _film(database, profile, title="Watched Once, Never Written Up", rating=3.5)
    user = _tracked_user(database, profile)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client(user).get(f"/api/profiles/{profile.username}/stats")

    payload = response.json()
    # Present and empty, so a client can render "none yet" rather than having
    # to tell a missing block from a failed one.
    assert payload["rewatches"]["most_rewatched"] == []
    assert payload["rewatches"]["average_rating_rewatched"] is None
    assert payload["reviews"]["total_reviews"] == 0
    assert payload["reviews"]["longest"] is None


def test_route_refuses_an_untracked_profile(database: Session, client) -> None:
    profile = _profile(database)
    user = _tracked_user(database, None)
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: user

    response = client(user).get(f"/api/profiles/{profile.username}/stats")

    assert response.status_code == 403


def test_a_bucket_reports_the_denominator_its_average_was_built_from(database):
    """`count` is every film in the bucket; the average covers the rated ones.

    The highlight card read "{average} average across {count} films", so a
    director with twelve films and three ratings advertised a three-rating
    average over twelve. The rated count now travels with the average.
    """
    profile = _profile(database, "viewer")
    for index in range(4):
        _film(
            database,
            profile,
            title=f"Horror {index}",
            # Only the first two carry a rating.
            rating=5.0 if index < 2 else None,
            genres=["Horror"],
        )

    stats = build_profile_stats(database, profile)
    horror = next(entry for entry in stats["genres"] if entry["label"] == "Horror")

    assert horror["count"] == 4
    assert horror["rated_count"] == 2
    assert horror["average_rating"] == 5.0


def test_the_writing_rate_measures_reviews_against_that_year_s_watching(database):
    """A rising review count can just mean a busier year.

    The share of viewing somebody chose to write about is the question, so the
    denominator has to be that year's watching rather than the total.
    """
    profile = _profile(database, "viewer")
    for index in range(4):
        movie = _film(database, profile, title=f"Watched {index}")
        _watch(database, profile, movie, date(2026, 3, 1))
    _review(database, profile, title="Watched 0", published=date(2026, 3, 2))
    _review(database, profile, title="Watched 1", published=date(2026, 3, 3))

    rows = build_profile_stats(database, profile)["reviews"]["writing_rate_by_year"]

    assert rows == [{"year": 2026, "reviews": 2, "films_watched": 4, "share": 0.5}]


def test_a_year_with_reviews_but_no_dated_watching_is_left_out(database):
    """An impossible rate is worse than an absent one."""
    profile = _profile(database, "viewer")
    _film(database, profile, title="Undated")
    _review(database, profile, title="Undated", published=date(2026, 3, 2))

    rows = build_profile_stats(database, profile)["reviews"]["writing_rate_by_year"]

    assert rows == []


def test_more_reviews_than_films_watched_reports_no_share(database):
    """Reviews are dated by publication, films by viewing.

    Somebody can publish this year about films seen years ago, so the counts
    can imply a share above 100%. That is not a share of anything, and
    clamping it to 100% would present "127 reviews of 35 films" as tidy.
    """
    profile = _profile(database, "viewer")
    movie = _film(database, profile, title="One Film")
    _watch(database, profile, movie, date(2026, 3, 1))
    for index in range(3):
        _review(database, profile, title=f"Older {index}", published=date(2026, 3, 2))

    row = build_profile_stats(database, profile)["reviews"]["writing_rate_by_year"][0]

    assert row["reviews"] == 3
    assert row["films_watched"] == 1
    assert row["share"] is None

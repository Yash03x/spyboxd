from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.models import (
    Base,
    Movie,
    Profile,
    Rating,
    SystemMetrics,
    WatchEvent,
)
from backend.database.repository import (
    DASHBOARD_SNAPSHOT_FORMAT_VERSION,
    AnalyticsRepository,
    RatingRepository,
)


AS_OF = date(2026, 7, 30)
EXPECTED_MONTHS = [
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
]


@pytest.fixture()
def database():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_compatibility(dbapi_connection, _connection_record):
        dbapi_connection.create_function(
            "char_length",
            1,
            lambda value: len(value) if value is not None else None,
        )

    Base.metadata.create_all(
        engine,
        tables=[
            Profile.__table__,
            Movie.__table__,
            Rating.__table__,
            WatchEvent.__table__,
            SystemMetrics.__table__,
        ],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _profile(profile_id: int, username: str) -> Profile:
    return Profile(
        id=profile_id,
        username=username,
        is_active=True,
        scraping_status="completed",
    )


def _movie(movie_id: int, title: str) -> Movie:
    normalized = title.casefold().replace(" ", "-")
    return Movie(
        id=movie_id,
        canonical_key=f"test:{normalized}",
        title=title,
        normalized_title=title.casefold(),
    )


def _watch_event(
    event_id: int,
    *,
    profile_id: int,
    movie_id: int,
    watched_date: date,
    rating: float | None = None,
    rewatch: bool = False,
    superseded: bool = False,
) -> WatchEvent:
    return WatchEvent(
        id=event_id,
        profile_id=profile_id,
        movie_id=movie_id,
        event_key=f"test-event:{event_id}",
        watched_date=watched_date,
        rating=rating,
        is_rewatch=rewatch,
        is_liked=False,
        has_review=False,
        tags=[],
        source_kind="diary_csv",
        superseded_at=(
            datetime(2026, 7, 1, tzinfo=timezone.utc)
            if superseded
            else None
        ),
    )


def _seed_monthly_activity(database) -> tuple[Profile, Profile]:
    alpha = _profile(1, "alpha")
    beta = _profile(2, "beta")
    film = _movie(1, "Repeat Film")
    second_film = _movie(2, "Second Film")
    database.add_all([alpha, beta, film, second_film])
    database.add_all(
        [
            # A rolling 365-day query incorrectly exposed this as a tiny Jul 2025 bucket.
            _watch_event(
                1,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=date(2025, 7, 31),
                rating=5.0,
            ),
            _watch_event(
                2,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=date(2025, 8, 1),
                rating=4.0,
            ),
            # Rewatches and unrated diary entries are still watch occurrences.
            _watch_event(
                3,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=date(2025, 8, 2),
                rating=None,
                rewatch=True,
            ),
            _watch_event(
                4,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=date(2025, 9, 2),
                rating=2.0,
            ),
            # A different film in the same month separates the unique-film grain
            # from the watch-event grain.
            _watch_event(
                5,
                profile_id=alpha.id,
                movie_id=second_film.id,
                watched_date=date(2025, 9, 3),
                rating=4.0,
            ),
            _watch_event(
                6,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=date(2025, 10, 1),
                rating=1.0,
                superseded=True,
            ),
            _watch_event(
                7,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=AS_OF,
                rating=3.5,
            ),
            # A bad future diary date must not leak into the current MTD bucket.
            _watch_event(
                8,
                profile_id=alpha.id,
                movie_id=film.id,
                watched_date=date(2026, 7, 31),
                rating=5.0,
            ),
            # A second profile proves explicit profile scoping remains intact.
            _watch_event(
                9,
                profile_id=beta.id,
                movie_id=film.id,
                watched_date=date(2026, 6, 15),
                rating=1.5,
            ),
        ]
    )
    database.commit()
    return alpha, beta


def test_global_monthly_activity_uses_exact_calendar_window_and_event_grain(database):
    alpha, _beta = _seed_monthly_activity(database)

    activity = RatingRepository(database).get_global_monthly_activity(
        profile_ids=[alpha.id],
        as_of=AS_OF,
    )

    assert [point["month"] for point in activity] == EXPECTED_MONTHS
    assert len(activity) == 12
    assert "2025-07" not in {point["month"] for point in activity}
    assert [point["is_partial"] for point in activity] == [False] * 11 + [True]
    assert [point["is_partial"] for point in activity] == [False] * 11 + [True]

    by_month = {point["month"]: point for point in activity}
    assert by_month["2025-08"]["movies_watched"] == 2
    # Two diary entries for the same film stay one unique film.
    assert by_month["2025-08"]["unique_movies"] == 1
    assert by_month["2025-08"]["average_rating"] == 4.0
    assert by_month["2025-09"]["movies_watched"] == 2
    assert by_month["2025-09"]["unique_movies"] == 2
    assert by_month["2025-09"]["average_rating"] == 3.0
    assert by_month["2025-10"]["movies_watched"] == 0
    assert by_month["2025-10"]["unique_movies"] == 0
    assert by_month["2025-10"]["average_rating"] is None
    assert by_month["2026-06"]["movies_watched"] == 0
    assert by_month["2026-07"]["movies_watched"] == 1
    assert by_month["2026-07"]["unique_movies"] == 1
    assert by_month["2026-07"]["average_rating"] == 3.5


def test_monthly_activity_zero_fills_only_a_nonempty_explicit_scope(database):
    alpha, _beta = _seed_monthly_activity(database)
    repository = RatingRepository(database)

    activity = repository.get_global_monthly_activity(
        profile_ids=[alpha.id],
        as_of=AS_OF,
    )

    assert len(activity) == 12
    assert sum(point["movies_watched"] == 0 for point in activity) == 9
    assert repository.get_global_monthly_activity(profile_ids=[], as_of=AS_OF) == []
    assert repository.get_global_monthly_activity(profile_ids=[999], as_of=AS_OF) == []


def test_first_day_of_month_marks_an_empty_current_bucket_as_partial(database):
    alpha, _beta = _seed_monthly_activity(database)

    activity = RatingRepository(database).get_global_monthly_activity(
        profile_ids=[alpha.id],
        as_of=date(2026, 7, 1),
    )

    assert activity[-1] == {
        "month": "2026-07",
        "movies_watched": 0,
        "unique_movies": 0,
        "average_rating": None,
        "is_partial": True,
    }


def test_per_profile_monthly_activity_matches_the_same_global_scope(database):
    alpha, _beta = _seed_monthly_activity(database)
    repository = RatingRepository(database)

    per_profile = repository.get_monthly_watch_stats(
        alpha.id,
        months=12,
        as_of=AS_OF,
    )
    scoped_global = repository.get_global_monthly_activity(
        profile_ids=[alpha.id],
        as_of=AS_OF,
    )

    assert per_profile == scoped_global


def _snapshot(profile_count: int = 1) -> dict:
    return {
        "system_stats": {
            "total_profiles": profile_count,
            "total_movies_tracked": 1,
            "total_reviews": 0,
            "global_avg_rating": 4.0,
        },
        "top_rated_movies": [],
        "rating_distribution": {"4.0": 1},
        "activity_data": [],
        "group_signals": {},
        "timestamp": "2026-07-30T10:00:00+00:00",
    }


def _snapshot_meta(as_of: date) -> dict:
    return {
        "format_version": DASHBOARD_SNAPSHOT_FORMAT_VERSION,
        "activity_window_start": "2025-08-01",
        "activity_as_of": as_of.isoformat(),
    }


def _seed_cached_snapshot(database, *, timestamp: datetime, meta: dict | None) -> dict:
    cached = _snapshot()
    metrics = {"dashboard_snapshot": cached}
    if meta is not None:
        metrics["dashboard_snapshot_meta"] = meta
    database.add(
        SystemMetrics(
            id=1,
            timestamp=timestamp,
            total_profiles=1,
            total_movies_tracked=1,
            total_reviews=0,
            active_scraping_jobs=0,
            metrics=metrics,
        )
    )
    database.commit()
    return cached


def test_dashboard_cache_reuses_matching_metadata(database, monkeypatch):
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)
    profile = _profile(1, "alpha")
    profile.updated_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    database.add(profile)
    cached = _seed_cached_snapshot(
        database,
        timestamp=now,
        meta=_snapshot_meta(now.date()),
    )
    repository = AnalyticsRepository(database)

    def unexpected_refresh(**_kwargs):
        raise AssertionError("a current snapshot must be reused")

    monkeypatch.setattr(repository, "refresh_dashboard_analytics_snapshot", unexpected_refresh)

    assert repository.get_dashboard_analytics_snapshot(now=now) == cached


@pytest.mark.parametrize(
    "meta",
    [
        None,
        {
            "format_version": DASHBOARD_SNAPSHOT_FORMAT_VERSION - 1,
            "activity_window_start": "2025-08-01",
            "activity_as_of": AS_OF.isoformat(),
        },
    ],
)
def test_dashboard_cache_invalidates_legacy_or_version_mismatched_metadata(
    database,
    monkeypatch,
    meta,
):
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)
    profile = _profile(1, "alpha")
    profile.updated_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    database.add(profile)
    _seed_cached_snapshot(database, timestamp=now, meta=meta)
    repository = AnalyticsRepository(database)
    rebuilt = {**_snapshot(), "timestamp": now.isoformat(), "rebuilt": True}
    calls = []

    def refresh(*, group_limit, top_movies_limit, now):
        calls.append((group_limit, top_movies_limit, now))
        return rebuilt

    monkeypatch.setattr(repository, "refresh_dashboard_analytics_snapshot", refresh)

    assert repository.get_dashboard_analytics_snapshot(now=now) == rebuilt
    assert calls == [(6, 10, now)]


def test_dashboard_cache_invalidates_on_day_rollover(database, monkeypatch):
    cached_at = datetime(2026, 7, 30, 23, 59, tzinfo=timezone.utc)
    requested_at = datetime(2026, 7, 31, 0, 1, tzinfo=timezone.utc)
    profile = _profile(1, "alpha")
    profile.updated_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    database.add(profile)
    _seed_cached_snapshot(
        database,
        timestamp=cached_at,
        meta=_snapshot_meta(cached_at.date()),
    )
    repository = AnalyticsRepository(database)
    calls = []

    def refresh(*, group_limit, top_movies_limit, now):
        calls.append((group_limit, top_movies_limit, now))
        return {**_snapshot(), "rebuilt": True}

    monkeypatch.setattr(repository, "refresh_dashboard_analytics_snapshot", refresh)

    result = repository.get_dashboard_analytics_snapshot(now=requested_at)

    assert result["rebuilt"] is True
    assert calls == [(6, 10, requested_at)]


def test_dashboard_cache_rejects_a_null_timestamp(database, monkeypatch):
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)
    profile = _profile(1, "alpha")
    profile.updated_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    database.add(profile)
    _seed_cached_snapshot(
        database,
        timestamp=now,
        meta=_snapshot_meta(now.date()),
    )
    metrics = database.get(SystemMetrics, 1)
    metrics.timestamp = None
    database.commit()
    repository = AnalyticsRepository(database)
    calls = []

    def refresh(*, group_limit, top_movies_limit, now):
        calls.append((group_limit, top_movies_limit, now))
        return {**_snapshot(), "rebuilt": True}

    monkeypatch.setattr(repository, "refresh_dashboard_analytics_snapshot", refresh)

    result = repository.get_dashboard_analytics_snapshot(now=now)

    assert result["rebuilt"] is True
    assert calls == [(6, 10, now)]


def test_dashboard_refresh_persists_matching_snapshot_metadata(database, monkeypatch):
    now = datetime(2026, 7, 30, 10, tzinfo=timezone.utc)
    repository = AnalyticsRepository(database)
    built = _snapshot(profile_count=0)
    calls = []

    def build(*, group_limit, top_movies_limit, now):
        calls.append((group_limit, top_movies_limit, now))
        return built

    monkeypatch.setattr(repository, "build_dashboard_analytics_snapshot", build)

    assert repository.refresh_dashboard_analytics_snapshot(now=now) == built

    metrics = database.query(SystemMetrics).one()
    assert metrics.timestamp == now.replace(tzinfo=None)
    assert metrics.metrics["dashboard_snapshot"] == built
    assert metrics.metrics["dashboard_snapshot_meta"] == _snapshot_meta(now.date())
    assert calls == [(6, 10, now)]

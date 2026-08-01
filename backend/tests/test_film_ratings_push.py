"""Residential-machine delivery of Letterboxd's own crowd rating per film.

The values can only be scraped where the scraper runs, so they arrive as a batch
over the same ingestion-token boundary as ``/upload/``. These tests pin the
contract that makes that batch safe to trust: match by slug, tolerate films
production has never seen, and never let a bad or absent value overwrite a good
one — the database's own CHECK constraint must never be the thing that catches a
malformed payload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from typing import Optional

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main as backend_main
from database.models import Movie
from scripts.push_letterboxd_ratings import collect_ratings, iter_batches


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


RATINGS_URL = "/api/films/letterboxd-ratings"


def _api_routes(routes):
    """Flatten routers the way test_route_access_matrix does.

    Newer FastAPI defers ``include_router`` behind a wrapper, so scanning
    ``app.routes`` for APIRoute instances finds nothing for an included
    router. The repo already hit this; mirror its traversal rather than
    depending on which version happens to be installed.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        included_router = getattr(route, "original_router", None)
        nested = getattr(included_router, "routes", None)
        if nested is not None:
            yield from _api_routes(nested)


INGESTION_TOKEN = "test-ingestion-token"
_MOVIE_IDS = count(1)


@pytest.fixture(autouse=True)
def ingestion_token(monkeypatch):
    """The API only honours X-Upload-Token when one is configured."""
    monkeypatch.setenv("INGESTION_API_TOKEN", INGESTION_TOKEN)


@pytest.fixture()
def database() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Movie.__table__.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(database) -> TestClient:
    backend_main.app.dependency_overrides[backend_main.get_db] = lambda: database
    try:
        yield TestClient(backend_main.app)
    finally:
        backend_main.app.dependency_overrides.clear()


def _film(
    database: Session,
    slug: Optional[str],
    *,
    url: Optional[str] = None,
    average: Optional[float] = None,
    rating_count: Optional[int] = None,
    synced_at: Optional[datetime] = None,
) -> Movie:
    movie_id = next(_MOVIE_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{slug or movie_id}",
        title=f"Film {movie_id}",
        normalized_title=f"film {movie_id}",
        release_year=2024,
        letterboxd_slug=slug,
        letterboxd_url=url,
        letterboxd_average_rating=average,
        letterboxd_rating_count=rating_count,
        letterboxd_rating_synced_at=synced_at,
    )
    database.add(movie)
    database.commit()
    return movie


def _post(client: TestClient, ratings: list[dict], *, token: Optional[str] = INGESTION_TOKEN):
    headers = {"X-Upload-Token": token} if token is not None else {}
    return client.post(RATINGS_URL, json={"ratings": ratings}, headers=headers)


def _entry(slug: str, **overrides) -> dict:
    entry = {"slug": slug, "average_rating": 4.0, "rating_count": 1000, "synced_at": None}
    entry.update(overrides)
    return entry


def _reload(database: Session, movie: Movie) -> Movie:
    database.expire_all()
    return database.get(Movie, movie.id)


def test_matching_slug_writes_the_letterboxd_average(client, database):
    movie = _film(database, "the-brutalist")

    response = _post(
        client,
        [
            _entry(
                "the-brutalist",
                average_rating=4.12,
                rating_count=250_000,
                synced_at="2026-08-01T10:30:00+00:00",
            )
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"received": 1, "updated": 1, "unmatched": 0, "skipped": 0}

    stored = _reload(database, movie)
    assert stored.letterboxd_average_rating == pytest.approx(4.12)
    assert stored.letterboxd_rating_count == 250_000
    assert stored.letterboxd_rating_synced_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 8, 1, 10, 30, tzinfo=timezone.utc
    )


def test_slug_matching_is_case_insensitive_in_both_directions(client, database):
    stored_lower = _film(database, "the-brutalist")
    stored_mixed = _film(database, "Nickel-Boys")

    response = _post(
        client,
        [
            _entry("THE-Brutalist", average_rating=4.12),
            _entry("nickel-boys", average_rating=3.87),
        ],
    )

    assert response.json() == {"received": 2, "updated": 2, "unmatched": 0, "skipped": 0}
    assert _reload(database, stored_lower).letterboxd_average_rating == pytest.approx(4.12)
    assert _reload(database, stored_mixed).letterboxd_average_rating == pytest.approx(3.87)


def test_unknown_slugs_are_reported_not_fatal(client, database):
    known = _film(database, "the-brutalist")

    response = _post(
        client,
        [
            _entry("the-brutalist", average_rating=4.12),
            _entry("a-film-production-has-never-seen", average_rating=3.5),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"received": 2, "updated": 1, "unmatched": 1, "skipped": 0}
    # The rest of the batch still landed.
    assert _reload(database, known).letterboxd_average_rating == pytest.approx(4.12)


def test_out_of_range_averages_are_skipped_before_the_check_constraint(client, database):
    high = _film(database, "too-high", average=3.0, rating_count=10)
    low = _film(database, "too-low", average=3.0, rating_count=10)

    response = _post(
        client,
        [
            _entry("too-high", average_rating=5.5),
            _entry("too-low", average_rating=-0.1),
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"received": 2, "updated": 0, "unmatched": 0, "skipped": 2}
    assert _reload(database, high).letterboxd_average_rating == pytest.approx(3.0)
    assert _reload(database, low).letterboxd_average_rating == pytest.approx(3.0)


@pytest.mark.parametrize("literal", ["NaN", "Infinity"])
def test_non_finite_averages_are_skipped(client, database, literal):
    """JSON's NaN/Infinity literals parse into floats; a range test rejects both."""
    movie = _film(database, "the-brutalist", average=3.0)

    response = client.post(
        RATINGS_URL,
        content=(
            '{"ratings": [{"slug": "the-brutalist", "average_rating": ' + literal + "}]}"
        ),
        headers={"X-Upload-Token": INGESTION_TOKEN, "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"received": 1, "updated": 0, "unmatched": 0, "skipped": 1}
    assert _reload(database, movie).letterboxd_average_rating == pytest.approx(3.0)


@pytest.mark.parametrize("rating_count", [-1, 10**19])
def test_impossible_rating_counts_are_skipped(client, database, rating_count):
    """A negative count breaks the CHECK; an astronomical one overflows BIGINT."""
    movie = _film(database, "the-brutalist", average=3.0, rating_count=10)

    response = _post(
        client,
        [
            _entry("the-brutalist", average_rating=4.0, rating_count=rating_count),
        ],
    )

    assert response.json() == {"received": 1, "updated": 0, "unmatched": 0, "skipped": 1}
    stored = _reload(database, movie)
    assert stored.letterboxd_average_rating == pytest.approx(3.0)
    assert stored.letterboxd_rating_count == 10


def test_null_average_never_clobbers_a_known_value(client, database):
    movie = _film(
        database,
        "the-brutalist",
        average=4.12,
        rating_count=250_000,
        synced_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    response = _post(client, [_entry("the-brutalist", average_rating=None, rating_count=999)])

    assert response.json() == {"received": 1, "updated": 0, "unmatched": 0, "skipped": 1}
    stored = _reload(database, movie)
    assert stored.letterboxd_average_rating == pytest.approx(4.12)
    assert stored.letterboxd_rating_count == 250_000
    assert stored.letterboxd_rating_synced_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 1, tzinfo=timezone.utc
    )


def test_null_rating_count_keeps_the_stored_count(client, database):
    movie = _film(database, "the-brutalist", average=4.0, rating_count=250_000)

    response = _post(client, [_entry("the-brutalist", average_rating=4.2, rating_count=None)])

    assert response.json() == {"received": 1, "updated": 1, "unmatched": 0, "skipped": 0}
    stored = _reload(database, movie)
    assert stored.letterboxd_average_rating == pytest.approx(4.2)
    assert stored.letterboxd_rating_count == 250_000


def test_missing_synced_at_falls_back_to_the_request_time(client, database):
    movie = _film(database, "the-brutalist")
    before = datetime.now(timezone.utc)

    assert _post(client, [_entry("the-brutalist", synced_at=None)]).status_code == 200

    stamped = _reload(database, movie).letterboxd_rating_synced_at.replace(tzinfo=timezone.utc)
    assert stamped >= before.replace(microsecond=0)


def test_counts_always_account_for_every_submitted_entry(client, database):
    _film(database, "the-brutalist")

    response = _post(
        client,
        [
            _entry("the-brutalist", average_rating=4.12),
            _entry("never-seen-here", average_rating=3.0),
            _entry("the-brutalist", average_rating=99.0),
            _entry("   ", average_rating=3.0),
        ],
    )

    body = response.json()
    assert body["received"] == 4
    assert body["updated"] + body["unmatched"] + body["skipped"] == body["received"]
    assert body == {"received": 4, "updated": 1, "unmatched": 1, "skipped": 2}


def test_oversized_batch_is_rejected_outright(client, database):
    movie = _film(database, "the-brutalist", average=3.0)

    response = _post(
        client,
        [_entry("the-brutalist", average_rating=4.12) for _ in range(1001)],
    )

    assert response.status_code == 422
    assert _reload(database, movie).letterboxd_average_rating == pytest.approx(3.0)


def test_maximum_batch_size_is_accepted(client, database):
    _film(database, "the-brutalist")

    response = _post(
        client,
        [_entry(f"film-{index}", average_rating=3.0) for index in range(999)]
        + [_entry("the-brutalist", average_rating=4.12)],
    )

    assert response.status_code == 200
    assert response.json()["received"] == 1000


def test_empty_batch_is_rejected(client):
    assert _post(client, []).status_code == 422


def test_ingestion_token_is_required(client, database):
    movie = _film(database, "the-brutalist", average=3.0)
    entries = [_entry("the-brutalist", average_rating=4.12)]

    assert _post(client, entries, token=None).status_code == 401
    assert _post(client, entries, token="not-the-token").status_code == 401
    assert _reload(database, movie).letterboxd_average_rating == pytest.approx(3.0)

    assert _post(client, entries).status_code == 200


def test_route_carries_the_upload_trust_boundary():
    route = next(
        candidate
        for candidate in _api_routes(backend_main.app.routes)
        if candidate.path == RATINGS_URL
    )
    names = {dependency.call.__name__ for dependency in route.dependant.dependencies}

    # The route declares its own gate rather than inheriting one from how it is
    # mounted, so the trust boundary is visible on the route itself.
    assert "get_active_upload_user" in names


def test_pusher_collects_only_films_with_a_known_average(database):
    _film(database, "the-brutalist", average=4.12, rating_count=250_000)
    _film(database, None, url="https://letterboxd.com/film/nickel-boys/", average=3.87)
    _film(database, "no-average-yet")
    _film(database, None, url=None, average=2.5)

    entries, skipped_no_slug = collect_ratings(database)

    assert skipped_no_slug == 1
    assert [entry["slug"] for entry in entries] == ["the-brutalist", "nickel-boys"]
    assert entries[0]["average_rating"] == pytest.approx(4.12)
    assert entries[0]["rating_count"] == 250_000
    assert entries[1]["rating_count"] is None


def test_pusher_respects_the_limit_and_chunks_into_batches(database):
    for index in range(5):
        _film(database, f"film-{index}", average=3.0)

    entries, _ = collect_ratings(database, limit=3)
    batches = list(iter_batches(entries, 2))

    assert len(entries) == 3
    assert [len(batch) for batch in batches] == [2, 1]

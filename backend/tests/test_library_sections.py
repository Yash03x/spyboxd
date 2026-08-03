"""Films, Tonight and Data: what these panels are allowed to claim.

The recurring theme is the difference between a zero and an absence. A runtime
band nobody queued has no ratio, not a ratio of zero. A surface that was never
read is not a surface that came back empty. A profile whose header was never
fetched does not have zero films. Each of those is a sentence in the product's
copy, and each is pinned below.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from itertools import count
from typing import Optional

import pytest
from sqlalchemy import BigInteger, Integer, create_engine, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import (
    LostEntry,
    Movie,
    MovieEnrichment,
    MovieList,
    MovieListItem,
    MovieWatchProvider,
    Profile,
    ProfileFeedState,
    ProfileFilm,
    ProfileSync,
    Review,
    SyncDataset,
    WatchEvent,
    WatchlistItem,
)
from services.data_health import (
    SURFACE_ORDER,
    build_counts,
    build_feeds,
    build_ledger,
    build_lost_list_films,
    build_request_latency,
    build_watch_event_freshness,
)
from services.films import (
    build_atlas,
    build_collections,
    build_filmographies,
    build_keywords,
    build_liked_vs_rated,
    build_match_rate,
    build_metadata_gaps,
    build_queue_age,
    build_runtime,
)
from services.tonight import (
    build_availability,
    build_blind_spot_favourites,
    build_list_cadence,
    build_list_only_films,
)


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
    Profile.__table__,
    ProfileSync.__table__,
    SyncDataset.__table__,
    ProfileFeedState.__table__,
    Movie.__table__,
    MovieEnrichment.__table__,
    MovieWatchProvider.__table__,
    ProfileFilm.__table__,
    WatchEvent.__table__,
    WatchlistItem.__table__,
    MovieList.__table__,
    MovieListItem.__table__,
    LostEntry.__table__,
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

    # `movie_watch_providers` pins its region to two characters with a
    # `char_length` check. SQLite has no such function, so the CHECK would fail
    # at insert rather than at create -- register it instead of dropping the
    # constraint, so the test exercises the same guard production does.
    @event.listens_for(engine, "connect")
    def _register_char_length(connection, _record):  # noqa: ANN001
        connection.create_function("char_length", 1, lambda value: len(value or ""))

    for table in TABLES:
        table.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


_IDS = count(1)


def _profile(database: Session, username: str, **kwargs) -> Profile:
    profile = Profile(username=username, scraping_status="completed", is_active=True, **kwargs)
    database.add(profile)
    database.commit()
    return profile


def _movie(
    database: Session,
    title: str,
    *,
    runtime: Optional[int] = None,
    collection: Optional[str] = None,
    enrich: bool = True,
    crowd: Optional[float] = None,
    year: int = 2000,
) -> Movie:
    movie_id = next(_IDS)
    movie = Movie(
        id=movie_id,
        canonical_key=f"letterboxd:{title}-{movie_id}",
        title=title,
        normalized_title=title.casefold(),
        release_year=year,
        tmdb_id=movie_id if enrich else None,
        letterboxd_average_rating=crowd,
    )
    database.add(movie)
    if enrich:
        # TMDB's response is nested under `details`, and this fixture used to
        # put the collection at the top level instead. Both the fixture and the
        # service agreed on a shape production never stores, so the panel was
        # empty on real data while the test passed.
        payload = (
            {"details": {"belongs_to_collection": {"name": collection}}} if collection else {}
        )
        database.add(
            MovieEnrichment(movie_id=movie_id, runtime_minutes=runtime, raw_payload=payload)
        )
    database.commit()
    return movie


def _film(
    database: Session,
    profile: Profile,
    movie: Movie,
    *,
    rating: Optional[float] = None,
    liked: bool = False,
) -> None:
    database.add(
        ProfileFilm(
            profile_id=profile.id,
            movie_id=movie.id,
            rating=rating,
            is_liked=liked,
            tags=[],
            watch_count=1,
        )
    )
    database.commit()


def _queued(database: Session, profile: Profile, movie: Movie, added: Optional[date]) -> None:
    database.add(
        WatchlistItem(profile_id=profile.id, movie_id=movie.id, added_date=added)
    )
    database.commit()


def _sync(database: Session, profile: Profile, *, datasets: dict[str, int]) -> ProfileSync:
    sync = ProfileSync(
        profile_id=profile.id,
        source_kind="full_html_upload",
        source_fingerprint=f"fingerprint-{next(_IDS)}",
        importer_version="v5",
        status="completed",
        completed_at=datetime(2026, 8, 3, 8, tzinfo=timezone.utc),
        started_at=datetime(2026, 8, 3, 7, tzinfo=timezone.utc),
    )
    database.add(sync)
    database.commit()
    for name, rows in datasets.items():
        database.add(
            SyncDataset(
                profile_sync_id=sync.id,
                dataset_name=name,
                source_row_count=rows,
                imported_row_count=rows,
                is_authoritative=True,
            )
        )
    database.commit()
    return sync


def test_a_runtime_band_nobody_queued_has_no_ratio(database: Session) -> None:
    """Null rather than infinity. Dividing by an empty queue would print a
    ratio that describes nothing, and printing zero would claim the opposite."""

    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Long", runtime=200))

    band = next(
        entry for entry in build_runtime(database, [viewer])["bands"] if entry["label"] == "over 150"
    )

    assert band["watched"] == 1
    assert band["queued"] == 0
    assert band["ratio"] is None


def test_a_single_film_is_not_a_series(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Alone", collection="Lonely Collection"))
    for title in ("First", "Second"):
        _film(database, viewer, _movie(database, title, collection="Real Collection"))

    series = build_collections(database, [viewer])["series"]

    assert [entry["name"] for entry in series] == ["Real Collection"]
    assert series[0]["films"] == 2


def test_no_films_panel_ships_the_whole_tmdb_payload(database: Session) -> None:
    """`raw_payload` is the entire TMDB response, watch providers included.

    Selecting it as a column pulled tens of megabytes per request, and the five
    Films panels all fire on first paint, which was enough to stop the API
    answering anything at all. The one fragment anybody needs out of it is
    extracted by JSON path in the database, so the bare column must never
    appear in a SELECT again.
    """

    viewer = _profile(database, "viewer")
    for title in ("First", "Second"):
        _film(database, viewer, _movie(database, title, runtime=100, collection="Series"))

    statements: list[str] = []

    @event.listens_for(database.get_bind(), "before_cursor_execute")
    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    for build in (
        build_keywords,
        build_runtime,
        build_atlas,
        build_collections,
        build_filmographies,
        build_metadata_gaps,
        build_match_rate,
        build_liked_vs_rated,
    ):
        build(database, [viewer])

    event.remove(database.get_bind(), "before_cursor_execute", _record)

    mentions = 0
    for statement in statements:
        for index in _offsets(statement, "movie_enrichments.raw_payload"):
            mentions += 1
            preceding = statement[:index]
            assert preceding.rstrip().endswith("JSON_EXTRACT("), (
                "raw_payload was selected whole rather than by path:\n" + statement
            )

    # Otherwise the loop above passes by never running, and stays passing after
    # somebody drops the column back into a SELECT under a different name.
    assert mentions, "no panel read raw_payload at all — this guard has stopped guarding"


def _offsets(haystack: str, needle: str):
    start = haystack.find(needle)
    while start != -1:
        yield start
        start = haystack.find(needle, start + 1)


def test_an_unrated_series_has_no_average(database: Session) -> None:
    viewer = _profile(database, "viewer")
    for title in ("One", "Two"):
        _film(database, viewer, _movie(database, title, collection="Unrated Collection"))

    assert build_collections(database, [viewer])["series"][0]["average_rating"] is None


def test_the_match_rate_states_the_ceiling_it_imposes(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Enriched"))
    _film(database, viewer, _movie(database, "Bare", enrich=False))

    result = build_match_rate(database, [viewer])

    assert result["films"] == 2
    assert result["enriched"] == 1
    assert result["ratio"] == 0.5
    assert "it is their maximum" in result["caveat"]


def test_an_unrated_film_lands_in_neither_and_the_caveat_says_so(database: Session) -> None:
    """An unrated film has no score, so it cannot be told apart from a film
    rated low by this panel alone. Saying so is the difference between a
    quadrant and a claim."""

    viewer = _profile(database, "viewer")
    _film(database, viewer, _movie(database, "Unrated"))

    result = build_liked_vs_rated(database, [viewer])
    neither = next(quad for quad in result["quadrants"] if quad["tag"] == "NEITHER")

    assert neither["films"] == 1
    assert "an unrated film has no score" in result["caveat"].lower()


def test_queue_age_excludes_entries_with_no_added_date(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _queued(database, viewer, _movie(database, "Dated"), date(2019, 3, 4))
    _queued(database, viewer, _movie(database, "Undated"), None)

    result = build_queue_age(database, [viewer])

    assert result["dated"] == 1
    assert result["total"] == 2
    assert [film["title"] for film in result["films"]] == ["Dated"]
    assert "excluded rather than guessed at" in result["caveat"]


def test_a_blind_spot_favourite_needs_exactly_one_holder(database: Session) -> None:
    left = _profile(database, "left")
    right = _profile(database, "right")
    solo = _movie(database, "Solo")
    shared = _movie(database, "Shared")

    _film(database, left, solo, rating=5.0)
    _film(database, left, shared, rating=5.0)
    _film(database, right, shared, rating=5.0)

    films = build_blind_spot_favourites(database, [left, right])["films"]

    assert [film["title"] for film in films] == ["Solo"]


def test_an_unrated_film_cannot_be_a_blind_spot_favourite(database: Session) -> None:
    left = _profile(database, "left")
    right = _profile(database, "right")
    _film(database, left, _movie(database, "Loved But Unrated"))

    assert build_blind_spot_favourites(database, [left, right])["count"] == 0


def test_list_only_films_need_more_than_one_list(database: Session) -> None:
    viewer = _profile(database, "viewer")
    once = _movie(database, "On One List")
    twice = _movie(database, "On Two Lists")

    for index, name in enumerate(("A", "B")):
        movie_list = MovieList(profile_id=viewer.id, name=name, is_public=True)
        database.add(movie_list)
        database.commit()
        database.add(MovieListItem(movie_list_id=movie_list.id, movie_id=twice.id, position=1))
        if index == 0:
            database.add(MovieListItem(movie_list_id=movie_list.id, movie_id=once.id, position=2))
        database.commit()

    films = build_list_only_films(database, [viewer])["films"]

    assert [film["title"] for film in films] == ["On Two Lists"]


def test_a_blind_spot_is_drawn_from_the_selection_s_own_public_lists(database: Session) -> None:
    """Three panels on this tab said "readable lists" and meant three things.

    Unscoped, this counted every list in the store: other people's, and the
    private ones an account export brings in. Both are now excluded, so the
    word means the same thing everywhere on the tab.
    """

    viewer = _profile(database, "viewer")
    stranger = _profile(database, "stranger")
    theirs = _movie(database, "On A Stranger's Lists")
    hidden = _movie(database, "On Private Lists")

    for index in range(2):
        outside = MovieList(profile_id=stranger.id, name=f"Stranger {index}", is_public=True)
        private = MovieList(profile_id=viewer.id, name=f"Private {index}", is_public=False)
        database.add_all([outside, private])
        database.commit()
        database.add(MovieListItem(movie_list_id=outside.id, movie_id=theirs.id, position=1))
        database.add(MovieListItem(movie_list_id=private.id, movie_id=hidden.id, position=1))
        database.commit()

    payload = build_list_only_films(database, [viewer])

    assert payload["films"] == []
    assert "own public lists" in payload["caveat"]


def test_a_profile_with_no_lists_is_named_rather_than_ranked_last(database: Session) -> None:
    viewer = _profile(database, "viewer")

    entry = build_list_cadence(database, [viewer])["profiles"][0]

    assert entry["lists"] == 0
    assert entry["read"] == "Never made one"


def test_availability_reports_staleness_and_claims_no_countdown(database: Session) -> None:
    viewer = _profile(database, "viewer")
    movie = _movie(database, "Streaming")
    _queued(database, viewer, movie, date(2025, 1, 1))
    database.add(
        MovieWatchProvider(
            movie_id=movie.id,
            region="IN",
            provider_id=8,
            provider_name="Netflix",
            provider_type="flatrate",
            fetched_at=datetime.now(timezone.utc) - timedelta(days=30),
        )
    )
    database.commit()

    result = build_availability(database, [viewer], region="IN")

    assert result["films"][0]["providers"] == ["Netflix"]
    stale = next(entry for entry in result["regions"] if entry["region"] == "IN")
    assert stale["stale"] is True
    # The whole point of the panel: no expiry is claimed anywhere.
    assert "days left" in result["caveat"]
    assert "invented rather than read" in result["caveat"]


def test_a_region_never_fetched_is_not_a_region_that_carries_nothing(database: Session) -> None:
    """The shortlist read "Nothing queued is carried in IN".

    Only DE had ever been fetched. Reporting a region we have never read as one
    that carries none of the queue is the single thing this section is not
    allowed to do, and the freshness panel beside it already said as much.
    """

    viewer = _profile(database, "viewer")
    movie = _movie(database, "Streaming")
    _queued(database, viewer, movie, date(2025, 1, 1))
    database.add(
        MovieWatchProvider(
            movie_id=movie.id,
            region="DE",
            provider_id=8,
            provider_name="Netflix",
            provider_type="flatrate",
            fetched_at=datetime.now(timezone.utc),
        )
    )
    database.commit()

    result = build_availability(database, [viewer], region="IN")

    assert result["films"] == []
    assert result["region_read"] is False
    assert "never been read" in result["caveat"]
    assert "DE" in result["caveat"]

    read = build_availability(database, [viewer], region="DE")
    assert read["region_read"] is True
    assert "never been read" not in read["caveat"]


def test_a_private_list_is_counted_for_its_owner_and_named_as_unshown(database: Session) -> None:
    """Curating is curating, but the other panels on the tab cannot see it.

    A bare list count here read as a flat contradiction of "Work through a
    list", which only ever shows public ones.
    """

    viewer = _profile(database, "viewer")
    database.add_all(
        [
            MovieList(profile_id=viewer.id, name="Shown", is_public=True),
            MovieList(profile_id=viewer.id, name="Hidden", is_public=False),
        ]
    )
    database.commit()

    payload = build_list_cadence(database, [viewer])
    entry = payload["profiles"][0]

    assert entry["lists"] == 2
    assert entry["public_lists"] == 1
    assert payload["private_lists"] == 1
    assert "appear in no other panel on this tab" in payload["caveat"]


def test_a_refresh_that_skips_a_surface_does_not_unread_it(database: Session) -> None:
    """The ledger said "Follows: never read" beside a rendered follow graph.

    Scoped to each profile's single latest sync, a surface an older run had
    read and a newer one did not touch fell out of the ledger entirely and was
    reported as never read.
    """

    viewer = _profile(database, "viewer")
    _sync(database, viewer, datasets={"following": 35})
    later = _sync(database, viewer, datasets={"films": 500})
    later.completed_at = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)
    database.commit()

    surfaces = {row["dataset"]: row for row in build_ledger(database, [viewer])["surfaces"]}

    assert surfaces["films"]["rows"] == 500
    assert surfaces["following"]["rows"] == 35
    assert surfaces["following"]["result"] != "Never read for any selected profile"
    # A surface genuinely never read still says so.
    assert surfaces["comments"]["result"] == "Never read for any selected profile"


def test_every_ledger_surface_is_a_name_the_importer_actually_writes(
    database: Session,
) -> None:
    """The ledger asked for a dataset called "follows".

    The importer has only ever written "following" and "followers", so that row
    could report nothing but "never read" for the life of the product — beside
    a follow graph drawing 35 edges. A surface nobody can ever fill is worse
    than a missing row: it reads as a finding.
    """

    from services.ingestion import _upsert_sync_datasets  # noqa: PLC0415

    written = _upsert_sync_datasets.__code__.co_consts
    names = {value for const in written if isinstance(const, tuple) for value in const}

    for dataset, _label in SURFACE_ORDER:
        assert dataset in names, f"the ledger reads {dataset!r}, which no importer writes"


def test_a_header_never_read_holds_no_film_total_rather_than_zero(database: Session) -> None:
    """Data › Profiles showed "0" beside a profile's own 299 watches.

    The count came from the tracked-profile list, which does not cover every
    profile the panel renders, and a miss fell through to zero. It travels with
    the row now, and stays null when the profile header has never been read.
    """

    read = _profile(database, "read", reported_total_films=564)
    unread = _profile(database, "unread")

    payload = build_watch_event_freshness(database, [read, unread])
    by_name = {entry["username"]: entry for entry in payload["profiles"]}

    assert by_name["read"]["films_held"] == 564
    assert by_name["unread"]["films_held"] is None
    assert "holds no number rather than a zero" in payload["caveat"]


def test_a_surface_never_read_is_not_a_surface_that_came_back_empty(database: Session) -> None:
    viewer = _profile(database, "viewer")
    _sync(database, viewer, datasets={"films": 1_200})

    surfaces = {row["dataset"]: row for row in build_ledger(database, [viewer])["surfaces"]}

    assert surfaces["films"]["rows"] == 1_200
    assert surfaces["films"]["authoritative_profiles"] == 1
    assert surfaces["likes"]["result"] == "Never read for any selected profile"


def test_a_profile_with_no_stated_total_has_no_gap(database: Session) -> None:
    """Never read is not zero. A gap of 0 would claim we had checked."""

    read = _profile(database, "read", reported_total_films=10)
    unread = _profile(database, "unread")
    _film(database, read, _movie(database, "One"))

    entries = {entry["username"]: entry for entry in build_counts(database, [read, unread])["profiles"]}

    assert entries["read"]["gap"] == 9
    assert entries["unread"]["theirs"] is None
    assert entries["unread"]["gap"] is None


def test_a_backing_off_feed_reports_why(database: Session) -> None:
    viewer = _profile(database, "viewer")
    database.add(
        ProfileFeedState(
            profile_id=viewer.id,
            feed_url="https://letterboxd.com/viewer/rss/",
            consecutive_failures=4,
            last_http_status=429,
        )
    )
    database.commit()

    feed = build_feeds(database, [viewer])["feeds"][0]

    assert feed["tone"] == "bad"
    assert "429" in feed["why"]


def test_latency_refuses_to_estimate_without_a_completed_run(database: Session) -> None:
    viewer = _profile(database, "viewer")

    result = build_request_latency(database, [viewer])

    assert result["median_seconds"] is None
    assert "a promise rather than a figure" in result["caveat"]


def test_a_deleted_list_keeps_the_films_and_the_order(database: Session) -> None:
    owner = _profile(database, "owner")
    movie = _movie(database, "Recovered")
    movie_list = MovieList(
        profile_id=owner.id,
        name="2023 ranked",
        removed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    database.add(movie_list)
    database.commit()
    database.add(MovieListItem(movie_list_id=movie_list.id, movie_id=movie.id, position=3))
    database.commit()

    films = build_lost_list_films(database, [owner])["films"]

    assert films[0]["title"] == "Recovered"
    assert films[0]["position"] == 3
    assert films[0]["list_name"] == "2023 ranked"

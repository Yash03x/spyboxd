from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from backend.database.models import (
    Movie,
    MovieList,
    MovieListItem,
    Profile,
    ProfileDataChange,
    ProfileFeedState,
    ProfileFavoriteMovie,
    ProfileFilm,
    ProfileFollowEdge,
    ProfileSync,
    Rating,
    Review,
    SyncDataset,
    WatchEvent,
    WatchlistItem,
)
from backend.services.import_contracts import MovieIdentity, diary_event_key
from backend.services.rss_incremental import (
    MAX_RSS_BYTES,
    RSSFeedError,
    RSSFeedTooLarge,
    _record_poll_failure,
    acquire_profile_feed_lease,
    due_profiles,
    parse_letterboxd_rss,
    poll_profile_feed,
)


@compiles(BigInteger, "sqlite")
def _compile_bigint_as_integer(_type, _compiler, **_kwargs):
    # SQLite only auto-increments columns whose declared type is exactly INTEGER.
    return "INTEGER"


def _item(
    *,
    guid: str,
    title: str,
    slug: str,
    watched_date: str,
    published: str,
    year: int = 2026,
    rating: float = 4.5,
    rewatch: str = "No",
    liked: str = "Yes",
    description: str = "<p>Watched.</p>",
) -> str:
    return f"""
      <item>
        <title>{title}, {year}</title>
        <link>https://letterboxd.com/viewer/film/{slug}/</link>
        <guid isPermaLink="false">{guid}</guid>
        <pubDate>{published}</pubDate>
        <letterboxd:watchedDate>{watched_date}</letterboxd:watchedDate>
        <letterboxd:rewatch>{rewatch}</letterboxd:rewatch>
        <letterboxd:filmTitle>{title}</letterboxd:filmTitle>
        <letterboxd:filmYear>{year}</letterboxd:filmYear>
        <letterboxd:memberRating>{rating}</letterboxd:memberRating>
        <letterboxd:memberLike>{liked}</letterboxd:memberLike>
        <tmdb:movieId>42</tmdb:movieId>
        <description><![CDATA[{description}]]></description>
      </item>
    """


def _feed(*items: str, list_item: bool = False) -> bytes:
    extra = """
      <item>
        <title>A public list</title>
        <link>https://letterboxd.com/viewer/list/a-public-list/</link>
        <guid isPermaLink="false">letterboxd-list-77</guid>
        <pubDate>Tue, 28 Jul 2026 05:00:00 +1200</pubDate>
        <description><![CDATA[<p>Not a watch event.</p>]]></description>
      </item>
    """ if list_item else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"
      xmlns:letterboxd="https://letterboxd.com"
      xmlns:tmdb="https://themoviedb.org">
      <channel><title>Letterboxd - viewer</title>{''.join(items)}{extra}</channel>
    </rss>""".encode("utf-8")


ARRIVAL_ITEM = _item(
    guid="letterboxd-review-200",
    title="Arrival",
    slug="arrival",
    year=2016,
    watched_date="2026-07-17",
    published="Tue, 28 Jul 2026 04:51:43 +1200",
    description=(
        '<p><img src="https://a.ltrbxd.com/resized/arrival.jpg" /></p>'
        '<p>Loved <b>it</b>.<br />This may contain spoilers.</p>'
        '<script>alert("never store me")</script>'
    ),
)

HEAT_ITEM = _item(
    guid="letterboxd-watch-100",
    title="Heat",
    slug="heat-1995",
    year=1995,
    watched_date="2026-07-10",
    published="Sat, 11 Jul 2026 01:00:00 +1200",
    rating=4.0,
    liked="No",
)


class FakeResponse:
    def __init__(self, body: bytes = b"", *, status: int = 200, headers=None):
        self.status_code = status
        self.headers = dict(headers or {})
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self._body), chunk_size):
            yield self._body[offset : offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses: FakeResponse):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.fixture()
def database():
    engine = create_engine("sqlite:///:memory:")
    for table in (
        Profile.__table__,
        ProfileSync.__table__,
        ProfileFeedState.__table__,
        SyncDataset.__table__,
        Movie.__table__,
        Rating.__table__,
        ProfileFilm.__table__,
        ProfileFollowEdge.__table__,
        WatchEvent.__table__,
        Review.__table__,
        WatchlistItem.__table__,
        MovieList.__table__,
        MovieListItem.__table__,
        ProfileFavoriteMovie.__table__,
        ProfileDataChange.__table__,
    ):
        table.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _seed_authoritative_baseline(db):
    completed_at = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    profile = Profile(
        id=1,
        username="viewer",
        is_active=True,
        scraping_status="completed",
        total_reviews=0,
    )
    baseline = ProfileSync(
        id=1,
        profile_id=1,
        source_kind="full_html_upload",
        source_fingerprint="full-baseline",
        importer_version="3",
        status="completed",
        completed_at=completed_at,
        coverage={},
        stats={},
        manifest={},
    )
    db.add_all([profile, baseline])
    db.flush()
    profile.last_profile_sync_id = baseline.id
    db.add_all(
        [
            SyncDataset(
                profile_sync_id=baseline.id,
                dataset_name="films",
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=True,
                metadata_payload={},
            ),
            SyncDataset(
                profile_sync_id=baseline.id,
                dataset_name="diary",
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=True,
                metadata_payload={},
            ),
        ]
    )
    movie = Movie(
        id=10,
        canonical_key="letterboxd-slug:heat-1995",
        letterboxd_slug="heat-1995",
        title="Heat",
        normalized_title="heat",
        release_year=1995,
        letterboxd_url="https://letterboxd.com/film/heat-1995/",
        first_seen_profile_sync_id=baseline.id,
        last_seen_profile_sync_id=baseline.id,
    )
    rating = Rating(
        id=10,
        profile_id=profile.id,
        movie_id=movie.id,
        movie_title=movie.title,
        movie_year=movie.release_year,
        rating=4.0,
        watched_date=date(2026, 7, 10),
        is_liked=False,
        first_seen_profile_sync_id=baseline.id,
        last_seen_profile_sync_id=baseline.id,
        tags=[],
    )
    db.add_all([movie, rating])
    db.flush()
    profile_film = ProfileFilm(
        id=10,
        profile_id=profile.id,
        movie_id=movie.id,
        legacy_rating_id=rating.id,
        rating=4.0,
        is_liked=False,
        tags=[],
        first_watched_date=date(2026, 7, 10),
        latest_watched_date=date(2026, 7, 10),
        watch_count=1,
        rewatch_count=0,
        has_review=False,
        first_seen_profile_sync_id=baseline.id,
        last_seen_profile_sync_id=baseline.id,
    )
    db.add(profile_film)
    db.flush()
    identity = MovieIdentity(
        title=movie.title,
        release_year=movie.release_year,
        letterboxd_slug=movie.letterboxd_slug,
        letterboxd_url=movie.letterboxd_url,
    )
    db.add(
        WatchEvent(
            id=10,
            profile_id=profile.id,
            movie_id=movie.id,
            profile_film_id=profile_film.id,
            event_key=diary_event_key(
                username=profile.username,
                identity=identity,
                watched_date=date(2026, 7, 10),
                occurrence=1,
                source_entry_id="100",
            ),
            watched_date=date(2026, 7, 10),
            rating=4.0,
            is_rewatch=False,
            is_liked=False,
            has_review=False,
            tags=[],
            source_kind="full_html_upload",
            source_entry_id="100",
            first_seen_profile_sync_id=baseline.id,
            last_seen_profile_sync_id=baseline.id,
        )
    )
    db.commit()
    return profile


def test_parser_uses_watched_date_and_sanitizes_review_html():
    items = parse_letterboxd_rss(_feed(ARRIVAL_ITEM, list_item=True))

    assert len(items) == 1
    item = items[0]
    assert item.watched_date == date(2026, 7, 17)
    assert item.published_date == date(2026, 7, 28)
    assert item.published_at == datetime(2026, 7, 27, 16, 51, 43, tzinfo=timezone.utc)
    assert item.has_review is True
    assert item.review_text == "Loved\nit\n.\nThis may contain spoilers."
    assert item.contains_spoilers is True
    assert "<" not in item.review_text
    assert "alert" not in item.review_text
    assert item.poster_url == "https://a.ltrbxd.com/resized/arrival.jpg"
    assert len(item.content_sha256) == 64


def test_parser_never_uses_pubdate_as_a_missing_watch_date():
    payload = _feed(
        """
        <item>
          <title>Heat, 1995</title>
          <link>https://letterboxd.com/viewer/film/heat-1995/</link>
          <guid>letterboxd-review-1</guid>
          <pubDate>Tue, 28 Jul 2026 04:51:43 +1200</pubDate>
          <letterboxd:filmTitle>Heat</letterboxd:filmTitle>
          <letterboxd:filmYear>1995</letterboxd:filmYear>
        </item>
        """
    )

    assert parse_letterboxd_rss(payload) == []


def test_parser_rejects_oversize_and_entity_documents():
    with pytest.raises(RSSFeedTooLarge):
        parse_letterboxd_rss(b"x" * (MAX_RSS_BYTES + 1))
    with pytest.raises(RSSFeedTooLarge):
        parse_letterboxd_rss(
            b"x" * (MAX_RSS_BYTES + 1),
            max_bytes=MAX_RSS_BYTES * 2,
        )
    with pytest.raises(RSSFeedError, match="declarations"):
        parse_letterboxd_rss(b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "x">]><rss/>')


def test_parser_rejects_conflicting_content_for_one_guid():
    changed_arrival = ARRIVAL_ITEM.replace(
        "<letterboxd:memberRating>4.5</letterboxd:memberRating>",
        "<letterboxd:memberRating>1.0</letterboxd:memberRating>",
    )

    with pytest.raises(RSSFeedError, match="conflicting entries"):
        parse_letterboxd_rss(_feed(ARRIVAL_ITEM, changed_arrival))


def test_poll_requires_authoritative_films_and_diary_before_fetch(database):
    profile = Profile(id=1, username="viewer", is_active=True)
    database.add(profile)
    database.commit()
    client = FakeSession(FakeResponse(_feed(ARRIVAL_ITEM)))

    result = poll_profile_feed(database, profile, session=client)

    assert result["status"] == "baseline_required"
    assert client.calls == []
    assert database.query(ProfileSync).count() == 0


def test_poll_is_additive_sanitized_and_idempotent(database):
    profile = _seed_authoritative_baseline(database)
    body = _feed(ARRIVAL_ITEM, HEAT_ITEM, list_item=True)
    first_response = FakeResponse(
        body,
        headers={"ETag": '"feed-v1"', "Last-Modified": "Tue, 28 Jul 2026 05:00:00 GMT"},
    )
    second_response = FakeResponse(body, headers={"ETag": '"feed-v1"'})
    client = FakeSession(first_response, second_response)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)

    first = poll_profile_feed(database, profile, session=client, now=instant)

    assert first["status"] == "updated"
    assert first["initial_seed"] is True
    assert first["watch_events_created"] == 1
    assert first["profile_films_created"] == 1
    assert first["ratings_created"] == 1
    assert first["reviews_created"] == 1
    assert database.query(ProfileFeedState).one().next_poll_at == (
        instant + timedelta(minutes=10)
    ).replace(tzinfo=None)
    assert database.query(WatchEvent).count() == 2
    assert database.query(ProfileFilm).count() == 2
    assert database.query(Rating).count() == 2
    assert database.query(Review).count() == 1

    arrival_event = (
        database.query(WatchEvent)
        .join(Movie, Movie.id == WatchEvent.movie_id)
        .filter(Movie.letterboxd_slug == "arrival")
        .one()
    )
    assert arrival_event.watched_date == date(2026, 7, 17)
    assert arrival_event.source_kind == "rss_incremental"
    assert arrival_event.source_entry_id == "letterboxd-review-200"
    assert database.query(WatchEvent).filter(WatchEvent.source_entry_id == "100").count() == 1

    review = database.query(Review).one()
    assert review.published_date == date(2026, 7, 17)
    assert review.published_at == datetime(2026, 7, 27, 16, 51, 43)
    assert review.review_text == "Loved\nit\n.\nThis may contain spoilers."
    assert "<" not in review.review_text
    assert "alert" not in review.review_text
    assert review.contains_spoilers is False
    expected_key_material = "1|letterboxd-slug:arrival|2026-07-17|1"
    assert review.source_review_key == (
        "review:" + hashlib.sha256(expected_key_material.encode("utf-8")).hexdigest()
    )

    rss_sync = database.query(ProfileSync).filter(ProfileSync.source_kind == "rss_incremental").one()
    assert rss_sync.status == "completed"
    assert rss_sync.manifest["absence_is_not_a_deletion"] is True
    assert all(dataset.is_authoritative is False for dataset in rss_sync.datasets)
    assert {change.change_type for change in database.query(ProfileDataChange).all()} >= {
        "film_added",
        "diary_added",
        "review_added",
    }
    assert all("<" not in str(change.after_payload) for change in database.query(ProfileDataChange).all())

    second = poll_profile_feed(
        database,
        profile,
        session=client,
        now=instant + timedelta(hours=2),
    )

    assert second["status"] == "unchanged"
    assert database.query(ProfileSync).filter(ProfileSync.source_kind == "rss_incremental").count() == 1
    assert database.query(WatchEvent).count() == 2
    assert client.calls[1][1]["headers"]["If-None-Match"] == '"feed-v1"'
    assert first_response.closed is True
    assert second_response.closed is True


def test_initial_seed_preserves_known_authoritative_values(database):
    profile = _seed_authoritative_baseline(database)
    movie = database.get(Movie, 10)
    event = database.get(WatchEvent, 10)
    profile_film = database.get(ProfileFilm, 10)
    event.has_review = True
    profile_film.has_review = True
    baseline_review = Review(
        id=10,
        profile_id=profile.id,
        movie_id=movie.id,
        first_seen_profile_sync_id=1,
        last_seen_profile_sync_id=1,
        source_review_key="baseline-heat-review",
        source_url="https://letterboxd.com/viewer/film/heat-1995/",
        published_at=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        published_date=date(2026, 7, 10),
        movie_title=movie.title,
        movie_year=movie.release_year,
        review_text="Authoritative baseline prose.",
        rating=4.0,
        contains_spoilers=True,
        likes_count=3,
        comments_count=1,
        tags=[],
    )
    database.add(baseline_review)
    database.commit()
    conflicting_seed = _item(
        guid="letterboxd-review-100",
        title="Heat",
        slug="heat-1995",
        year=1995,
        watched_date="2026-07-10",
        published="Wed, 29 Jul 2026 01:00:00 +1200",
        rating=1.0,
        liked="Yes",
        description="<p>Different RSS formatting that says spoilers.</p>",
    )

    result = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(conflicting_seed))),
        now=datetime(2026, 7, 29, 10, tzinfo=timezone.utc),
    )
    database.expire_all()

    assert result["status"] == "unchanged"
    assert result["initial_seed"] is True
    assert result["changes"] == 0
    assert database.get(WatchEvent, 10).rating == 4.0
    assert database.get(WatchEvent, 10).is_liked is False
    assert database.get(ProfileFilm, 10).rating == 4.0
    assert database.get(ProfileFilm, 10).is_liked is False
    assert database.get(Rating, 10).rating == 4.0
    assert database.get(Rating, 10).is_liked is False
    review = database.get(Review, 10)
    assert review.review_text == "Authoritative baseline prose."
    assert review.contains_spoilers is True
    assert review.published_at == datetime(2026, 7, 28, 13)
    assert review.likes_count == 3
    assert review.comments_count == 1
    rss_sync = database.query(ProfileSync).filter(ProfileSync.source_kind == "rss_incremental").one()
    assert rss_sync.status == "skipped"
    assert database.query(ProfileDataChange).count() == 0
    assert database.get(Profile, profile.id).last_profile_sync_id == 1


def test_later_feed_revision_updates_known_rating_and_like(database):
    profile = _seed_authoritative_baseline(database)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
    initial = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(HEAT_ITEM))),
        now=instant,
    )
    changed_heat = HEAT_ITEM.replace(
        "<letterboxd:memberRating>4.0</letterboxd:memberRating>",
        "<letterboxd:memberRating>4.5</letterboxd:memberRating>",
    ).replace(
        "<letterboxd:memberLike>No</letterboxd:memberLike>",
        "<letterboxd:memberLike>Yes</letterboxd:memberLike>",
    )

    changed = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(changed_heat))),
        now=instant + timedelta(hours=2),
    )

    assert initial["status"] == "unchanged"
    assert initial["initial_seed"] is True
    assert changed["status"] == "updated"
    assert changed["initial_seed"] is False
    assert database.get(WatchEvent, 10).rating == 4.5
    assert database.get(WatchEvent, 10).is_liked is True
    assert database.get(ProfileFilm, 10).rating == 4.5
    assert database.get(ProfileFilm, 10).is_liked is True
    assert database.get(Rating, 10).rating == 4.5
    assert database.get(Rating, 10).is_liked is True
    assert {change.change_type for change in database.query(ProfileDataChange).all()} == {
        "rating_changed",
        "like_changed",
    }


def test_omitted_feed_rating_never_clears_a_known_rating(database):
    profile = _seed_authoritative_baseline(database)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
    poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(HEAT_ITEM))),
        now=instant,
    )
    without_rating = HEAT_ITEM.replace(
        "        <letterboxd:memberRating>4.0</letterboxd:memberRating>\n",
        "",
    )

    result = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(without_rating))),
        now=instant + timedelta(hours=2),
    )

    assert result["status"] == "unchanged"
    assert database.get(WatchEvent, 10).rating == 4.0
    assert database.get(ProfileFilm, 10).rating == 4.0
    assert database.get(Rating, 10).rating == 4.0
    assert database.query(ProfileDataChange).count() == 0


def test_missing_feed_entries_are_never_deleted_or_superseded(database):
    profile = _seed_authoritative_baseline(database)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
    poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(ARRIVAL_ITEM, HEAT_ITEM))),
        now=instant,
    )

    result = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(ARRIVAL_ITEM))),
        now=instant + timedelta(hours=2),
    )

    assert result["status"] == "unchanged"
    assert database.query(WatchEvent).count() == 2
    assert database.query(WatchEvent).filter(WatchEvent.superseded_at.is_not(None)).count() == 0
    assert database.query(ProfileFilm).filter(ProfileFilm.removed_at.is_not(None)).count() == 0
    assert database.query(Review).filter(Review.removed_at.is_not(None)).count() == 0
    rss_syncs = (
        database.query(ProfileSync)
        .filter(ProfileSync.source_kind == "rss_incremental")
        .order_by(ProfileSync.id.asc())
        .all()
    )
    assert [sync.status for sync in rss_syncs] == ["completed", "skipped"]
    assert database.query(Profile).one().last_profile_sync_id == rss_syncs[0].id


def test_no_overlap_marks_overflow_without_mutating_profile_data(database):
    profile = _seed_authoritative_baseline(database)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
    poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(ARRIVAL_ITEM, HEAT_ITEM))),
        now=instant,
    )
    events_before = database.query(WatchEvent).count()
    syncs_before = database.query(ProfileSync).count()
    stranger = _item(
        guid="letterboxd-watch-999",
        title="Stranger Than Fiction",
        slug="stranger-than-fiction-2006",
        year=2006,
        watched_date="2026-07-29",
        published="Wed, 29 Jul 2026 12:00:00 +1200",
    )

    result = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(_feed(stranger))),
        now=instant + timedelta(hours=2),
    )

    assert result["status"] == "overflow"
    assert result["requires_full_sync"] is True
    assert database.query(WatchEvent).count() == events_before
    assert database.query(ProfileSync).count() == syncs_before
    feed_state = database.query(ProfileFeedState).one()
    assert "full sync required" in feed_state.last_error
    assert feed_state.requires_full_sync is True
    assert feed_state.reconciliation_reason == "rss_window_no_overlap"

    blocked_client = FakeSession(FakeResponse(_feed(stranger)))
    blocked = poll_profile_feed(
        database,
        profile,
        session=blocked_client,
        now=instant + timedelta(hours=4),
    )
    assert blocked["status"] == "full_sync_required"
    assert blocked_client.calls == []


def test_stale_overflow_cannot_override_a_newer_authoritative_refresh(database):
    profile = _seed_authoritative_baseline(database)
    state = ProfileFeedState(
        profile_id=profile.id,
        feed_url="https://letterboxd.com/viewer/rss/",
        activity_guids=["old-guid"],
        requires_full_sync=False,
        consecutive_failures=0,
    )
    database.add(state)
    expected_next_poll_at = datetime(2026, 7, 29, 11, 1, tzinfo=timezone.utc)
    state.next_poll_at = expected_next_poll_at
    newer = ProfileSync(
        id=2,
        profile_id=profile.id,
        source_kind="full_html_upload",
        source_fingerprint="newer-full-baseline",
        importer_version="4",
        status="completed",
        completed_at=datetime(2026, 7, 29, 11, tzinfo=timezone.utc),
        coverage={},
        stats={},
        manifest={},
    )
    database.add(newer)
    database.flush()
    database.add_all(
        [
            SyncDataset(
                profile_sync_id=newer.id,
                dataset_name=name,
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=True,
                metadata_payload={},
            )
            for name in ("films", "diary")
        ]
    )
    database.commit()

    result = _record_poll_failure(
        database,
        profile_id=profile.id,
        observed_baseline_id=1,
        now=datetime(2026, 7, 29, 10, tzinfo=timezone.utc),
        message="RSS recent window has no overlap with stored GUIDs; full sync required",
        http_status=200,
        interval_seconds=600,
        max_backoff_seconds=3600,
        requires_full_sync=True,
        reconciliation_reason="rss_window_no_overlap",
    )

    database.refresh(state)
    assert result["requires_full_sync"] is False
    assert result["reconciled_by_profile_sync_id"] == newer.id
    assert state.requires_full_sync is False
    assert state.reconciliation_reason is None
    assert state.last_error is None
    assert state.consecutive_failures == 0
    assert state.next_poll_at.replace(tzinfo=timezone.utc) == expected_next_poll_at


def test_http_body_cap_fails_before_any_incremental_sync(database):
    profile = _seed_authoritative_baseline(database)
    response = FakeResponse(
        b"not read",
        headers={"Content-Length": str(MAX_RSS_BYTES + 1)},
    )

    result = poll_profile_feed(database, profile, session=FakeSession(response))

    assert result["status"] == "failed"
    assert "exceeds" in result["error"]
    assert database.query(ProfileSync).filter(ProfileSync.source_kind == "rss_incremental").count() == 0


def test_due_profiles_and_committed_lease(database):
    profile = _seed_authoritative_baseline(database)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)

    assert [row.id for row in due_profiles(database, now=instant)] == [profile.id]
    assert acquire_profile_feed_lease(database, profile.id, now=instant, lease_seconds=300) is True
    assert acquire_profile_feed_lease(database, profile.id, now=instant, lease_seconds=300) is False
    assert due_profiles(database, now=instant) == []
    assert [row.id for row in due_profiles(database, now=instant + timedelta(seconds=301))] == [profile.id]


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        ("10800", datetime(2026, 7, 29, 13, tzinfo=timezone.utc)),
        ("Wed, 29 Jul 2026 15:00:00 GMT", datetime(2026, 7, 29, 15, tzinfo=timezone.utc)),
    ],
)
def test_rate_limit_retry_after_wins_over_shorter_backoff(database, retry_after, expected):
    profile = _seed_authoritative_baseline(database)
    instant = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)

    result = poll_profile_feed(
        database,
        profile,
        session=FakeSession(FakeResponse(status=429, headers={"Retry-After": retry_after})),
        now=instant,
        interval_seconds=3600,
    )

    assert result["status"] == "failed"
    assert result["error"].endswith("HTTP 429")
    assert database.query(ProfileFeedState).one().next_poll_at == expected.replace(tzinfo=None)

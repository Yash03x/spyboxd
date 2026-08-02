from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import ClerkUser, _payload_grants_admin
from backend import main as backend_main
from backend.database.models import (
    AppUser,
    Base,
    Movie,
    MovieEnrichment,
    MovieWatchProvider,
    Profile,
    ProfileAccessRequest,
    ProfileFavoriteMovie,
    ProfileFilm,
    ProfileFollowEdge,
    Rating,
    Review,
    UserTrackedProfile,
    WatchEvent,
    WatchlistItem,
)
from backend.database.repository import AnalyticsRepository
from backend.services.insights import InsightRequestError, InsightsService
from backend.services import profile_access as profile_access_service
from backend.services.profile_access import (
    accessible_profiles,
    authorize_profile_usernames,
    decide_profile_request,
    fulfill_pending_requests,
    list_profile_catalog,
    list_profile_requests,
    normalize_profile_username,
    provision_app_user_identity,
    reopen_fulfilled_requests_for_profile,
    require_profile_access,
    track_profile_by_id,
    track_or_request_profile,
    tracked_profiles,
    untrack_profile,
)


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
            AppUser.__table__,
            UserTrackedProfile.__table__,
            ProfileAccessRequest.__table__,
            ProfileFollowEdge.__table__,
            Movie.__table__,
            MovieEnrichment.__table__,
            MovieWatchProvider.__table__,
            ProfileFilm.__table__,
            ProfileFavoriteMovie.__table__,
            WatchlistItem.__table__,
            Rating.__table__,
            Review.__table__,
            WatchEvent.__table__,
        ],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(
    user_id: str = "user_one",
    *,
    admin: bool = False,
    letterboxd_username: str | None = None,
) -> ClerkUser:
    return ClerkUser(
        user_id=user_id,
        session_id="session",
        is_admin=admin,
        letterboxd_username=letterboxd_username,
    )


def _legacy_user(
    database,
    user_id: str = "user_one",
    *,
    admin: bool = False,
) -> ClerkUser:
    app_user = (
        database.query(AppUser)
        .filter(AppUser.clerk_user_id == user_id)
        .first()
    )
    if app_user is None:
        database.add(
            AppUser(
                clerk_user_id=user_id,
                primary_profile_required=False,
            )
        )
        database.commit()
    return _user(user_id, admin=admin)


def _link_handle(database, clerk_user_id: str, handle: str) -> None:
    """Give an app user a Letterboxd identity.

    The catalog is scoped to the caller's own follow-graph corner, which cannot
    be computed without one.
    """
    app_user = (
        database.query(AppUser).filter(AppUser.clerk_user_id == clerk_user_id).one()
    )
    app_user.letterboxd_username = handle
    database.commit()


def _profile(profile_id: int, username: str, *, completed: bool = True) -> Profile:
    return Profile(
        id=profile_id,
        username=username,
        is_active=True,
        scraping_status="completed" if completed else "pending",
    )


@pytest.mark.parametrize(
    "raw_username,canonical",
    [
        ("ab", "ab"),
        (" FilmFan_7 ", "FilmFan_7"),
        ("@Viewer", "Viewer"),
        ("123456789012345", "123456789012345"),
    ],
)
def test_letterboxd_username_validation_accepts_the_source_contract(
    raw_username,
    canonical,
):
    assert normalize_profile_username(raw_username) == (
        canonical,
        canonical.casefold(),
    )


@pytest.mark.parametrize(
    "raw_username",
    [
        "a",
        "1234567890123456",
        "with-hyphen",
        "has space",
        "film.fan",
        "fílmfan",
    ],
)
def test_letterboxd_username_validation_rejects_non_letterboxd_handles(
    raw_username,
):
    with pytest.raises(HTTPException) as raised:
        normalize_profile_username(raw_username)
    assert raised.value.status_code == 400


def test_primary_identity_tracks_an_existing_profile_atomically_and_idempotently(
    database,
):
    database.add(_profile(1, "Alpha"))
    database.commit()
    user = _user(letterboxd_username="aLpHa")

    first = provision_app_user_identity(database, user)
    second = provision_app_user_identity(database, user)

    assert first == second == {
        "letterboxd_username": "aLpHa",
        "primary_profile_status": "tracked",
    }
    app_user = database.query(AppUser).one()
    assert app_user.letterboxd_username == "aLpHa"
    assert app_user.primary_profile_required is True
    assert database.query(UserTrackedProfile).count() == 1
    assert database.query(ProfileAccessRequest).count() == 0


def test_primary_identity_creates_one_pending_request_and_preserves_rejection(
    database,
):
    user = _user(letterboxd_username="New_User")

    first = provision_app_user_identity(database, user)
    repeated = provision_app_user_identity(database, user)
    request = database.query(ProfileAccessRequest).one()
    request.status = "rejected"
    database.commit()
    after_rejection = provision_app_user_identity(database, user)

    assert first["primary_profile_status"] == "pending"
    assert repeated["primary_profile_status"] == "pending"
    assert after_rejection["primary_profile_status"] == "rejected"
    assert database.query(ProfileAccessRequest).count() == 1
    assert database.query(UserTrackedProfile).count() == 0


def test_primary_identity_fulfillment_is_not_blocked_by_optional_tracking_limit(
    database,
    monkeypatch,
):
    monkeypatch.setenv("SPYBOXD_MAX_TRACKED_PROFILES_PER_USER", "1")
    optional = _profile(1, "Optional")
    database.add(optional)
    database.commit()
    user = _user(letterboxd_username="Primary")

    assert provision_app_user_identity(database, user)["primary_profile_status"] == "pending"
    track_profile_by_id(database, user, optional.id)

    primary = _profile(2, "Primary")
    database.add(primary)
    database.commit()

    assert fulfill_pending_requests(database, primary) == 1
    assert {
        profile.username for profile in tracked_profiles(database, user)
    } == {"Optional", "Primary"}


def test_primary_identity_failure_rolls_back_the_new_user_and_access_mapping(
    database,
    monkeypatch,
):
    database.add(_profile(1, "Alpha"))
    database.commit()

    def fail_tracking(*_args, **_kwargs):
        raise RuntimeError("synthetic tracking failure")

    monkeypatch.setattr(profile_access_service, "_add_tracking", fail_tracking)

    with pytest.raises(RuntimeError, match="synthetic tracking failure"):
        provision_app_user_identity(
            database,
            _user(letterboxd_username="Alpha"),
        )

    assert database.query(AppUser).count() == 0
    assert database.query(UserTrackedProfile).count() == 0
    assert database.query(ProfileAccessRequest).count() == 0


def test_primary_identity_is_unique_case_insensitively(database):
    provision_app_user_identity(
        database,
        _user("first_user", letterboxd_username="FilmFan"),
    )

    with pytest.raises(HTTPException) as raised:
        provision_app_user_identity(
            database,
            _user("second_user", letterboxd_username="filmfan"),
        )

    assert raised.value.status_code == 409
    assert database.query(AppUser).count() == 1
    assert database.query(ProfileAccessRequest).count() == 1


def test_legacy_admin_and_ingestion_service_do_not_require_the_new_claim(database):
    legacy = provision_app_user_identity(database, _user("admin", admin=True))
    ingestion = provision_app_user_identity(
        database,
        ClerkUser(user_id="ingestion-token", session_id=None, is_admin=True),
    )

    assert legacy == {
        "letterboxd_username": None,
        "primary_profile_status": "unconfigured",
    }
    assert ingestion == legacy
    assert [user.clerk_user_id for user in database.query(AppUser).all()] == [
        "admin"
    ]
    assert database.query(AppUser).one().primary_profile_required is False


def test_new_non_admin_fails_closed_without_the_signed_username_claim(database):
    user = _user("missing_identity")

    with pytest.raises(HTTPException) as direct:
        provision_app_user_identity(database, user)
    with pytest.raises(HTTPException) as first_route:
        list_profile_catalog(database, user)

    assert direct.value.status_code == 409
    assert first_route.value.status_code == 409
    assert database.query(AppUser).count() == 0
    assert database.query(ProfileAccessRequest).count() == 0


def test_grandfathered_admin_claim_does_not_create_a_profile_request(database):
    database.add(
        AppUser(
            clerk_user_id="admin",
            primary_profile_required=False,
        )
    )
    database.commit()

    identity = provision_app_user_identity(
        database,
        _user("admin", admin=True, letterboxd_username="admin"),
    )

    assert identity == {
        "letterboxd_username": "admin",
        "primary_profile_status": "unlinked",
    }
    assert database.query(AppUser).one().letterboxd_username == "admin"
    assert database.query(ProfileAccessRequest).count() == 0
    assert database.query(UserTrackedProfile).count() == 0


def test_stored_primary_identity_is_not_silently_retargeted(database):
    database.add(
        AppUser(
            clerk_user_id="user_one",
            letterboxd_username="Alpha",
        )
    )
    database.commit()

    with pytest.raises(HTTPException) as raised:
        provision_app_user_identity(
            database,
            _user(letterboxd_username="Beta"),
        )

    assert raised.value.status_code == 409
    assert database.query(AppUser).one().letterboxd_username == "Alpha"
    assert database.query(ProfileAccessRequest).count() == 0


def test_primary_profile_cannot_be_untracked(database):
    alpha = _profile(1, "Alpha")
    beta = _profile(2, "Beta")
    database.add_all([alpha, beta])
    database.commit()
    user = _user(letterboxd_username="Alpha")
    provision_app_user_identity(database, user)
    track_profile_by_id(database, user, beta.id)

    with pytest.raises(HTTPException) as raised:
        untrack_profile(database, user, "alpha")

    assert raised.value.status_code == 409
    assert untrack_profile(database, user, "Beta") is True
    assert [profile.username for profile in tracked_profiles(database, user)] == [
        "Alpha"
    ]


def test_me_returns_canonical_identity_and_primary_profile_status(database):
    backend_main.app.dependency_overrides[backend_main.get_db] = lambda: database
    backend_main.app.dependency_overrides[backend_main.get_current_user] = lambda: _user(
        "new_user",
        letterboxd_username="FilmFan",
    )
    client = TestClient(backend_main.app)
    try:
        response = client.get("/api/me")
    finally:
        backend_main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "new_user",
        "is_admin": False,
        "letterboxd_username": "FilmFan",
        "primary_profile_status": "pending",
    }


def test_profile_analysis_exposes_review_spoiler_metadata(database):
    profile = _profile(1, "Alpha")
    database.add(profile)
    database.add(
        Review(
            id=1,
            profile_id=profile.id,
            movie_title="Spoiler Film",
            movie_year=2026,
            review_text="The actual spoiler review.",
            rating=4.5,
            published_date=date(2026, 7, 30),
            contains_spoilers=True,
            tags=[],
        )
    )
    database.commit()

    analysis = asyncio.run(
        backend_main.get_analysis(
            "Alpha",
            db=database,
            user=_user("admin_user", admin=True),
        )
    )

    assert analysis["recent_reviews"] == [
        {
            "movie_title": "Spoiler Film",
            "movie_year": 2026,
            "rating": 4.5,
            "review_text": "The actual spoiler review.",
            "contains_spoilers": True,
            "published_date": "2026-07-30",
            "likes_count": 0,
            "tags": [],
        }
    ]


def test_profile_analysis_header_carries_the_letterboxd_profile_surface(database):
    profile = _profile(1, "Alpha")
    profile.display_name = "Alpha Viewer"
    profile.bio = "Watches too much."
    profile.location = "Chennai"
    profile.website = "alpha.example.com"
    profile.pronoun = "they/them"
    profile.member_badge = "Patron"
    profile.profile_image_url = "https://images.example.com/alpha.jpg"
    profile.letterboxd_person_id = 998877
    profile.join_date = date(2019, 4, 2)
    profile.reported_total_films = 1420
    profile.reported_total_reviews = 210
    profile.reported_total_lists = 12
    profile.reported_watchlist_count = 340
    profile.following_count = 88
    profile.followers_count = 190
    profile.avg_rating = 3.75
    profile.total_reviews = 7
    profile.stats_snapshot = {"hours": 2130, "directors": 640, "longest_streak": 19}
    profile.stats_synced_at = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    database.add(profile)
    database.add_all(
        [
            Movie(
                id=1,
                canonical_key="letterboxd:fav-one",
                title="Favourite One",
                normalized_title="favourite one",
                release_year=1999,
                poster_url="https://images.example.com/one.jpg",
                letterboxd_url="https://letterboxd.com/film/favourite-one/",
            ),
            Movie(
                id=2,
                canonical_key="letterboxd:fav-two",
                title="Favourite Two",
                normalized_title="favourite two",
                release_year=2004,
                letterboxd_slug="favourite-two",
            ),
        ]
    )
    database.flush()
    database.add_all(
        [
            ProfileFavoriteMovie(id=2, profile_id=profile.id, movie_id=2, position=2),
            ProfileFavoriteMovie(id=1, profile_id=profile.id, movie_id=1, position=1),
        ]
    )
    database.commit()

    analysis = asyncio.run(
        backend_main.get_analysis(
            "Alpha",
            db=database,
            user=_user("admin_user", admin=True),
        )
    )
    header = analysis["profile_header"]

    assert header["display_name"] == "Alpha Viewer"
    assert header["bio"] == "Watches too much."
    assert header["location"] == "Chennai"
    assert header["website"] == "alpha.example.com"
    assert header["website_url"] == "https://alpha.example.com"
    assert header["pronoun"] == "they/them"
    assert header["member_badge"] == "Patron"
    assert header["avatar_url"] == "https://images.example.com/alpha.jpg"
    assert header["letterboxd_url"] == "https://letterboxd.com/Alpha/"
    assert header["letterboxd_person_id"] == 998877
    assert header["join_date"] == "2019-04-02"
    assert header["films_count"] == 1420
    assert header["reviews_count"] == 210
    assert header["lists_count"] == 12
    assert header["watchlist_count"] == 340
    assert header["following_count"] == 88
    assert header["followers_count"] == 190
    assert header["avg_rating"] == 3.75
    assert header["total_reviews"] == 7
    assert header["stats_snapshot"] == {"hours": 2130, "directors": 640, "longest_streak": 19}
    assert header["stats_synced_at"].startswith("2026-07-31T09:00:00")
    assert header["favorites"] == [
        {
            "position": 1,
            "title": "Favourite One",
            "year": 1999,
            "poster_url": "https://images.example.com/one.jpg",
            "letterboxd_url": "https://letterboxd.com/film/favourite-one/",
            # A stated favourite is not automatically a logged one.
            "in_library": False,
            "own_rating": None,
        },
        {
            "position": 2,
            "title": "Favourite Two",
            "year": 2004,
            "poster_url": None,
            "letterboxd_url": "https://letterboxd.com/film/favourite-two/",
            "in_library": False,
            "own_rating": None,
        },
    ]


def test_profile_analysis_header_reports_unobserved_metadata_as_null(database):
    profile = _profile(1, "Alpha")
    profile.website = "javascript:alert(1)"
    database.add(profile)
    database.commit()

    analysis = asyncio.run(
        backend_main.get_analysis(
            "Alpha",
            db=database,
            user=_user("admin_user", admin=True),
        )
    )
    header = analysis["profile_header"]

    assert header["username"] == "Alpha"
    assert header["website_url"] is None
    assert header["favorites"] == []
    assert header["stats_snapshot"] is None
    assert [
        header[field]
        for field in (
            "display_name",
            "bio",
            "location",
            "pronoun",
            "member_badge",
            "avatar_url",
            "join_date",
            "films_count",
            "reviews_count",
            "lists_count",
            "watchlist_count",
            "following_count",
            "followers_count",
            "films_this_year",
            "stats_synced_at",
        )
    ] == [None] * 15


def test_existing_completed_profile_is_tracked_case_insensitively_and_idempotently(database):
    database.add_all([_profile(1, "Alpha"), _profile(2, "Beta")])
    database.commit()
    user = _legacy_user(database)

    first = track_or_request_profile(database, user, "aLpHa")
    second = track_or_request_profile(database, user, "ALPHA")

    assert first["status"] == "tracked"
    assert first["profile"]["username"] == "Alpha"
    assert second["status"] == "tracked"
    assert database.query(UserTrackedProfile).count() == 1
    assert authorize_profile_usernames(database, user, None) == ["Alpha"]
    with pytest.raises(HTTPException) as raised:
        authorize_profile_usernames(database, user, ["Beta"])
    assert raised.value.status_code == 403


def test_signed_in_catalog_lists_only_selectable_profiles_and_tracks_by_id(database):
    selectable = _profile(1, "Alpha")
    selectable.display_name = "Alpha Viewer"
    pending = _profile(2, "Pending", completed=False)
    inactive = _profile(3, "Inactive")
    inactive.is_active = False
    database.add_all([selectable, pending, inactive])
    database.add(
        Rating(
            id=1,
            profile_id=selectable.id,
            movie_title="Catalog Film",
            movie_year=2026,
            rating=4.0,
        )
    )
    # The catalog is scoped to the caller's own follow-graph corner, so the
    # selectable profile has to be connected to them to appear at all.
    database.add(
        ProfileFollowEdge(
            id=1,
            profile_id=1,
            direction="follower",
            counterpart_username="viewer",
            counterpart_username_normalized="viewer",
        )
    )
    database.commit()
    user = _legacy_user(database)
    _link_handle(database, "user_one", "viewer")

    initial = list_profile_catalog(database, user)
    assert initial["total"] == 1
    assert initial["profiles"] == [
        {
            "id": 1,
            "username": "Alpha",
            "display_name": "Alpha Viewer",
            "profile_image_url": None,
            "total_films": 1,
            "is_tracked": False,
        }
    ]

    tracked = track_profile_by_id(database, user, selectable.id)
    assert tracked["status"] == "tracked"
    assert list_profile_catalog(database, user)["profiles"][0]["is_tracked"] is True

    with pytest.raises(HTTPException) as unavailable:
        track_profile_by_id(database, user, pending.id)
    assert unavailable.value.status_code == 404


def test_profile_catalog_tracking_is_isolated_per_user(database):
    database.add(_profile(1, "Alpha"))
    for index, handle in enumerate(("first_viewer", "second_viewer"), start=1):
        database.add(
            ProfileFollowEdge(
                id=index,
                profile_id=1,
                direction="follower",
                counterpart_username=handle,
                counterpart_username_normalized=handle,
            )
        )
    database.commit()
    first_user = _legacy_user(database, "first")
    second_user = _legacy_user(database, "second")
    _link_handle(database, "first", "first_viewer")
    _link_handle(database, "second", "second_viewer")

    track_profile_by_id(database, first_user, 1)

    assert list_profile_catalog(database, first_user)["profiles"][0]["is_tracked"] is True
    assert list_profile_catalog(database, second_user)["profiles"][0]["is_tracked"] is False


def test_admin_personal_monitoring_is_separate_from_global_library_access(database):
    alpha = _profile(1, "Alpha")
    beta = _profile(2, "Beta")
    database.add_all([alpha, beta])
    database.commit()
    admin_user = _user("admin", admin=True)

    track_profile_by_id(database, admin_user, alpha.id)

    assert [profile.username for profile in tracked_profiles(database, admin_user)] == ["Alpha"]
    assert {profile.username for profile in accessible_profiles(database, admin_user)} == {"Alpha", "Beta"}


def test_non_admin_cannot_request_global_dashboard_scope(database):
    user = _legacy_user(database)
    with pytest.raises(HTTPException) as forbidden:
        asyncio.run(
            backend_main.get_consolidated_dashboard_analytics(
                scope="global",
                db=database,
                user=user,
            )
        )
    assert forbidden.value.status_code == 403


def test_omitted_dashboard_scope_preserves_admin_global_default(database, monkeypatch):
    sentinel = {"scope": "global"}
    monkeypatch.setattr(
        backend_main.AnalyticsRepository,
        "get_dashboard_analytics_snapshot",
        lambda self, *, group_limit, top_movies_limit: sentinel,
    )

    result = asyncio.run(
        backend_main.get_consolidated_dashboard_analytics(
            scope=None,
            db=database,
            user=_user("admin", admin=True),
        )
    )

    assert result is sentinel


def test_omitted_dashboard_scope_defaults_non_admin_to_tracked_profiles(database):
    alpha = _profile(1, "Alpha")
    beta = _profile(2, "Beta")
    database.add_all([alpha, beta])
    database.add_all(
        [
            Rating(id=1, profile_id=alpha.id, movie_title="Alpha Film", rating=4.0),
            Rating(id=2, profile_id=beta.id, movie_title="Beta Film", rating=1.0),
        ]
    )
    database.commit()
    user = _legacy_user(database)
    track_profile_by_id(database, user, alpha.id)

    result = asyncio.run(
        backend_main.get_consolidated_dashboard_analytics(
            scope=None,
            db=database,
            user=user,
        )
    )

    assert result["system_stats"]["total_profiles"] == 1
    assert result["system_stats"]["total_movies_tracked"] == 1
    assert result["rating_distribution"] == {"4.0": 1}


def test_explicit_tracked_dashboard_scope_limits_admin_to_personal_set(database):
    alpha = _profile(1, "Alpha")
    beta = _profile(2, "Beta")
    database.add_all([alpha, beta])
    database.add_all(
        [
            Rating(id=1, profile_id=alpha.id, movie_title="Alpha Film", rating=4.0),
            Rating(id=2, profile_id=beta.id, movie_title="Beta Film", rating=1.0),
        ]
    )
    database.commit()
    admin_user = _user("admin", admin=True)
    track_profile_by_id(database, admin_user, alpha.id)

    result = asyncio.run(
        backend_main.get_consolidated_dashboard_analytics(
            scope="tracked",
            db=database,
            user=admin_user,
        )
    )

    assert result["system_stats"]["total_profiles"] == 1
    assert result["system_stats"]["total_movies_tracked"] == 1
    assert result["rating_distribution"] == {"4.0": 1}


def test_unknown_request_is_casefolded_idempotent_and_fulfills_only_after_sync(database):
    user = _legacy_user(database)
    first = track_or_request_profile(database, user, "New_User")
    second = track_or_request_profile(database, user, "new_user")

    assert first["status"] == second["status"] == "pending"
    assert database.query(ProfileAccessRequest).count() == 1

    profile = _profile(3, "new_user", completed=False)
    database.add(profile)
    database.commit()
    assert fulfill_pending_requests(database, profile) == 0
    assert database.query(UserTrackedProfile).count() == 0
    assert database.query(ProfileAccessRequest).one().status == "pending"

    profile.scraping_status = "completed"
    database.commit()
    assert fulfill_pending_requests(database, profile) == 1
    assert database.query(UserTrackedProfile).count() == 1
    request = database.query(ProfileAccessRequest).one()
    assert request.status == "fulfilled"
    assert request.fulfilled_profile_id == profile.id


def test_pending_placeholder_stays_a_request_without_access(database):
    profile = _profile(1, "awaiting", completed=False)
    database.add(profile)
    database.commit()
    user = _legacy_user(database)

    result = track_or_request_profile(database, user, "AWAITING")

    assert result["status"] == "pending"
    assert result["profile"]["scraping_status"] == "pending"
    assert database.query(UserTrackedProfile).count() == 0
    assert database.query(ProfileAccessRequest).one().status == "pending"


def test_per_user_request_and_tracking_limits_are_enforced(database, monkeypatch):
    monkeypatch.setenv("SPYBOXD_MAX_PENDING_PROFILE_REQUESTS_PER_USER", "1")
    user = _legacy_user(database)
    track_or_request_profile(database, user, "first_unknown")
    with pytest.raises(HTTPException) as pending_limit:
        track_or_request_profile(database, user, "second_unknown")
    assert pending_limit.value.status_code == 429

    monkeypatch.setenv("SPYBOXD_MAX_TRACKED_PROFILES_PER_USER", "1")
    database.add_all([_profile(10, "First"), _profile(11, "Second")])
    database.commit()
    another = _legacy_user(database, "another")
    track_or_request_profile(database, another, "First")
    with pytest.raises(HTTPException) as tracked_limit:
        track_or_request_profile(database, another, "Second")
    assert tracked_limit.value.status_code == 429


def test_untracking_removes_fulfilled_request_and_prevents_silent_regrant(database):
    profile = _profile(1, "Alpha")
    app_user = AppUser(
        clerk_user_id="user_one",
        primary_profile_required=False,
    )
    database.add_all([profile, app_user])
    database.flush()
    database.add_all(
        [
            UserTrackedProfile(user_id=app_user.id, profile_id=profile.id),
            ProfileAccessRequest(
                user_id=app_user.id,
                requested_username="Alpha",
                normalized_username="alpha",
                status="fulfilled",
                fulfilled_profile_id=profile.id,
            ),
        ]
    )
    database.commit()

    assert untrack_profile(database, _user(), "alpha") is True
    assert database.query(UserTrackedProfile).count() == 0
    assert database.query(ProfileAccessRequest).count() == 0


def test_untracking_preserves_access_to_legacy_profile_usernames(database):
    profile = _profile(1, "legacy-name")
    app_user = AppUser(
        clerk_user_id="user_one",
        primary_profile_required=False,
    )
    database.add_all([profile, app_user])
    database.flush()
    database.add(
        UserTrackedProfile(user_id=app_user.id, profile_id=profile.id)
    )
    database.commit()

    assert untrack_profile(database, _user(), "@LEGACY-NAME") is True
    assert database.query(UserTrackedProfile).count() == 0


def test_deleted_profile_requests_reopen_as_approved(database):
    profile = _profile(1, "Alpha")
    app_user = AppUser(clerk_user_id="user_one")
    database.add_all([profile, app_user])
    database.flush()
    request = ProfileAccessRequest(
        user_id=app_user.id,
        requested_username="Alpha",
        normalized_username="alpha",
        status="fulfilled",
        fulfilled_profile_id=profile.id,
    )
    database.add(request)
    database.commit()

    assert reopen_fulfilled_requests_for_profile(database, profile) == 1
    database.refresh(request)
    assert request.status == "approved"
    assert request.fulfilled_profile_id is None


def test_direct_and_request_tracking_survive_delete_and_reupload(database):
    profile = _profile(1, "Alpha")
    direct_user = AppUser(clerk_user_id="direct_user")
    request_user = AppUser(clerk_user_id="request_user")
    database.add_all([profile, direct_user, request_user])
    database.flush()
    database.add_all(
        [
            UserTrackedProfile(
                user_id=direct_user.id,
                profile_id=profile.id,
                source="direct",
            ),
            UserTrackedProfile(
                user_id=request_user.id,
                profile_id=profile.id,
                source="request_fulfillment",
            ),
            ProfileAccessRequest(
                user_id=request_user.id,
                requested_username="Alpha",
                normalized_username="alpha",
                status="fulfilled",
                fulfilled_profile_id=profile.id,
            ),
        ]
    )
    database.commit()

    assert reopen_fulfilled_requests_for_profile(database, profile, commit=False) == 2
    database.query(UserTrackedProfile).filter_by(profile_id=profile.id).delete()
    database.query(Profile).filter_by(id=profile.id).delete()
    database.commit()

    requests = database.query(ProfileAccessRequest).order_by(ProfileAccessRequest.user_id).all()
    assert len(requests) == 2
    assert {request.status for request in requests} == {"approved"}
    assert {request.fulfilled_profile_id for request in requests} == {None}

    replacement = _profile(2, "alpha")
    database.add(replacement)
    database.commit()
    assert fulfill_pending_requests(database, replacement) == 2
    assert {
        row.user_id
        for row in database.query(UserTrackedProfile).filter_by(profile_id=replacement.id)
    } == {direct_user.id, request_user.id}


def test_tracking_cap_applies_to_fulfillment_and_admin_approval(database, monkeypatch):
    monkeypatch.setenv("SPYBOXD_MAX_TRACKED_PROFILES_PER_USER", "1")
    first = _profile(1, "First")
    second = _profile(2, "Second")
    requester = AppUser(clerk_user_id="requester")
    admin = AppUser(clerk_user_id="admin")
    database.add_all([first, second, requester, admin])
    database.flush()
    database.add(
        UserTrackedProfile(user_id=requester.id, profile_id=first.id, source="direct")
    )
    pending = ProfileAccessRequest(
        user_id=requester.id,
        requested_username="Second",
        normalized_username="second",
        status="pending",
    )
    database.add(pending)
    database.commit()

    assert fulfill_pending_requests(database, second) == 0
    assert database.query(UserTrackedProfile).filter_by(user_id=requester.id).count() == 1
    assert pending.status == "pending"

    result = decide_profile_request(
        database,
        _user("admin", admin=True),
        pending.id,
        decision="approved",
        note="Queue after capacity is available",
    )
    assert result["status"] == "approved"
    assert database.query(UserTrackedProfile).filter_by(user_id=requester.id).count() == 1


def test_disabled_admin_is_rejected_before_admin_bypasses(database):
    profile = _profile(1, "Alpha")
    disabled = AppUser(clerk_user_id="disabled_admin", is_active=False)
    database.add_all([profile, disabled])
    database.commit()
    admin_user = _user("disabled_admin", admin=True)

    checks = (
        lambda: accessible_profiles(database, admin_user),
        lambda: authorize_profile_usernames(database, admin_user, ["Alpha"]),
        lambda: require_profile_access(database, admin_user, "Alpha"),
        lambda: list_profile_requests(database, admin_user, include_all=True),
        lambda: decide_profile_request(
            database,
            admin_user,
            999,
            decision="approved",
            note=None,
        ),
    )
    for check in checks:
        with pytest.raises(HTTPException) as raised:
            check()
        assert raised.value.status_code == 403


def test_disabled_admin_is_rejected_by_every_main_admin_mutation(database):
    database.add(AppUser(clerk_user_id="disabled_admin", is_active=False))
    database.commit()
    admin_user = _user("disabled_admin", admin=True)

    calls = (
        backend_main.create_profile(
            backend_main.ProfileCreate(username="new_profile"),
            db=database,
            _user=admin_user,
        ),
        backend_main.update_profile(
            "missing",
            backend_main.ProfileUpdate(bio="x"),
            db=database,
            _user=admin_user,
        ),
        backend_main.delete_profile("missing", db=database, _user=admin_user),
        backend_main.clear_profile_data("missing", db=database, _user=admin_user),
    )
    for call in calls:
        with pytest.raises(HTTPException) as raised:
            asyncio.run(call)
        assert raised.value.status_code == 403


def test_disabled_admin_is_rejected_through_every_admin_http_route(database):
    database.add(AppUser(clerk_user_id="disabled_admin", is_active=False))
    database.commit()
    admin_user = _user("disabled_admin", admin=True)
    backend_main.app.dependency_overrides[backend_main.get_db] = lambda: database
    backend_main.app.dependency_overrides[backend_main.get_admin_user] = lambda: admin_user
    backend_main.app.dependency_overrides[backend_main.get_upload_user] = lambda: admin_user
    client = TestClient(backend_main.app)
    try:
        responses = (
            client.post("/profiles/create", json={"username": "new_profile"}),
            client.put("/profiles/missing", json={"bio": "x"}),
            client.delete("/profiles/missing"),
            client.delete("/profiles/missing/data"),
            client.post(
                "/upload/",
                files={"files": ("profile.zip", b"not-a-zip", "application/zip")},
            ),
            client.get("/admin/profile-requests"),
            client.put(
                "/admin/profile-requests/999",
                json={"status": "approved"},
            ),
        )
    finally:
        backend_main.app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [403] * len(responses)


def test_different_pending_usernames_share_the_per_user_lock(database, monkeypatch):
    locked_user_ids = []
    monkeypatch.setattr(
        profile_access_service,
        "_lock_user_access_mutations",
        lambda _db, app_user_id: locked_user_ids.append(app_user_id),
    )

    user = _legacy_user(database)
    track_or_request_profile(database, user, "first_unknown")
    track_or_request_profile(database, user, "second_unknown")

    app_user = database.query(AppUser).filter_by(clerk_user_id="user_one").one()
    assert locked_user_ids == [app_user.id, app_user.id]


def test_non_admin_request_payload_omits_internal_identity_and_notes(database):
    requester = AppUser(
        clerk_user_id="requester",
        primary_profile_required=False,
    )
    admin = AppUser(clerk_user_id="admin")
    database.add_all([requester, admin])
    database.flush()
    request = ProfileAccessRequest(
        user_id=requester.id,
        requested_username="Alpha",
        normalized_username="alpha",
        status="rejected",
        admin_note="internal moderation note",
        resolved_by_clerk_user_id="admin",
    )
    database.add(request)
    database.commit()

    ordinary = list_profile_requests(database, _user("requester"))[0]
    assert "requester_user_id" not in ordinary
    # Naming the requester is as much an identity leak as the Clerk id is.
    assert "requester_letterboxd_username" not in ordinary
    assert "resolved_by_user_id" not in ordinary
    assert "note" not in ordinary

    privileged = list_profile_requests(
        database,
        _user("admin", admin=True),
        include_all=True,
    )[0]
    assert privileged["requester_user_id"] == "requester"
    assert privileged["resolved_by_user_id"] == "admin"
    assert privileged["note"] == "internal moderation note"
    # This requester never linked an account, so there is no name to show and
    # the queue is left with the opaque id.
    assert privileged["requester_letterboxd_username"] is None


def test_admin_queue_names_the_requester_when_an_account_is_linked(database):
    """The Clerk id identifies an account; it does not tell an admin who asked."""
    requester = AppUser(clerk_user_id="user_3HDeXHfN", letterboxd_username="prani_1234")
    database.add_all([requester, AppUser(clerk_user_id="admin")])
    database.flush()
    database.add(
        ProfileAccessRequest(
            user_id=requester.id,
            requested_username="Alpha",
            normalized_username="alpha",
            status="pending",
        )
    )
    database.commit()

    privileged = list_profile_requests(
        database,
        _user("admin", admin=True),
        include_all=True,
    )[0]

    assert privileged["requester_letterboxd_username"] == "prani_1234"
    # Kept alongside, not replaced: it is still the only stable identifier.
    assert privileged["requester_user_id"] == "user_3HDeXHfN"


def test_profile_username_is_unique_case_insensitively(database):
    database.add(_profile(1, "Alpha"))
    database.commit()
    database.add(_profile(2, "alpha"))
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_profile_id_scope_prevents_case_variant_tenant_confusion(database):
    database.execute(text('DROP INDEX "uq_profiles_username_lower"'))
    tracked = _profile(1, "Alpha")
    hidden = _profile(2, "alpha")
    app_user = AppUser(
        clerk_user_id="user_one",
        primary_profile_required=False,
    )
    database.add_all([tracked, hidden, app_user])
    database.flush()
    database.add(
        UserTrackedProfile(user_id=app_user.id, profile_id=tracked.id, source="direct")
    )
    database.commit()

    assert authorize_profile_usernames(database, _user(), ["alpha"]) == ["Alpha"]
    assert require_profile_access(database, _user(), "alpha").id == tracked.id
    resolved = InsightsService(
        database,
        allowed_profile_ids=[tracked.id],
    )._resolve_profiles(["alpha"], minimum=1)
    assert [profile.id for profile in resolved] == [tracked.id]


def test_watch_together_ignores_untracked_outsider_evidence(database, monkeypatch):
    selected_a = _profile(1, "SelectedA")
    selected_b = _profile(2, "SelectedB")
    hidden = _profile(3, "Hidden")
    hidden_movie = Movie(
        id=10,
        canonical_key="letterboxd:hidden-film",
        title="Hidden Film",
        normalized_title="hidden film",
        release_year=2026,
    )
    database.add_all([selected_a, selected_b, hidden, hidden_movie])
    database.flush()
    database.add(
        ProfileFilm(
            id=1,
            profile_id=hidden.id,
            movie_id=hidden_movie.id,
            rating=5.0,
            watch_count=1,
            rewatch_count=0,
        )
    )
    database.commit()

    def stub_coverage(service):
        monkeypatch.setattr(service, "_available_public_lists", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(service, "_state_rows", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(service, "_event_rows", lambda *_args, **_kwargs: [])
        monkeypatch.setattr(
            service,
            "_coverage_payload",
            lambda *_args, **_kwargs: {"profiles": []},
        )
        monkeypatch.setattr(
            service,
            "_feature_coverage",
            lambda *_args, **_kwargs: {
                "status": "ready",
                "score": 100,
                "blockers": [],
                "warnings": [],
            },
        )

    unrestricted = InsightsService(database)
    stub_coverage(unrestricted)
    unrestricted_result = unrestricted.watch_together(
        ["SelectedA", "SelectedB"],
        mode="unseen_pick",
        region="ALL",
        max_runtime=None,
        genre=None,
        availability=None,
        limit=30,
    )
    assert [item["movie"]["title"] for item in unrestricted_result["recommendations"]] == [
        "Hidden Film"
    ]

    scoped = InsightsService(
        database,
        allowed_profile_ids=[selected_a.id, selected_b.id],
    )
    stub_coverage(scoped)
    scoped_result = scoped.watch_together(
        ["SelectedA", "SelectedB"],
        mode="unseen_pick",
        region="ALL",
        max_runtime=None,
        genre=None,
        availability=None,
        limit=30,
    )
    assert scoped_result["recommendations"] == []


def test_insights_service_rejects_untracked_and_defaults_only_to_allowed(database):
    database.add_all([_profile(1, "Alpha"), _profile(2, "Beta")])
    database.commit()
    service = InsightsService(database, allowed_usernames=["Alpha"])

    assert [profile.username for profile in service._resolve_profiles([], minimum=1)] == ["Alpha"]
    with pytest.raises(InsightRequestError) as raised:
        service._resolve_profiles(["Beta"], minimum=1)
    assert raised.value.status_code == 403


def test_dashboard_snapshot_never_treats_empty_scope_as_global(database):
    alpha = _profile(1, "Alpha")
    beta = _profile(2, "Beta")
    database.add_all([alpha, beta])
    database.add_all(
        [
            Rating(
                id=1,
                profile_id=alpha.id,
                movie_title="Alpha Movie",
                movie_year=2024,
                rating=4.0,
                watched_date=datetime(2026, 7, 1, tzinfo=timezone.utc).date(),
            ),
            Rating(
                id=2,
                profile_id=beta.id,
                movie_title="Beta Movie",
                movie_year=2025,
                rating=1.0,
                watched_date=datetime(2026, 7, 2, tzinfo=timezone.utc).date(),
            ),
            Review(
                id=1,
                profile_id=alpha.id,
                movie_title="Alpha Movie",
                movie_year=2024,
            ),
            Review(
                id=2,
                profile_id=beta.id,
                movie_title="Beta Movie",
                movie_year=2025,
            ),
        ]
    )
    database.commit()

    repository = AnalyticsRepository(database)
    scoped = repository.build_dashboard_analytics_snapshot(usernames=["Alpha"])
    empty = repository.build_dashboard_analytics_snapshot(usernames=[])

    assert scoped["system_stats"]["total_profiles"] == 1
    assert scoped["system_stats"]["total_movies_tracked"] == 1
    assert scoped["system_stats"]["total_reviews"] == 1
    assert scoped["rating_distribution"] == {"4.0": 1}
    assert empty["system_stats"]["total_profiles"] == 0
    assert empty["system_stats"]["total_movies_tracked"] == 0
    assert empty["system_stats"]["total_reviews"] == 0
    assert empty["rating_distribution"] == {}
    assert empty["activity_data"] == []
    assert empty["group_signals"]["summary"]["profiles_analyzed"] == 0


def test_global_dashboard_snapshot_excludes_unready_and_inactive_profiles(database):
    ready = _profile(1, "Ready")
    pending = _profile(2, "Pending", completed=False)
    inactive = _profile(3, "Inactive")
    inactive.is_active = False
    movie = Movie(
        id=1,
        canonical_key="test:dashboard-film",
        title="Dashboard Film",
        normalized_title="dashboard film",
    )
    database.add_all([ready, pending, inactive, movie])
    database.add_all(
        [
            Rating(id=1, profile_id=ready.id, movie_title="Ready Film", rating=4.0),
            Rating(id=2, profile_id=pending.id, movie_title="Pending Film", rating=2.0),
            Rating(id=3, profile_id=inactive.id, movie_title="Inactive Film", rating=1.0),
            WatchEvent(
                id=1,
                profile_id=ready.id,
                movie_id=movie.id,
                event_key="ready-watch",
                watched_date=datetime(2026, 7, 15).date(),
                rating=4.0,
                source_kind="diary_csv",
            ),
            WatchEvent(
                id=2,
                profile_id=pending.id,
                movie_id=movie.id,
                event_key="pending-watch",
                watched_date=datetime(2026, 7, 15).date(),
                rating=2.0,
                source_kind="diary_csv",
            ),
            WatchEvent(
                id=3,
                profile_id=inactive.id,
                movie_id=movie.id,
                event_key="inactive-watch",
                watched_date=datetime(2026, 7, 15).date(),
                rating=1.0,
                source_kind="diary_csv",
            ),
        ]
    )
    database.commit()

    snapshot = AnalyticsRepository(database).build_dashboard_analytics_snapshot(
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert snapshot["system_stats"]["total_profiles"] == 1
    assert snapshot["system_stats"]["total_movies_tracked"] == 1
    assert snapshot["rating_distribution"] == {"4.0": 1}
    assert sum(point["movies_watched"] for point in snapshot["activity_data"]) == 1


def test_admin_allowlist_is_server_side_and_metadata_boolean_is_strict(monkeypatch):
    monkeypatch.setenv("CLERK_ADMIN_USER_IDS", "user_admin, user_other")
    assert _payload_grants_admin({}, "user_admin") is True
    assert _payload_grants_admin({"metadata": {"is_admin": True}}, "regular") is True
    assert _payload_grants_admin({"public_metadata": {"is_admin": "false"}}, "regular") is False


def _edge(edge_id: int, profile_id: int, handle: str, *, direction: str = "follower"):
    return ProfileFollowEdge(
        id=edge_id,
        profile_id=profile_id,
        direction=direction,
        counterpart_username=handle,
        counterpart_username_normalized=handle.casefold(),
    )


def test_a_non_admin_only_browses_their_own_corner_of_the_follow_graph(database):
    """Browsing every tracked profile told a new sign-up who Spyboxd watches.

    Letterboxd does not publish that list even though the profiles are public,
    so the catalog is narrowed to people the caller is actually connected to.
    """
    connected = _profile(1, "Connected")
    stranger = _profile(2, "Stranger")
    database.add_all([connected, stranger])
    database.add(_edge(1, connected.id, "viewer"))
    database.commit()
    user = _legacy_user(database)
    _link_handle(database, "user_one", "viewer")

    catalog = list_profile_catalog(database, user)

    assert [entry["username"] for entry in catalog["profiles"]] == ["Connected"]
    assert catalog["total"] == 1


def test_an_admin_still_sees_the_whole_library(database):
    database.add_all([_profile(1, "Alpha"), _profile(2, "Beta")])
    database.commit()
    admin = _legacy_user(database, "admin_user", admin=True)

    catalog = list_profile_catalog(database, admin)

    assert {entry["username"] for entry in catalog["profiles"]} == {"Alpha", "Beta"}


def test_a_caller_with_no_linked_letterboxd_identity_browses_nothing(database):
    """A fresh sign-up has no connections to compute, which is a real state.

    They are not stuck: typing a known username still resolves.
    """
    database.add(_profile(1, "Alpha"))
    database.commit()
    user = _legacy_user(database)

    catalog = list_profile_catalog(database, user)

    assert catalog["profiles"] == []
    assert catalog["total"] == 0


def test_connection_counts_from_either_side_of_the_edge(database):
    """Only one end of a pair may be synced, so both sides have to be read."""
    theirs = _profile(1, "TheyFollowMe")
    mine = _profile(2, "Viewer")
    reached = _profile(3, "IFollowThem")
    database.add_all([theirs, mine, reached])
    database.add(_edge(1, theirs.id, "viewer"))
    edge_out = _edge(2, mine.id, "ifollowthem", direction="following")
    edge_out.counterpart_profile_id = reached.id
    database.add(edge_out)
    database.commit()
    user = _legacy_user(database)
    _link_handle(database, "user_one", "viewer")

    usernames = {entry["username"] for entry in list_profile_catalog(database, user)["profiles"]}

    # Their edge naming me, my edge naming them, and my own profile.
    assert usernames == {"TheyFollowMe", "IFollowThem", "Viewer"}


def test_a_removed_follow_edge_is_not_a_connection(database):
    database.add(_profile(1, "Formerly"))
    stale = _edge(1, 1, "viewer")
    stale.removed_at = datetime.now(timezone.utc)
    database.add(stale)
    database.commit()
    user = _legacy_user(database)
    _link_handle(database, "user_one", "viewer")

    assert list_profile_catalog(database, user)["profiles"] == []


def test_a_known_username_outside_the_catalog_still_resolves_directly(database):
    """The restriction is on discovery, not on access.

    Someone who knows a username can still reach an already-synced profile
    without an admin in the loop, which is what makes the narrower catalog
    acceptable rather than obstructive.
    """
    database.add(_profile(1, "Unconnected"))
    database.commit()
    user = _legacy_user(database)
    _link_handle(database, "user_one", "viewer")

    assert list_profile_catalog(database, user)["profiles"] == []

    result = track_or_request_profile(database, user, "Unconnected")

    assert result["status"] == "tracked"
    assert authorize_profile_usernames(database, user, None) == ["Unconnected"]


def test_a_favourite_reports_whether_its_owner_ever_logged_it(database):
    """A stated favourite and a logged one are different claims.

    Across the tracked profiles four favourites are absent from their owner's
    diary entirely and five more are logged without ever being rated, so the
    payload must distinguish "never logged" from "logged but unrated".
    """
    from main import _profile_favorite_films
    from database.models import Movie, ProfileFavoriteMovie, ProfileFilm

    profile = _profile(1, "Alpha")
    database.add(profile)
    for index, (title, in_library, rating) in enumerate(
        [("Rated", True, 5.0), ("Unrated", True, None), ("Absent", False, None)], start=1
    ):
        movie = Movie(
            id=index,
            canonical_key=f"letterboxd:{index}",
            title=title,
            normalized_title=title.casefold(),
            release_year=2020,
            letterboxd_slug=f"film-{index}",
        )
        database.add(movie)
        database.add(
            ProfileFavoriteMovie(
                id=index, profile_id=profile.id, movie_id=movie.id, position=index
            )
        )
        if in_library:
            database.add(
                ProfileFilm(
                    id=index, profile_id=profile.id, movie_id=movie.id, rating=rating
                )
            )
    database.commit()

    favourites = {row["title"]: row for row in _profile_favorite_films(database, profile.id)}

    assert favourites["Rated"]["in_library"] is True
    assert favourites["Rated"]["own_rating"] == 5.0
    assert favourites["Unrated"]["in_library"] is True
    assert favourites["Unrated"]["own_rating"] is None
    assert favourites["Absent"]["in_library"] is False


# A like is a `boxd.it` token until its redirect is resolved. Unresolved, 46 of
# them render as the number 46; resolved, they say whose writing a member rates.

def test_liked_authors_rank_by_how_often_their_writing_was_liked():
    from api.routes.member_archive import _liked_authors

    class _Like:
        def __init__(self, username):
            self.target_username = username

    likes = [_Like("er3nweeber")] * 3 + [_Like("zoerosebryant")] * 2 + [_Like("peanat")]

    ranked = _liked_authors(likes)

    assert [row["username"] for row in ranked] == ["er3nweeber", "zoerosebryant", "peanat"]
    assert ranked[0]["likes"] == 3


def test_unresolved_likes_are_reported_rather_than_bucketed_as_an_author():
    """A dead or unresolvable link is not a member called None."""
    from api.routes.member_archive import _liked_authors

    class _Like:
        def __init__(self, username):
            self.target_username = username

    ranked = _liked_authors([_Like("er3nweeber"), _Like(None), _Like(None)])

    assert [row["username"] for row in ranked] == ["er3nweeber"]
    # Stated, so a short list reads as partial resolution rather than as a
    # short history.
    assert ranked[0]["unresolved_likes"] == 2


def test_no_resolved_likes_yield_no_authors_rather_than_an_empty_name():
    from api.routes.member_archive import _liked_authors

    class _Like:
        target_username = None

    assert _liked_authors([_Like(), _Like()]) == []


def test_like_target_resolution_is_admin_only(database):
    """Naming who a member likes is an identity surface, not a public one."""
    from fastapi import HTTPException
    from backend.api.routes.member_archive import resolve_like_targets

    with pytest.raises(HTTPException) as raised:
        resolve_like_targets(
            username="alpha",
            payload={"resolutions": {}},
            db=database,
            user=_user("ordinary"),
        )

    assert raised.value.status_code == 403


def test_like_target_resolution_rejects_a_payload_it_cannot_read(database):
    """Access is settled before the body is read, so the profile must exist."""
    from fastapi import HTTPException
    from backend.api.routes.member_archive import resolve_like_targets

    database.add(_profile(1, "Alpha"))
    database.commit()
    admin = _legacy_user(database, "admin", admin=True)

    with pytest.raises(HTTPException) as raised:
        resolve_like_targets(
            username="Alpha",
            payload={"resolutions": ["not", "a", "mapping"]},
            db=database,
            user=admin,
        )

    assert raised.value.status_code == 400

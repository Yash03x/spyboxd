from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
    ProfileFilm,
    Rating,
    Review,
    UserTrackedProfile,
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
    list_profile_requests,
    reopen_fulfilled_requests_for_profile,
    require_profile_access,
    track_or_request_profile,
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
            Movie.__table__,
            MovieEnrichment.__table__,
            MovieWatchProvider.__table__,
            ProfileFilm.__table__,
            WatchlistItem.__table__,
            Rating.__table__,
            Review.__table__,
        ],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(user_id: str = "user_one", *, admin: bool = False) -> ClerkUser:
    return ClerkUser(user_id=user_id, session_id="session", is_admin=admin)


def _profile(profile_id: int, username: str, *, completed: bool = True) -> Profile:
    return Profile(
        id=profile_id,
        username=username,
        is_active=True,
        scraping_status="completed" if completed else "pending",
    )


def test_existing_completed_profile_is_tracked_case_insensitively_and_idempotently(database):
    database.add_all([_profile(1, "Alpha"), _profile(2, "Beta")])
    database.commit()

    first = track_or_request_profile(database, _user(), "aLpHa")
    second = track_or_request_profile(database, _user(), "ALPHA")

    assert first["status"] == "tracked"
    assert first["profile"]["username"] == "Alpha"
    assert second["status"] == "tracked"
    assert database.query(UserTrackedProfile).count() == 1
    assert authorize_profile_usernames(database, _user(), None) == ["Alpha"]
    with pytest.raises(HTTPException) as raised:
        authorize_profile_usernames(database, _user(), ["Beta"])
    assert raised.value.status_code == 403


def test_unknown_request_is_casefolded_idempotent_and_fulfills_only_after_sync(database):
    first = track_or_request_profile(database, _user(), "New_User")
    second = track_or_request_profile(database, _user(), "new_user")

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

    result = track_or_request_profile(database, _user(), "AWAITING")

    assert result["status"] == "pending"
    assert result["profile"]["scraping_status"] == "pending"
    assert database.query(UserTrackedProfile).count() == 0
    assert database.query(ProfileAccessRequest).one().status == "pending"


def test_per_user_request_and_tracking_limits_are_enforced(database, monkeypatch):
    monkeypatch.setenv("SPYBOXD_MAX_PENDING_PROFILE_REQUESTS_PER_USER", "1")
    track_or_request_profile(database, _user(), "first_unknown")
    with pytest.raises(HTTPException) as pending_limit:
        track_or_request_profile(database, _user(), "second_unknown")
    assert pending_limit.value.status_code == 429

    monkeypatch.setenv("SPYBOXD_MAX_TRACKED_PROFILES_PER_USER", "1")
    database.add_all([_profile(10, "First"), _profile(11, "Second")])
    database.commit()
    track_or_request_profile(database, _user("another"), "First")
    with pytest.raises(HTTPException) as tracked_limit:
        track_or_request_profile(database, _user("another"), "Second")
    assert tracked_limit.value.status_code == 429


def test_untracking_removes_fulfilled_request_and_prevents_silent_regrant(database):
    profile = _profile(1, "Alpha")
    app_user = AppUser(clerk_user_id="user_one")
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

    track_or_request_profile(database, _user(), "first_unknown")
    track_or_request_profile(database, _user(), "second_unknown")

    app_user = database.query(AppUser).filter_by(clerk_user_id="user_one").one()
    assert locked_user_ids == [app_user.id, app_user.id]


def test_non_admin_request_payload_omits_internal_identity_and_notes(database):
    requester = AppUser(clerk_user_id="requester")
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
    app_user = AppUser(clerk_user_id="user_one")
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


def test_admin_allowlist_is_server_side_and_metadata_boolean_is_strict(monkeypatch):
    monkeypatch.setenv("CLERK_ADMIN_USER_IDS", "user_admin, user_other")
    assert _payload_grants_admin({}, "user_admin") is True
    assert _payload_grants_admin({"metadata": {"is_admin": True}}, "regular") is True
    assert _payload_grants_admin({"public_metadata": {"is_admin": "false"}}, "regular") is False

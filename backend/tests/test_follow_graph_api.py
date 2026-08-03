from __future__ import annotations

from datetime import datetime, timezone
from itertools import count

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import ClerkUser
from backend import main as backend_main
from backend.database.models import (
    AppUser,
    Base,
    Profile,
    ProfileAccessRequest,
    ProfileFollowEdge,
    ProfileSync,
    UserTrackedProfile,
)


@pytest.fixture()
def database():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Profile.__table__,
            AppUser.__table__,
            UserTrackedProfile.__table__,
            ProfileAccessRequest.__table__,
            ProfileSync.__table__,
            ProfileFollowEdge.__table__,
        ],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client_for(database):
    def _client(user: ClerkUser) -> TestClient:
        backend_main.app.dependency_overrides[backend_main.get_db] = lambda: database
        backend_main.app.dependency_overrides[backend_main.get_current_user] = (
            lambda: user
        )
        return TestClient(backend_main.app)

    try:
        yield _client
    finally:
        backend_main.app.dependency_overrides.clear()


def _user(user_id: str = "user_one", *, admin: bool = False) -> ClerkUser:
    return ClerkUser(
        user_id=user_id,
        session_id="session",
        is_admin=admin,
        letterboxd_username=None,
    )


def _legacy_user(
    database,
    user_id: str = "user_one",
    *,
    admin: bool = False,
    tracked_profile_ids: tuple[int, ...] = (),
) -> ClerkUser:
    app_user = AppUser(
        clerk_user_id=user_id,
        primary_profile_required=False,
    )
    database.add(app_user)
    database.flush()
    for profile_id in tracked_profile_ids:
        database.add(
            UserTrackedProfile(
                user_id=app_user.id,
                profile_id=profile_id,
                source="direct",
            )
        )
    database.commit()
    return _user(user_id, admin=admin)


def _profile(
    profile_id: int,
    username: str,
    *,
    completed: bool = True,
    active: bool = True,
    following_count: int | None = None,
    followers_count: int | None = None,
) -> Profile:
    return Profile(
        id=profile_id,
        username=username,
        is_active=active,
        scraping_status="completed" if completed else "pending",
        following_count=following_count,
        followers_count=followers_count,
    )


# SQLite only autogenerates INTEGER (not BIGINT) primary keys, so edge ids
# are assigned explicitly, matching the other sqlite fixtures in this suite.
_EDGE_IDS = count(1)


def _edge(
    profile_id: int,
    direction: str,
    counterpart: str,
    *,
    position: int | None = None,
    display_name: str | None = None,
    avatar_url: str | None = None,
    profile_url: str | None = None,
    counterpart_profile_id: int | None = None,
    removed_at: datetime | None = None,
) -> ProfileFollowEdge:
    return ProfileFollowEdge(
        id=next(_EDGE_IDS),
        profile_id=profile_id,
        direction=direction,
        counterpart_username=counterpart,
        counterpart_username_normalized=counterpart.casefold(),
        counterpart_display_name=display_name,
        counterpart_avatar_url=avatar_url,
        counterpart_profile_url=profile_url,
        counterpart_profile_id=counterpart_profile_id,
        position=position,
        removed_at=removed_at,
    )


def _seed_alpha_graph(database):
    database.add_all(
        [
            _profile(1, "alpha", following_count=3, followers_count=1),
            _profile(4, "zoe"),
            _profile(5, "penny", completed=False),
        ]
    )
    database.flush()
    database.add_all(
        [
            _edge(
                1,
                "following",
                "Zoe",
                position=1,
                display_name="Zoe Z",
                avatar_url="https://a.ltrbxd.com/zoe.jpg",
                profile_url="https://letterboxd.com/zoe/",
                counterpart_profile_id=4,
            ),
            _edge(1, "following", "carol", position=2),
            _edge(1, "following", "penny", position=3, counterpart_profile_id=5),
            _edge(1, "follower", "dave", position=1),
            _edge(
                1,
                "following",
                "eve",
                position=4,
                removed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            ),
        ]
    )
    database.commit()


def test_follow_graph_returns_edges_and_profile_counts(database, client_for):
    _seed_alpha_graph(database)
    user = _legacy_user(database, tracked_profile_ids=(1,))

    response = client_for(user).get("/api/profiles/alpha/follow-graph")

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == "alpha"
    assert payload["following_count"] == 3
    assert payload["followers_count"] == 1
    assert payload["total"] == 4
    # Deterministic order: direction asc, then source-page position.
    assert [
        (edge["direction"], edge["counterpart_username"]) for edge in payload["edges"]
    ] == [
        ("follower", "dave"),
        ("following", "Zoe"),
        ("following", "carol"),
        ("following", "penny"),
    ]
    by_counterpart = {edge["counterpart_username"]: edge for edge in payload["edges"]}
    zoe = by_counterpart["Zoe"]
    assert zoe["counterpart_display_name"] == "Zoe Z"
    assert zoe["counterpart_avatar_url"] == "https://a.ltrbxd.com/zoe.jpg"
    assert zoe["counterpart_profile_url"] == "https://letterboxd.com/zoe/"
    assert zoe["position"] == 1
    assert zoe["counterpart_profile_id"] == 4
    assert zoe["is_imported_profile"] is True
    assert zoe["removed_at"] is None
    assert by_counterpart["carol"]["is_imported_profile"] is False
    assert by_counterpart["carol"]["counterpart_profile_id"] is None
    # Linked but still pending: not selectable, so not "imported".
    assert by_counterpart["penny"]["is_imported_profile"] is False
    assert by_counterpart["penny"]["counterpart_profile_id"] == 5


def test_follow_graph_direction_filter_include_removed_and_pagination(
    database, client_for
):
    _seed_alpha_graph(database)
    user = _legacy_user(database, tracked_profile_ids=(1,))
    client = client_for(user)

    following = client.get(
        "/api/profiles/alpha/follow-graph", params={"direction": "following"}
    ).json()
    assert following["total"] == 3
    assert {edge["direction"] for edge in following["edges"]} == {"following"}

    followers = client.get(
        "/api/profiles/alpha/follow-graph", params={"direction": "followers"}
    ).json()
    assert followers["total"] == 1
    assert followers["edges"][0]["counterpart_username"] == "dave"

    removed_included = client.get(
        "/api/profiles/alpha/follow-graph", params={"include_removed": "true"}
    ).json()
    assert removed_included["total"] == 5
    eve = next(
        edge
        for edge in removed_included["edges"]
        if edge["counterpart_username"] == "eve"
    )
    assert eve["removed_at"] is not None
    assert eve["removed_at"].startswith("2026-07-01")

    page = client.get(
        "/api/profiles/alpha/follow-graph", params={"limit": 2, "offset": 1}
    ).json()
    assert page["total"] == 4
    assert [edge["counterpart_username"] for edge in page["edges"]] == ["Zoe", "carol"]

    assert (
        client.get(
            "/api/profiles/alpha/follow-graph", params={"direction": "sideways"}
        ).status_code
        == 422
    )


def test_follow_graph_unknown_profile_is_404(database, client_for):
    user = _legacy_user(database)

    response = client_for(user).get("/api/profiles/nosuch/follow-graph")

    assert response.status_code == 404
    assert response.json()["detail"] == "Profile not found"


def test_follow_graph_untracked_profile_is_403_for_non_admin(database, client_for):
    _seed_alpha_graph(database)
    user = _legacy_user(database, tracked_profile_ids=(1,))

    response = client_for(user).get("/api/profiles/zoe/follow-graph")

    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Track this profile before accessing its analytics."
    )


def test_follow_graph_admin_sees_any_profile(database, client_for):
    _seed_alpha_graph(database)
    admin = _legacy_user(database, "admin_user", admin=True)

    response = client_for(admin).get("/api/profiles/zoe/follow-graph")

    assert response.status_code == 200
    assert response.json() == {
        "username": "zoe",
        "following_count": None,
        "followers_count": None,
        "edges": [],
        "total": 0,
    }


def _seed_mutuals_group(database):
    database.add_all(
        [
            _profile(1, "alpha"),
            _profile(2, "beta"),
            _profile(3, "gamma"),
        ]
    )
    database.flush()
    database.add_all(
        [
            # alpha -> beta observed directly on alpha's following page.
            _edge(1, "following", "beta"),
            # beta -> alpha observed only as corroboration on alpha's
            # followers page; beta's own surfaces contributed nothing.
            _edge(1, "follower", "beta"),
            # alpha's old follow of gamma was soft-removed: no longer counts.
            _edge(
                1,
                "following",
                "gamma",
                removed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            ),
            # gamma -> alpha observed directly on gamma's following page.
            _edge(3, "following", "alpha"),
        ]
    )
    database.commit()


def test_mutuals_pair_logic_includes_follower_corroboration(database, client_for):
    _seed_mutuals_group(database)
    user = _legacy_user(database, tracked_profile_ids=(1, 2, 3))

    response = client_for(user).get(
        "/api/follow-graph/mutuals",
        params=[("profiles", "alpha"), ("profiles", "beta"), ("profiles", "gamma")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profiles"] == ["alpha", "beta", "gamma"]
    assert payload["pairs"] == [
        {
            "a": "alpha",
            "b": "beta",
            "a_follows_b": True,
            "b_follows_a": True,
            "mutual": True,
        },
        {
            "a": "alpha",
            "b": "gamma",
            "a_follows_b": False,
            "b_follows_a": True,
            "mutual": False,
        },
        {
            "a": "beta",
            "b": "gamma",
            "a_follows_b": False,
            "b_follows_a": False,
            "mutual": False,
        },
    ]
    assert payload["rollups"] == {
        "alpha": {"follows_in_group": 1, "followed_by_in_group": 2},
        "beta": {"follows_in_group": 1, "followed_by_in_group": 1},
        "gamma": {"follows_in_group": 1, "followed_by_in_group": 0},
    }


def test_mutuals_omitted_selection_uses_completed_tracked_set(database, client_for):
    _seed_mutuals_group(database)
    database.add(_profile(5, "penny", completed=False))
    database.commit()
    user = _legacy_user(database, tracked_profile_ids=(1, 2, 3, 5))

    payload = client_for(user).get("/api/follow-graph/mutuals").json()

    assert payload["profiles"] == ["alpha", "beta", "gamma"]
    assert len(payload["pairs"]) == 3
    mutual_by_pair = {
        (pair["a"], pair["b"]): pair["mutual"] for pair in payload["pairs"]
    }
    assert mutual_by_pair[("alpha", "beta")] is True


def test_mutuals_untracked_selection_is_403(database, client_for):
    _seed_mutuals_group(database)
    database.add(_profile(4, "zoe"))
    database.commit()
    user = _legacy_user(database, tracked_profile_ids=(1, 2))

    response = client_for(user).get(
        "/api/follow-graph/mutuals",
        params=[("profiles", "alpha"), ("profiles", "zoe")],
    )

    assert response.status_code == 403
    assert response.json()["detail"]["untracked_profiles"] == ["zoe"]


def _seed_suggestion_edges(database):
    database.add_all(
        [
            _profile(1, "alpha"),
            _profile(2, "beta"),
            _profile(3, "gamma"),
            _profile(4, "zoe"),
        ]
    )
    database.flush()
    database.add_all(
        [
            # yara: followed by all three tracked profiles, never imported.
            _edge(1, "following", "yara"),
            _edge(2, "following", "yara"),
            _edge(3, "following", "yara"),
            # zoe: overlap of two active follows; gamma's follow was removed.
            _edge(
                1,
                "following",
                "zoe",
                display_name="Zoe Z",
                avatar_url="https://a.ltrbxd.com/zoe.jpg",
                counterpart_profile_id=4,
            ),
            _edge(2, "following", "zoe", counterpart_profile_id=4),
            _edge(
                3,
                "following",
                "zoe",
                counterpart_profile_id=4,
                removed_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            ),
            # zoe follows alpha back (reciprocity tiebreaker input).
            _edge(1, "follower", "zoe", counterpart_profile_id=4),
            # apple: ties with zoe on overlap; username breaks the tie.
            _edge(1, "following", "apple"),
            _edge(2, "following", "apple"),
            # solo: below the default overlap threshold.
            _edge(1, "following", "solo"),
            # Tracked counterparts never come back as suggestions.
            _edge(1, "following", "beta"),
            _edge(2, "following", "alpha"),
        ]
    )
    database.commit()


def test_suggestions_threshold_exclusion_and_ordering(database, client_for):
    _seed_suggestion_edges(database)
    user = _legacy_user(database, tracked_profile_ids=(1, 2, 3))
    client = client_for(user)

    payload = client.get("/api/follow-graph/suggestions").json()

    assert [suggestion["username"] for suggestion in payload["suggestions"]] == [
        "yara",
        "apple",
        "zoe",
    ]
    yara, apple, zoe = payload["suggestions"]
    assert yara == {
        "username": "yara",
        "display_name": None,
        "avatar_url": None,
        "followed_by": ["alpha", "beta", "gamma"],
        "followed_by_count": 3,
        "follows_back_count": 0,
        "already_imported": False,
        "profile_id": None,
    }
    assert apple["followed_by"] == ["alpha", "beta"]
    assert apple["followed_by_count"] == 2
    assert zoe == {
        "username": "zoe",
        "display_name": "Zoe Z",
        "avatar_url": "https://a.ltrbxd.com/zoe.jpg",
        "followed_by": ["alpha", "beta"],
        "followed_by_count": 2,
        "follows_back_count": 1,
        "already_imported": True,
        "profile_id": 4,
    }

    lowered = client.get(
        "/api/follow-graph/suggestions", params={"min_overlap": 1}
    ).json()
    assert "solo" in {
        suggestion["username"] for suggestion in lowered["suggestions"]
    }

    limited = client.get("/api/follow-graph/suggestions", params={"limit": 1}).json()
    assert [suggestion["username"] for suggestion in limited["suggestions"]] == [
        "yara"
    ]


def test_suggestions_empty_for_user_with_no_tracked_profiles(database, client_for):
    _seed_suggestion_edges(database)
    outsider = _legacy_user(database, "outsider")

    payload = client_for(outsider).get("/api/follow-graph/suggestions").json()

    # The denominator travels with the counts: they are taken across every
    # monitored profile, and a caller that supplied its own rendered "10 of 6".
    assert payload == {"suggestions": [], "monitored_profiles": 0}

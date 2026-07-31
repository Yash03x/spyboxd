"""Phase-3 social graph ingestion: edges, lineage, unfollow events, backfill."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import (
    Movie,
    MovieList,
    MovieListItem,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
    ProfileFeedState,
    ProfileFilm,
    ProfileFollowEdge,
    ProfileSourceActivity,
    ProfileSync,
    Rating,
    Review,
    SyncDataset,
    WatchEvent,
    WatchlistItem,
)
from backend.services.ingestion import unified_data_loader
from backend.services.profile_loader import load_profile_data, validate_import_bundle


@compiles(BigInteger, "sqlite")
def _compile_big_integer_as_sqlite_integer(_type, _compiler, **_kwargs):
    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
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
    ProfileSourceActivity.__table__,
)


@pytest.fixture()
def database() -> Session:
    engine = create_engine("sqlite:///:memory:")
    for table in TABLES:
        table.create(engine, checkfirst=True)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _write_frame(path: Path, rows: list[dict], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


PEOPLE_COLUMNS = ["Position", "Username", "Display_Name", "Avatar_URL", "Profile_URL"]


def _person(position: int, username: str, display: str = "") -> dict:
    return {
        "Position": position,
        "Username": username,
        "Display_Name": display or username,
        "Avatar_URL": f"https://a.ltrbxd.com/{username}.jpg",
        "Profile_URL": f"https://letterboxd.com/{username}/",
    }


def _write_bundle(root: Path, *, following: list[dict], followers: list[dict], with_social: bool = True) -> None:
    root.mkdir()
    film = {
        "Title": "Challengers", "Year": 2024, "Rating": 4.0, "Film_ID": "842301",
        "Slug": "challengers", "Poster_URL": "",
        "Film_URL": "https://letterboxd.com/film/challengers/",
        "Has_Review": "No", "Is_Liked": "No", "Tags": "[]", "Movie_ID": "842301",
    }
    _write_frame(root / "profile.csv", [{
        "Username": "viewer", "Display_Name": "Viewer", "Join_Date": None,
        "Total_Films": 1, "Total_Reviews": 0, "Total_Lists": 0,
        "Following_Count": len(following), "Followers_Count": len(followers),
    }], [
        "Username", "Display_Name", "Join_Date", "Total_Films",
        "Total_Reviews", "Total_Lists", "Following_Count", "Followers_Count",
    ])
    _write_frame(root / "films_comprehensive.csv", [film], [
        "Title", "Year", "Rating", "Film_ID", "Slug", "Poster_URL",
        "Film_URL", "Has_Review", "Is_Liked", "Tags", "Movie_ID",
    ])
    _write_frame(root / "ratings.csv", [{"Name": "Challengers", "Year": 2024, "Rating": 4.0}], ["Name", "Year", "Rating"])
    _write_frame(root / "diary.csv", [], [
        "Name", "Year", "Watched Date", "Rating", "Is_Rewatch", "Is_Liked",
        "Has_Review", "Tags", "Film_ID", "Slug", "Diary_Entry_ID", "Film_URL",
    ])
    _write_frame(root / "likes.csv", [], ["Name", "Year", "Date", "Is_Liked", "Film_ID", "Slug", "Film_URL", "Poster_URL"])
    _write_frame(root / "reviews.csv", [], [
        "Name", "Year", "Rating", "Review", "Review_Date", "Review_Likes",
        "Contains_Spoilers", "Rewatch", "Tags", "Film_ID", "Slug", "Film_URL",
    ])
    _write_frame(root / "watchlist.csv", [], ["Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL"])
    _write_frame(root / "lists.csv", [], ["Title", "Description", "Film_Count", "URL", "Ranked", "Published_Date", "Tags"])
    _write_frame(root / "list_items.csv", [], [
        "List_Name", "List_URL", "Position", "Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL", "Notes",
    ])
    _write_frame(root / "favorites.csv", [], ["Position", "Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL"])

    datasets = [
        "profile", "favorites", "films", "diary", "likes",
        "reviews", "watchlist", "lists", "list_items",
    ]
    counts = {
        "films": 1, "diary": 0, "likes": 0, "reviews": 0, "watchlist": 0,
        "lists": 0, "list_items": 0, "favorites": 0,
    }
    schema_version = 2
    if with_social:
        schema_version = 3
        datasets += ["following", "followers"]
        counts["following"] = len(following)
        counts["followers"] = len(followers)
        _write_frame(root / "following.csv", following, PEOPLE_COLUMNS)
        _write_frame(root / "followers.csv", followers, PEOPLE_COLUMNS)

    (root / "manifest.json").write_text(
        json.dumps({
            "schema_version": schema_version,
            "source_kind": "full_html_upload",
            "username": "viewer",
            "requested_datasets": datasets,
            "completed_datasets": datasets,
            "counts": counts,
        }),
        encoding="utf-8",
    )


def _import(tmp_path: Path, name: str, db: Session, *, following: list[dict], followers: list[dict], with_social: bool = True) -> Profile:
    root = tmp_path / name
    _write_bundle(root, following=following, followers=followers, with_social=with_social)
    loaded = load_profile_data(str(root), "viewer")
    validate_import_bundle(loaded, require_full_manifest=True)
    profile = db.query(Profile).filter(Profile.username == "viewer").one_or_none()
    if profile is None:
        profile = Profile(username="viewer", scraping_status="pending")
        db.add(profile)
        db.commit()
    unified_data_loader(loaded, profile.id, db)
    db.commit()
    # The suite imports models as backend.database.models while ingestion uses
    # database.models — two mappers over the same tables — so held instances
    # must be expired or re-reads serve stale identity-map state.
    db.expire_all()
    return profile


def _active_edges(db: Session, direction: str) -> dict:
    return {
        edge.counterpart_username_normalized: edge
        for edge in db.query(ProfileFollowEdge)
        .filter(ProfileFollowEdge.direction == direction, ProfileFollowEdge.removed_at.is_(None))
        .all()
    }


def test_first_import_stores_edges_without_change_events(tmp_path: Path, database: Session) -> None:
    # A pre-existing canonical profile matching a counterpart gets attached.
    tracked = Profile(username="vaultedapathy", scraping_status="completed", is_active=True)
    database.add(tracked)
    database.commit()

    _import(
        tmp_path, "first", database,
        following=[_person(1, "vaultedapathy", "🫀"), _person(2, "maaxmc", "Maaxmc")],
        followers=[_person(1, "vaultedapathy", "🫀")],
    )

    following = _active_edges(database, "following")
    assert set(following) == {"vaultedapathy", "maaxmc"}
    assert following["vaultedapathy"].counterpart_profile_id == tracked.id
    assert following["maaxmc"].counterpart_profile_id is None
    assert following["maaxmc"].position == 2
    followers = _active_edges(database, "follower")
    assert set(followers) == {"vaultedapathy"}

    # Baseline import emits no change events.
    assert database.query(ProfileDataChange).count() == 0

    # sync_datasets rows exist for both surfaces.
    dataset_names = {row.dataset_name for row in database.query(SyncDataset).all()}
    assert {"following", "followers"} <= dataset_names


def test_unfollow_soft_removes_and_emits_events_and_refollow_resurrects(tmp_path: Path, database: Session) -> None:
    _import(
        tmp_path, "first", database,
        following=[_person(1, "vaultedapathy"), _person(2, "maaxmc")],
        followers=[_person(1, "bratpack")],
    )
    # Second sync: unfollowed maaxmc, lost bratpack, gained newfriend follower.
    _import(
        tmp_path, "second", database,
        following=[_person(1, "vaultedapathy")],
        followers=[_person(1, "newfriend")],
    )

    following = _active_edges(database, "following")
    assert set(following) == {"vaultedapathy"}
    removed = (
        database.query(ProfileFollowEdge)
        .filter(
            ProfileFollowEdge.direction == "following",
            ProfileFollowEdge.counterpart_username_normalized == "maaxmc",
        )
        .one()
    )
    assert removed.removed_at is not None

    changes = {
        (change.change_type, change.entity_key)
        for change in database.query(ProfileDataChange).all()
    }
    assert ("follow_removed", "user:maaxmc") in changes
    assert ("follower_lost", "user:bratpack") in changes
    assert ("follower_gained", "user:newfriend") in changes
    for change in database.query(ProfileDataChange).all():
        assert change.entity_type == "follow"

    # Third sync: re-followed maaxmc — same row resurrects, fresh event emits.
    _import(
        tmp_path, "third", database,
        following=[_person(1, "vaultedapathy"), _person(2, "maaxmc")],
        followers=[_person(1, "newfriend")],
    )
    resurrected = (
        database.query(ProfileFollowEdge)
        .filter(
            ProfileFollowEdge.direction == "following",
            ProfileFollowEdge.counterpart_username_normalized == "maaxmc",
        )
        .one()
    )
    assert resurrected.removed_at is None
    change_types = {
        (change.change_type, change.entity_key)
        for change in database.query(ProfileDataChange).all()
    }
    assert ("follow_added", "user:maaxmc") in change_types


def test_v2_bundle_preserves_prior_edges(tmp_path: Path, database: Session) -> None:
    _import(
        tmp_path, "social", database,
        following=[_person(1, "vaultedapathy")],
        followers=[_person(1, "bratpack")],
    )
    # A pre-upgrade scraper bundle without social surfaces must not remove edges.
    _import(tmp_path, "legacy", database, following=[], followers=[], with_social=False)

    assert set(_active_edges(database, "following")) == {"vaultedapathy"}
    assert set(_active_edges(database, "follower")) == {"bratpack"}
    # And no unfollow events were fabricated.
    assert database.query(ProfileDataChange).filter(
        ProfileDataChange.entity_type == "follow"
    ).count() == 0


def test_completed_profile_backfills_counterpart_references(tmp_path: Path, database: Session) -> None:
    _import(
        tmp_path, "first", database,
        following=[_person(1, "vaultedapathy")],
        followers=[],
    )
    edge = database.query(ProfileFollowEdge).one()
    assert edge.counterpart_profile_id is None

    # The counterpart later becomes a canonical profile via its own sync.
    counterpart = Profile(username="vaultedapathy", scraping_status="pending")
    database.add(counterpart)
    database.commit()
    root = tmp_path / "counterpart"
    _write_bundle(root, following=[], followers=[], with_social=True)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["username"] = "vaultedapathy"
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    profile_frame = pd.read_csv(root / "profile.csv")
    profile_frame["Username"] = "vaultedapathy"
    profile_frame.to_csv(root / "profile.csv", index=False)
    loaded = load_profile_data(str(root), "vaultedapathy")
    unified_data_loader(loaded, counterpart.id, database)
    database.commit()

    database.refresh(edge)
    assert edge.counterpart_profile_id == counterpart.id

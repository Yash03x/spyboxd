"""Export-only member surfaces: liked reviews/lists, comments, pronoun, preamble lists."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import (
    LostEntry,
    MemberComment,
    MemberContentLike,
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
from backend.services.profile_loader import load_profile_data


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
    LostEntry.__table__,
    MemberComment.__table__,
    MemberContentLike.__table__,
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


OFFICIAL_LIST_FILE = """Letterboxd list export v7
Date,Name,Tags,URL,Description
2026-07-17,"2024, Ranked","yearly, ranked",https://boxd.it/VKn8e,Ranked releases.

Position,Name,Year,URL,Description
1,The Wild Robot,2024,https://boxd.it/IWFy,Loved it
2,Dune: Part Two,2024,https://boxd.it/pUfA,
"""


DELETED_LIST_FILE = """Letterboxd list export v7
Date,Name,Tags,URL,Description
2024-02-02,Gone List,"2024, ranked",https://boxd.it/sFRUm,A list Letterboxd removed.

Position,Name,Year,URL,Description
1,Dune: Part Two,2024,https://boxd.it/pUfA,
2,Madame Web,2024,https://boxd.it/nope,
"""


def _write_export(root: Path, *, with_member_surfaces: bool = True) -> None:
    """A minimal official export mirroring the real 2026 file shapes."""
    root.mkdir()
    pd.DataFrame([{
        "Date Joined": "2023-08-21", "Username": "Viewer",
        "Location": "", "Website": "", "Bio": "", "Pronoun": "He / his",
    }]).to_csv(root / "profile.csv", index=False)
    pd.DataFrame([{
        "Date": "2023-10-15", "Name": "Lost in Translation", "Year": 2003,
        "Letterboxd URI": "https://boxd.it/4ZVRqB", "Rating": 2.5,
        "Rewatch": "", "Tags": "", "Watched Date": "2023-08-15",
    }]).to_csv(root / "diary.csv", index=False)
    pd.DataFrame([{
        "Date": "2023-08-15", "Name": "Lost in Translation", "Year": 2003,
        "Letterboxd URI": "https://boxd.it/4ZVRqB",
    }]).to_csv(root / "watched.csv", index=False)
    (root / "lists").mkdir()
    (root / "lists" / "2024-ranked.csv").write_text(OFFICIAL_LIST_FILE, encoding="utf-8")
    if with_member_surfaces:
        likes = root / "likes"
        likes.mkdir()
        pd.DataFrame([
            {"Date": "2023-10-30", "Content": "https://boxd.it/54qQSR"},
        ]).to_csv(likes / "reviews.csv", index=False)
        pd.DataFrame([
            {"Date": "2023-12-15", "Content": "https://boxd.it/qo626"},
            {"Date": "2024-01-02", "Content": "https://boxd.it/other1"},
        ]).to_csv(likes / "lists.csv", index=False)
        pd.DataFrame([
            {"Date": "2024-02-25", "Content": "https://boxd.it/5UiziT",
             "Comment": "One of the interpretations…"},
        ]).to_csv(root / "comments.csv", index=False)

        # deleted/ and orphaned/: header-only CSVs plus a removed list, which
        # is exactly the shape a real export ships.
        for lost_kind in ("deleted", "orphaned"):
            lost_dir = root / lost_kind
            lost_dir.mkdir()
            pd.DataFrame(columns=[
                "Date", "Name", "Year", "Letterboxd URI", "Rating", "Rewatch", "Tags", "Watched Date",
            ]).to_csv(lost_dir / "diary.csv", index=False)
            pd.DataFrame(columns=["Date", "Content", "Comment"]).to_csv(
                lost_dir / "comments.csv", index=False
            )
        orphaned_reviews = pd.DataFrame([{
            "Date": "2023-05-01", "Name": "Vanished Film", "Year": 2019,
            "Letterboxd URI": "https://boxd.it/ghost", "Rating": 3.0,
            "Rewatch": "", "Review": "It existed once.", "Tags": "",
            "Watched Date": "2023-04-28",
        }])
        orphaned_reviews.to_csv(root / "orphaned" / "reviews.csv", index=False)
        deleted_lists = root / "deleted" / "lists"
        deleted_lists.mkdir()
        (deleted_lists / "gone-list.csv").write_text(DELETED_LIST_FILE, encoding="utf-8")


def _import(tmp_path: Path, name: str, db: Session, **kwargs) -> Profile:
    root = tmp_path / name
    _write_export(root, **kwargs)
    loaded = load_profile_data(str(root), "viewer")
    profile = db.query(Profile).filter(Profile.username == "viewer").one_or_none()
    if profile is None:
        profile = Profile(username="viewer", scraping_status="pending")
        db.add(profile)
        db.commit()
    unified_data_loader(loaded, profile.id, db)
    db.commit()
    db.expire_all()
    return profile


def test_export_member_surfaces_flow_into_models(tmp_path: Path, database: Session) -> None:
    profile = _import(tmp_path, "export", database)

    likes = database.query(MemberContentLike).filter(
        MemberContentLike.removed_at.is_(None)
    ).all()
    assert {(like.content_type, like.target_url) for like in likes} == {
        ("review", "https://boxd.it/54qQSR"),
        ("list", "https://boxd.it/qo626"),
        ("list", "https://boxd.it/other1"),
    }
    assert all(like.liked_date is not None for like in likes)

    comment = database.query(MemberComment).one()
    assert comment.target_url == "https://boxd.it/5UiziT"
    assert comment.commented_date == date(2024, 2, 25)

    database.refresh(profile)
    assert profile.pronoun == "He / his"

    # The official v7 preamble supplies list metadata; Description on item rows is the note.
    movie_list = database.query(MovieList).one()
    assert movie_list.name == "2024, Ranked"
    assert movie_list.published_date == date(2026, 7, 17)
    assert sorted(movie_list.tags) == ["ranked", "yearly"]
    items = database.query(MovieListItem).order_by(MovieListItem.position).all()
    assert [item.notes for item in items] == ["Loved it", None]

    # Export diary rows carry both dates.
    event = database.query(WatchEvent).filter(WatchEvent.superseded_at.is_(None)).one()
    assert event.watched_date == date(2023, 8, 15)
    assert event.logged_date == date(2023, 10, 15)


def test_export_does_not_erase_scraper_observed_header_fields(tmp_path: Path, database: Session) -> None:
    # An export's profile.csv carries no display name or avatar; importing one
    # must not clear what the HTML scrape observed.
    profile = Profile(
        username="viewer",
        scraping_status="completed",
        display_name="Viewer Display",
        profile_image_url="https://a.ltrbxd.com/avatar.jpg",
    )
    database.add(profile)
    database.commit()

    _import(tmp_path, "export", database)

    database.refresh(profile)
    assert profile.display_name == "Viewer Display"
    assert profile.profile_image_url == "https://a.ltrbxd.com/avatar.jpg"
    # Fields the export DOES carry still apply.
    assert profile.pronoun == "He / his"


def test_lost_entries_capture_orphaned_rows_and_deleted_lists(tmp_path: Path, database: Session) -> None:
    _import(tmp_path, "export", database)

    entries = database.query(LostEntry).all()
    by_kind = {(entry.lost_kind, entry.entry_type) for entry in entries}
    assert ("orphaned", "review") in by_kind
    assert ("deleted", "list") in by_kind

    orphaned = next(entry for entry in entries if entry.entry_type == "review")
    assert orphaned.title == "Vanished Film"
    assert orphaned.body_text == "It existed once."
    assert orphaned.rating == 3.0

    # A removed list survives as one row per film, self-describing via body.
    deleted_films = sorted(
        entry.title for entry in entries if entry.entry_type == "list"
    )
    assert deleted_films == ["Dune: Part Two", "Madame Web"]
    assert all(
        entry.body_text == "From list: Gone List"
        for entry in entries
        if entry.entry_type == "list"
    )

    # Lost history must never leak into live surfaces.
    assert database.query(WatchEvent).filter(
        WatchEvent.superseded_at.is_(None)
    ).count() == 1
    assert database.query(MovieList).count() == 1


def test_export_resync_removes_unliked_and_preserves_without_files(tmp_path: Path, database: Session) -> None:
    _import(tmp_path, "first", database)

    # Second export: one list-like gone -> soft removed.
    root = tmp_path / "second"
    _write_export(root, with_member_surfaces=True)
    likes_frame = pd.DataFrame([{"Date": "2023-12-15", "Content": "https://boxd.it/qo626"}])
    likes_frame.to_csv(root / "likes" / "lists.csv", index=False)
    loaded = load_profile_data(str(root), "viewer")
    profile = database.query(Profile).filter(Profile.username == "viewer").one()
    unified_data_loader(loaded, profile.id, database)
    database.commit()
    database.expire_all()

    removed = database.query(MemberContentLike).filter(
        MemberContentLike.target_url == "https://boxd.it/other1"
    ).one()
    assert removed.removed_at is not None

    # A scraper bundle (no member-surface files) preserves everything.
    _import(tmp_path, "no_surfaces", database, with_member_surfaces=False)
    active = database.query(MemberContentLike).filter(
        MemberContentLike.removed_at.is_(None)
    ).count()
    assert active == 2
    assert database.query(MemberComment).filter(
        MemberComment.removed_at.is_(None)
    ).count() == 1

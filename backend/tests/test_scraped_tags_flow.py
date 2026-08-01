"""End-to-end: the upgraded scraper CSV contract (Tags columns, list flags)
flows through load_profile_data + unified_data_loader into the models, and
bundles from pre-upgrade scrapers keep preserving previously imported tags.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.database.models import (
    Movie,
    LostEntry,
    MemberComment,
    MemberContentLike,
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
    LostEntry.__table__,
    MemberComment.__table__,
    MemberContentLike.__table__,
    MovieList.__table__,
    MovieListItem.__table__,
    ProfileFavoriteMovie.__table__,
    ProfileDataChange.__table__,
    ProfileSourceActivity.__table__,
)

FILM_TAGS = '["comma, tag", "mood: eerie"]'
DIARY_TAGS = '["rewatch club"]'
REVIEW_TAGS = '["spoiler-review"]'
LIST_TAGS = '["favorites"]'


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


def _write_bundle(root: Path, *, with_tags: bool) -> None:
    """Write a full-html bundle in the current (with_tags) or legacy scraper contract."""
    root.mkdir()

    film = {
        "Title": "Challengers",
        "Year": 2024,
        "Rating": 4.0,
        "Film_ID": "842301",
        "Slug": "challengers",
        "Poster_URL": "",
        "Film_URL": "https://letterboxd.com/film/challengers/",
        "Has_Review": "Yes",
        "Is_Liked": "No",
        "Movie_ID": "842301",
    }
    film_columns = [
        "Title", "Year", "Rating", "Film_ID", "Slug", "Poster_URL",
        "Film_URL", "Has_Review", "Is_Liked", "Movie_ID",
    ]
    if with_tags:
        film["Tags"] = FILM_TAGS
        film_columns.insert(9, "Tags")

    diary_row = {
        "Name": "Challengers",
        "Year": 2024,
        "Date": "2026-07-05",
        "Watched Date": "2026-07-01",
        "Rating": 4.0,
        "Is_Rewatch": "No",
        "Is_Liked": "No",
        "Has_Review": "Yes",
        "Film_ID": "842301",
        "Slug": "challengers",
        "Diary_Entry_ID": "459597569",
        "Film_URL": "https://letterboxd.com/film/challengers/",
    }
    diary_columns = [
        "Name", "Year", "Date", "Watched Date", "Rating", "Is_Rewatch", "Is_Liked",
        "Has_Review", "Film_ID", "Slug", "Diary_Entry_ID", "Film_URL",
    ]
    if with_tags:
        diary_row["Tags"] = DIARY_TAGS
        diary_columns.insert(7, "Tags")

    review_row = {
        "Name": "Challengers",
        "Year": 2024,
        "Rating": 4.0,
        "Review": "Electric.",
        "Review_Date": "2026-07-01",
        "Review_Likes": 3,
        "Contains_Spoilers": "No",
        "Film_ID": "842301",
        "Slug": "challengers",
        "Film_URL": "https://letterboxd.com/film/challengers/",
    }
    review_columns = [
        "Name", "Year", "Rating", "Review", "Review_Date", "Review_Likes",
        "Contains_Spoilers", "Film_ID", "Slug", "Film_URL",
    ]
    if with_tags:
        review_row["Rewatch"] = "Yes"
        review_row["Tags"] = REVIEW_TAGS
        review_columns[7:7] = ["Rewatch", "Tags"]

    list_row = {
        "Title": "Best",
        "Description": "Ranked favorites",
        "Film_Count": 1,
        "URL": "/viewer/list/best/",
    }
    list_columns = ["Title", "Description", "Film_Count", "URL"]
    if with_tags:
        list_row.update({
            "Ranked": "Yes",
            "Published_Date": "2026-01-11T07:15:06.720Z",
            "Updated_Date": "2026-07-25T14:25:26.004Z",
            "Tags": LIST_TAGS,
        })
        list_columns += ["Ranked", "Published_Date", "Updated_Date", "Tags"]

    _write_frame(
        root / "profile.csv",
        [{
            "Username": "viewer",
            "Display_Name": "Viewer",
            "Join_Date": None,
            "Total_Films": 1,
            "Total_Reviews": 1,
            "Total_Lists": 1,
            "Following_Count": 1,
            "Followers_Count": 2,
            "Person_ID": 26275117 if with_tags else None,
            "Badge": "Patron" if with_tags else None,
            "Watchlist_Count": 88 if with_tags else None,
        }],
        [
            "Username", "Display_Name", "Join_Date", "Total_Films",
            "Total_Reviews", "Total_Lists", "Following_Count", "Followers_Count",
            "Person_ID", "Badge", "Watchlist_Count",
        ],
    )
    _write_frame(root / "films_comprehensive.csv", [film], film_columns)
    _write_frame(root / "ratings.csv", [{"Name": "Challengers", "Year": 2024, "Rating": 4.0}], ["Name", "Year", "Rating"])
    _write_frame(root / "diary.csv", [diary_row], diary_columns)
    _write_frame(
        root / "likes.csv",
        [],
        ["Name", "Year", "Date", "Is_Liked", "Film_ID", "Slug", "Film_URL", "Poster_URL"],
    )
    _write_frame(root / "reviews.csv", [review_row], review_columns)
    _write_frame(root / "watchlist.csv", [], ["Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL"])
    _write_frame(root / "lists.csv", [list_row], list_columns)
    _write_frame(
        root / "list_items.csv",
        [{
            "List_Name": "Best",
            "List_URL": "/viewer/list/best/",
            "Position": 1,
            "Name": "Challengers",
            "Year": 2024,
            "Film_ID": "842301",
            "Slug": "challengers",
            "Film_URL": "https://letterboxd.com/film/challengers/",
            "Poster_URL": "",
            "Notes": "",
        }],
        ["List_Name", "List_URL", "Position", "Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL", "Notes"],
    )
    _write_frame(root / "favorites.csv", [], ["Position", "Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL"])

    datasets = [
        "profile", "favorites", "films", "diary", "likes",
        "reviews", "watchlist", "lists", "list_items",
    ]
    (root / "manifest.json").write_text(
        json.dumps({
            "schema_version": 2,
            "source_kind": "full_html_upload",
            "username": "viewer",
            "requested_datasets": datasets,
            "completed_datasets": datasets,
            "counts": {
                "films": 1,
                "diary": 1,
                "likes": 0,
                "reviews": 1,
                "watchlist": 0,
                "lists": 1,
                "list_items": 1,
                "favorites": 0,
            },
        }),
        encoding="utf-8",
    )


def _import_bundle(tmp_path: Path, name: str, db: Session, *, with_tags: bool) -> Profile:
    root = tmp_path / name
    _write_bundle(root, with_tags=with_tags)
    loaded = load_profile_data(str(root), "viewer")
    validate_import_bundle(loaded, require_full_manifest=True)
    profile = db.query(Profile).filter(Profile.username == "viewer").one_or_none()
    if profile is None:
        profile = Profile(username="viewer", scraping_status="pending")
        db.add(profile)
        db.commit()
    unified_data_loader(loaded, profile.id, db)
    db.commit()
    return profile


def test_tagged_scraper_bundle_flows_into_all_tag_columns(tmp_path: Path, database: Session) -> None:
    _import_bundle(tmp_path, "bundle", database, with_tags=True)

    rating = database.query(Rating).one()
    # Legacy payloads union tags across every contributing frame
    # (films + diary + reviews).
    assert sorted(rating.tags or []) == [
        "comma, tag", "mood: eerie", "rewatch club", "spoiler-review",
    ]

    profile_film = database.query(ProfileFilm).one()
    # Film-level, diary, and review tags are unioned on the current-state row.
    assert set(profile_film.tags or []) == {
        "comma, tag", "mood: eerie", "rewatch club", "spoiler-review",
    }

    event = database.query(WatchEvent).one()
    assert event.tags == ["rewatch club"]
    assert event.watched_date == date(2026, 7, 1)

    review = database.query(Review).one()
    assert review.tags == ["spoiler-review"]
    assert review.likes_count == 3

    movie_list = database.query(MovieList).one()
    assert movie_list.is_ranked is True
    assert movie_list.published_date == date(2026, 1, 11)
    assert movie_list.updated_date == date(2026, 7, 25)
    assert movie_list.tags == ["favorites"]

    # Completeness columns: stable person id, badge, watchlist header count,
    # and the diary log date official exports carry alongside the watch date.
    profile = database.query(Profile).one()
    assert profile.letterboxd_person_id == 26275117
    assert profile.member_badge == "Patron"
    assert profile.reported_watchlist_count == 88
    assert event.logged_date == date(2026, 7, 5)


def test_legacy_bundle_without_tag_columns_preserves_previous_tags(tmp_path: Path, database: Session) -> None:
    _import_bundle(tmp_path, "tagged", database, with_tags=True)
    # A residential machine still running the pre-tags scraper uploads next.
    _import_bundle(tmp_path, "legacy", database, with_tags=False)

    assert sorted(database.query(Rating).one().tags or []) == [
        "comma, tag", "mood: eerie", "rewatch club", "spoiler-review",
    ]
    assert set(database.query(ProfileFilm).one().tags or []) == {
        "comma, tag", "mood: eerie", "rewatch club", "spoiler-review",
    }
    assert database.query(WatchEvent).filter(WatchEvent.superseded_at.is_(None)).one().tags == [
        "rewatch club"
    ]
    assert database.query(Review).one().tags == ["spoiler-review"]

    # Lists metadata from a pre-upgrade bundle (no Ranked/Published_Date/Tags
    # columns) must also preserve prior values, not reset them to defaults.
    movie_list = database.query(MovieList).one()
    assert movie_list.is_ranked is True
    assert movie_list.published_date == date(2026, 1, 11)
    assert movie_list.tags == ["favorites"]

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
    MovieList,
    MovieListItem,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
    ProfileFeedState,
    ProfileFilm,
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
    """Keep model-generated identifiers available in the in-memory test database."""

    return Integer().compile(dialect=_compiler.dialect)


TABLES = (
    Profile.__table__,
    ProfileSync.__table__,
    ProfileFeedState.__table__,
    SyncDataset.__table__,
    Movie.__table__,
    Rating.__table__,
    ProfileFilm.__table__,
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


def _movie(
    name: str,
    year: int,
    film_id: str,
    *,
    rating: float | None = None,
) -> dict:
    slug = name.casefold().replace(" ", "-")
    return {
        "Name": name,
        "Title": name,
        "Year": year,
        "Rating": rating,
        "Film_ID": film_id,
        "Slug": slug,
        "Film_URL": f"https://letterboxd.com/film/{slug}/",
        "Is_Liked": "No",
        "Has_Review": "No",
    }


def _write_frame(path: Path, rows: list[dict], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def _write_full_html_bundle(
    root: Path,
    *,
    films: list[dict],
    reviews: list[dict] | None = None,
    favorites: list[dict] | None = None,
    watchlist: list[dict] | None = None,
    join_date: str | None = None,
) -> None:
    root.mkdir()
    reviews = reviews or []
    favorites = favorites or []
    watchlist = watchlist or []

    _write_frame(
        root / "profile.csv",
        [
            {
                "Username": "viewer",
                "Display_Name": "Viewer",
                "Join_Date": join_date,
                "Total_Films": len(films),
                "Total_Reviews": len(reviews),
                "Total_Lists": 0,
                "Following_Count": 1,
                "Followers_Count": 2,
            }
        ],
        [
            "Username",
            "Display_Name",
            "Join_Date",
            "Total_Films",
            "Total_Reviews",
            "Total_Lists",
            "Following_Count",
            "Followers_Count",
        ],
    )
    _write_frame(
        root / "films_comprehensive.csv",
        films,
        [
            "Title",
            "Year",
            "Rating",
            "Film_ID",
            "Slug",
            "Poster_URL",
            "Film_URL",
            "Has_Review",
            "Is_Liked",
            "Movie_ID",
        ],
    )
    _write_frame(
        root / "ratings.csv",
        [
            {"Name": row["Name"], "Year": row["Year"], "Rating": row["Rating"]}
            for row in films
            if row.get("Rating") is not None
        ],
        ["Name", "Year", "Rating"],
    )
    _write_frame(
        root / "diary.csv",
        [],
        [
            "Name",
            "Year",
            "Watched Date",
            "Rating",
            "Is_Rewatch",
            "Is_Liked",
            "Has_Review",
            "Film_ID",
            "Slug",
            "Diary_Entry_ID",
            "Film_URL",
        ],
    )
    _write_frame(
        root / "likes.csv",
        [],
        ["Name", "Year", "Date", "Is_Liked", "Film_ID", "Slug", "Film_URL", "Poster_URL"],
    )
    _write_frame(
        root / "reviews.csv",
        reviews,
        ["Name", "Year", "Rating", "Review", "Review_Date", "Review_Likes", "Film_ID", "Slug", "Film_URL"],
    )
    _write_frame(
        root / "watchlist.csv",
        watchlist,
        ["Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL"],
    )
    _write_frame(root / "lists.csv", [], ["Title", "Description", "Film_Count", "URL"])
    _write_frame(
        root / "list_items.csv",
        [],
        ["List_Name", "List_URL", "Position", "Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL", "Notes"],
    )
    _write_frame(
        root / "favorites.csv",
        favorites,
        ["Position", "Name", "Year", "Film_ID", "Slug", "Film_URL", "Poster_URL"],
    )

    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_kind": "full_html_upload",
                "username": "viewer",
                "requested_datasets": [
                    "profile",
                    "favorites",
                    "films",
                    "diary",
                    "likes",
                    "reviews",
                    "watchlist",
                    "lists",
                    "list_items",
                ],
                "completed_datasets": [
                    "profile",
                    "favorites",
                    "films",
                    "diary",
                    "likes",
                    "reviews",
                    "watchlist",
                    "lists",
                    "list_items",
                ],
                "counts": {
                    "films": len(films),
                    "diary": 0,
                    "likes": 0,
                    "reviews": len(reviews),
                    "watchlist": len(watchlist),
                    "lists": 0,
                    "list_items": 0,
                    "favorites": len(favorites),
                },
            }
        ),
        encoding="utf-8",
    )


def _review(movie: dict, text: str, *, review_date: str, likes: int = 0) -> dict:
    return {
        "Name": movie["Name"],
        "Year": movie["Year"],
        "Rating": movie["Rating"],
        "Review": text,
        "Review_Date": review_date,
        "Review_Likes": likes,
        "Film_ID": movie["Film_ID"],
        "Slug": movie["Slug"],
        "Film_URL": movie["Film_URL"],
    }


def _favorite(movie: dict, position: int) -> dict:
    return {
        "Position": position,
        "Name": movie["Name"],
        "Year": movie["Year"],
        "Film_ID": movie["Film_ID"],
        "Slug": movie["Slug"],
        "Film_URL": movie["Film_URL"],
        "Poster_URL": "",
    }


def _watchlist_item(movie: dict) -> dict:
    return {
        "Name": movie["Name"],
        "Year": movie["Year"],
        "Film_ID": movie["Film_ID"],
        "Slug": movie["Slug"],
        "Film_URL": movie["Film_URL"],
        "Poster_URL": "",
    }


def _import_bundle(database: Session, profile: Profile, bundle_path: Path) -> None:
    loaded = load_profile_data(str(bundle_path), profile.username)
    unified_data_loader(loaded, profile.id, database)
    database.expire_all()


def _movie_id(database: Session, film_id: str) -> int:
    return database.query(Movie.id).filter(Movie.letterboxd_id == film_id).scalar()


def _create_profile(database: Session) -> Profile:
    profile = Profile(username="viewer", is_active=True, scraping_status="pending")
    database.add(profile)
    database.commit()
    return profile


def test_second_full_import_updates_rating_rows_in_place(database, tmp_path):
    profile = _create_profile(database)

    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    alien = _movie("Alien", 1979, "alien-id", rating=4.5)
    arrival = _movie("Arrival", 2016, "arrival-id", rating=3.5)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_full_html_bundle(first, films=[heat, alien])
    _import_bundle(database, profile, first)

    heat_movie_id = _movie_id(database, "heat-id")
    alien_movie_id = _movie_id(database, "alien-id")
    original_heat_rating_id = database.query(Rating.id).filter_by(profile_id=profile.id, movie_id=heat_movie_id).scalar()

    heat["Rating"] = 4.5
    _write_full_html_bundle(
        second,
        # Deliberately reverse source order so delete/reinsert cannot accidentally
        # look like an in-place update through recycled SQLite identifiers.
        films=[arrival, heat],
    )
    _import_bundle(database, profile, second)

    arrival_movie_id = _movie_id(database, "arrival-id")
    heat_rating = database.query(Rating).filter_by(profile_id=profile.id, movie_id=heat_movie_id).one()
    arrival_rating = database.query(Rating).filter_by(profile_id=profile.id, movie_id=arrival_movie_id).one()

    assert heat_rating.id == original_heat_rating_id
    assert heat_rating.rating == 4.5
    assert database.query(Rating).filter_by(profile_id=profile.id, movie_id=alien_movie_id).one_or_none() is None
    assert arrival_rating.id != original_heat_rating_id


def test_second_full_import_updates_review_rows_in_place(database, tmp_path):
    profile = _create_profile(database)

    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    alien = _movie("Alien", 1979, "alien-id", rating=4.5)
    arrival = _movie("Arrival", 2016, "arrival-id", rating=3.5)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_full_html_bundle(
        first,
        films=[heat, alien],
        reviews=[
            _review(heat, "Initial Heat review", review_date="2026-01-10", likes=2),
            _review(alien, "Alien review", review_date="2026-01-11"),
        ],
    )
    _import_bundle(database, profile, first)

    heat_movie_id = _movie_id(database, "heat-id")
    alien_movie_id = _movie_id(database, "alien-id")
    original_heat_review_id = database.query(Review.id).filter_by(profile_id=profile.id, movie_id=heat_movie_id).scalar()

    _write_full_html_bundle(
        second,
        films=[arrival, heat],
        reviews=[
            _review(arrival, "Arrival review", review_date="2026-01-12"),
            _review(heat, "Updated Heat review", review_date="2026-01-10", likes=3),
        ],
    )
    _import_bundle(database, profile, second)

    arrival_movie_id = _movie_id(database, "arrival-id")
    heat_review = database.query(Review).filter_by(profile_id=profile.id, movie_id=heat_movie_id).one()
    arrival_review = database.query(Review).filter_by(profile_id=profile.id, movie_id=arrival_movie_id).one()

    assert heat_review.id == original_heat_review_id
    assert heat_review.review_text == "Updated Heat review"
    assert heat_review.likes_count == 3
    assert database.query(Review).filter_by(profile_id=profile.id, movie_id=alien_movie_id).one_or_none() is None
    assert arrival_review.id != original_heat_review_id


def test_second_full_import_preserves_favorite_rows_while_reconciling(database, tmp_path):
    profile = _create_profile(database)

    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    alien = _movie("Alien", 1979, "alien-id", rating=4.5)
    arrival = _movie("Arrival", 2016, "arrival-id", rating=3.5)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_full_html_bundle(
        first,
        films=[heat, alien, arrival],
        favorites=[_favorite(heat, 1), _favorite(alien, 2)],
    )
    _import_bundle(database, profile, first)

    heat_movie_id = _movie_id(database, "heat-id")
    alien_movie_id = _movie_id(database, "alien-id")
    original_heat_id = database.query(ProfileFavoriteMovie.id).filter_by(profile_id=profile.id, movie_id=heat_movie_id).scalar()

    _write_full_html_bundle(
        second,
        films=[arrival, heat, alien],
        favorites=[_favorite(arrival, 1), _favorite(heat, 2)],
    )
    _import_bundle(database, profile, second)

    arrival_movie_id = _movie_id(database, "arrival-id")
    heat_favorite = database.query(ProfileFavoriteMovie).filter_by(profile_id=profile.id, movie_id=heat_movie_id).one()
    arrival_favorite = database.query(ProfileFavoriteMovie).filter_by(profile_id=profile.id, movie_id=arrival_movie_id).one()

    assert heat_favorite.id == original_heat_id
    assert heat_favorite.position == 2
    assert database.query(ProfileFavoriteMovie).filter_by(profile_id=profile.id, movie_id=alien_movie_id).one_or_none() is None
    assert arrival_favorite.position == 1
    assert arrival_favorite.id != original_heat_id


def test_second_full_import_preserves_watchlist_added_date_omitted_by_html(database, tmp_path):
    profile = _create_profile(database)

    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_full_html_bundle(
        first,
        films=[heat],
        watchlist=[_watchlist_item(heat)],
    )
    _import_bundle(database, profile, first)

    heat_movie_id = _movie_id(database, "heat-id")
    watchlist_item = database.query(WatchlistItem).filter_by(profile_id=profile.id, movie_id=heat_movie_id).one()
    watchlist_item.added_date = date(2025, 12, 31)
    watchlist_item.added_date_source_kind = "letterboxd_export:watchlist"
    database.commit()

    _write_full_html_bundle(
        second,
        films=[heat],
        watchlist=[_watchlist_item(heat)],
    )
    _import_bundle(database, profile, second)

    refreshed_watchlist_item = database.query(WatchlistItem).filter_by(
        profile_id=profile.id,
        movie_id=heat_movie_id,
    ).one()
    assert refreshed_watchlist_item.added_date == date(2025, 12, 31)
    assert refreshed_watchlist_item.added_date_source_kind == "letterboxd_export:watchlist"


def test_second_full_import_preserves_join_date_omitted_by_html(database, tmp_path):
    profile = _create_profile(database)

    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_full_html_bundle(first, films=[heat], join_date="2020-01-02")
    _import_bundle(database, profile, first)

    _write_full_html_bundle(second, films=[heat], join_date=None)
    _import_bundle(database, profile, second)

    refreshed_profile = database.get(Profile, profile.id)
    assert refreshed_profile.join_date == date(2020, 1, 2)


def test_only_authoritative_film_and_diary_snapshot_resets_rss_gap(database, tmp_path):
    profile = _create_profile(database)
    feed_state = ProfileFeedState(
        profile_id=profile.id,
        feed_url="https://letterboxd.com/viewer/rss/",
        activity_guids=["older-guid"],
        requires_full_sync=True,
        reconciliation_reason="rss_window_no_overlap",
    )
    database.add(feed_state)
    database.commit()

    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    partial = tmp_path / "partial"
    partial.mkdir()
    _write_frame(
        partial / "profile.csv",
        [{"Username": "viewer", "Display_Name": "Viewer"}],
        ["Username", "Display_Name"],
    )
    _write_frame(
        partial / "ratings.csv",
        [{"Name": "Heat", "Year": 1995, "Rating": 4.0}],
        ["Name", "Year", "Rating"],
    )
    _import_bundle(database, profile, partial)

    after_partial = database.get(ProfileFeedState, profile.id)
    assert after_partial.requires_full_sync is True
    assert after_partial.reconciliation_reason == "rss_window_no_overlap"
    assert after_partial.activity_guids == ["older-guid"]

    complete = tmp_path / "complete"
    _write_full_html_bundle(complete, films=[heat])
    _import_bundle(database, profile, complete)

    after_complete = database.get(ProfileFeedState, profile.id)
    assert after_complete.requires_full_sync is False
    assert after_complete.reconciliation_reason is None
    assert after_complete.activity_guids == []


def test_partial_rating_import_preserves_unobserved_profile_film_fields(database, tmp_path):
    profile = _create_profile(database)
    heat = _movie("Heat", 1995, "heat-id", rating=4.0)
    initial = tmp_path / "initial"
    _write_full_html_bundle(initial, films=[heat])
    _import_bundle(database, profile, initial)

    movie_id = _movie_id(database, "heat-id")
    rating = database.query(Rating).filter_by(profile_id=profile.id, movie_id=movie_id).one()
    rating.watched_date = date(2025, 1, 2)
    rating.is_rewatch = True
    rating.is_liked = True
    rating.tags = ["export-tag"]
    profile_film = database.query(ProfileFilm).filter_by(
        profile_id=profile.id,
        movie_id=movie_id,
    ).one()
    profile_film.is_liked = True
    profile_film.has_review = True
    profile_film.tags = ["export-tag"]
    database.commit()

    partial = tmp_path / "rating-only"
    partial.mkdir()
    _write_frame(
        partial / "ratings.csv",
        [{"Name": "Heat", "Year": 1995, "Rating": 4.5, "Film_ID": "heat-id"}],
        ["Name", "Year", "Rating", "Film_ID"],
    )
    _import_bundle(database, profile, partial)

    refreshed_rating = database.query(Rating).filter_by(
        profile_id=profile.id,
        movie_id=movie_id,
    ).one()
    refreshed_film = database.query(ProfileFilm).filter_by(
        profile_id=profile.id,
        movie_id=movie_id,
    ).one()
    assert refreshed_rating.rating == 4.5
    assert refreshed_rating.watched_date == date(2025, 1, 2)
    assert refreshed_rating.is_rewatch is True
    assert refreshed_rating.is_liked is True
    assert refreshed_rating.tags == ["export-tag"]
    assert refreshed_film.rating == 4.5
    assert refreshed_film.is_liked is True
    assert refreshed_film.has_review is True
    assert refreshed_film.tags == ["export-tag"]


def test_title_year_fallback_never_reassigns_linked_rating(database, tmp_path):
    profile = _create_profile(database)
    original_movie = Movie(
        canonical_key="letterboxd:original-crash",
        letterboxd_id="original-crash",
        title="Crash",
        normalized_title="crash",
        release_year=1996,
    )
    distinct_movie = Movie(
        canonical_key="letterboxd:distinct-crash",
        letterboxd_id="distinct-crash",
        title="Crash",
        normalized_title="crash",
        release_year=1996,
    )
    database.add_all([original_movie, distinct_movie])
    database.flush()
    original_rating = Rating(
        profile_id=profile.id,
        movie_id=original_movie.id,
        movie_title="Crash",
        movie_year=1996,
        rating=4.0,
        tags=[],
    )
    database.add(original_rating)
    database.flush()
    original_film = ProfileFilm(
        profile_id=profile.id,
        movie_id=original_movie.id,
        legacy_rating_id=original_rating.id,
        rating=4.0,
        tags=[],
    )
    database.add(original_film)
    database.commit()
    original_rating_id = original_rating.id

    partial = tmp_path / "same-title-rating"
    partial.mkdir()
    _write_frame(
        partial / "ratings.csv",
        [
            {
                "Name": "Crash",
                "Year": 1996,
                "Rating": 3.5,
                "Film_ID": "distinct-crash",
            }
        ],
        ["Name", "Year", "Rating", "Film_ID"],
    )
    _import_bundle(database, profile, partial)

    database.refresh(original_rating)
    database.refresh(original_film)
    assert original_rating.id == original_rating_id
    assert original_rating.movie_id == original_movie.id
    assert original_film.legacy_rating_id == original_rating_id
    distinct_rating = database.query(Rating).filter_by(
        profile_id=profile.id,
        movie_id=distinct_movie.id,
    ).one_or_none()
    assert distinct_rating is None
    distinct_film = database.query(ProfileFilm).filter_by(
        profile_id=profile.id,
        movie_id=distinct_movie.id,
    ).one()
    assert distinct_film.legacy_rating_id is None
    assert distinct_film.rating == 3.5


def test_full_films_snapshot_computes_average_without_ratings_csv(database, tmp_path):
    profile = _create_profile(database)
    bundle = tmp_path / "films-without-ratings-file"
    _write_full_html_bundle(
        bundle,
        films=[
            _movie("Heat", 1995, "heat-id", rating=4.0),
            _movie("Alien", 1979, "alien-id", rating=4.5),
        ],
    )
    (bundle / "ratings.csv").unlink()
    _import_bundle(database, profile, bundle)

    database.refresh(profile)
    assert profile.avg_rating == pytest.approx(4.25)

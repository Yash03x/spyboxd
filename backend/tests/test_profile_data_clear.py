from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import (
    Movie,
    MemberComment,
    MemberContentLike,
    MovieList,
    MovieListItem,
    Profile,
    ProfileDataChange,
    ProfileFavoriteMovie,
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
from backend.database.repository import ProfileRepository


REPO_ROOT = Path(__file__).resolve().parents[2]


class ProfileDataClearTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        for table in (
            Profile.__table__,
            ProfileSync.__table__,
            SyncDataset.__table__,
            Movie.__table__,
            Rating.__table__,
            Review.__table__,
            ProfileFilm.__table__,
            ProfileFollowEdge.__table__,
            WatchEvent.__table__,
            WatchlistItem.__table__,
            MemberComment.__table__,
            MemberContentLike.__table__,
            MovieList.__table__,
            MovieListItem.__table__,
            ProfileFavoriteMovie.__table__,
            ProfileDataChange.__table__,
            ProfileSourceActivity.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.db = sessionmaker(bind=self.engine)()
        self._seed_two_profiles()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_two_profiles(self):
        synced_at = datetime(2026, 7, 28, tzinfo=timezone.utc)
        profiles = [
            Profile(
                id=1,
                username="target",
                scraping_status="completed",
                last_scraped_at=synced_at,
                avg_rating=4.0,
                total_reviews=1,
                metadata_synced_at=synced_at,
                reported_total_films=1,
                reported_total_reviews=1,
                reported_total_lists=1,
                enhanced_metrics={"data_coverage": {"is_partial": False}},
            ),
            Profile(
                id=2,
                username="survivor",
                scraping_status="completed",
                last_scraped_at=synced_at,
                avg_rating=3.5,
                total_reviews=1,
                metadata_synced_at=synced_at,
                reported_total_films=1,
                reported_total_reviews=1,
                reported_total_lists=1,
                enhanced_metrics={"data_coverage": {"is_partial": False}},
            ),
        ]
        movies = [
            Movie(
                id=100,
                canonical_key="letterboxd:target-film",
                title="Target Film",
                normalized_title="target film",
                release_year=2026,
            ),
            Movie(
                id=200,
                canonical_key="letterboxd:survivor-film",
                title="Survivor Film",
                normalized_title="survivor film",
                release_year=2025,
            ),
        ]
        self.db.add_all([*profiles, *movies])
        self.db.commit()

        syncs = [
            ProfileSync(
                id=10,
                profile_id=1,
                source_kind="full_html_upload",
                source_fingerprint="target-sync",
                importer_version="2",
                status="completed",
            ),
            ProfileSync(
                id=20,
                profile_id=2,
                source_kind="full_html_upload",
                source_fingerprint="survivor-sync",
                importer_version="2",
                status="completed",
            ),
        ]
        datasets = [
            SyncDataset(
                id=10,
                profile_sync_id=10,
                dataset_name="diary",
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=True,
            ),
            SyncDataset(
                id=20,
                profile_sync_id=20,
                dataset_name="diary",
                source_row_count=1,
                imported_row_count=1,
                is_authoritative=True,
            ),
        ]
        ratings = [
            Rating(
                id=1,
                profile_id=1,
                movie_id=100,
                movie_title="Target Film",
                movie_year=2026,
                rating=4.0,
                watched_date=date(2026, 7, 1),
            ),
            Rating(
                id=2,
                profile_id=2,
                movie_id=200,
                movie_title="Survivor Film",
                movie_year=2025,
                rating=3.5,
                watched_date=date(2026, 7, 2),
            ),
        ]
        reviews = [
            Review(
                id=1,
                profile_id=1,
                movie_id=100,
                movie_title="Target Film",
                movie_year=2026,
                review_text="Target review",
            ),
            Review(
                id=2,
                profile_id=2,
                movie_id=200,
                movie_title="Survivor Film",
                movie_year=2025,
                review_text="Survivor review",
            ),
        ]
        profile_films = [
            ProfileFilm(
                id=10,
                profile_id=1,
                movie_id=100,
                legacy_rating_id=1,
                rating=4.0,
                watch_count=1,
                rewatch_count=0,
            ),
            ProfileFilm(
                id=20,
                profile_id=2,
                movie_id=200,
                legacy_rating_id=2,
                rating=3.5,
                watch_count=1,
                rewatch_count=0,
            ),
        ]
        events = [
            WatchEvent(
                id=10,
                profile_id=1,
                movie_id=100,
                profile_film_id=10,
                event_key="target-event",
                watched_date=date(2026, 7, 1),
                source_kind="full_html_upload",
            ),
            WatchEvent(
                id=20,
                profile_id=2,
                movie_id=200,
                profile_film_id=20,
                event_key="survivor-event",
                watched_date=date(2026, 7, 2),
                source_kind="full_html_upload",
            ),
        ]
        watchlist_items = [
            WatchlistItem(id=10, profile_id=1, movie_id=100, position=1),
            WatchlistItem(id=20, profile_id=2, movie_id=200, position=1),
        ]
        movie_lists = [
            MovieList(id=10, profile_id=1, name="Target list", movie_count=1),
            MovieList(id=20, profile_id=2, name="Survivor list", movie_count=1),
        ]
        movie_list_items = [
            MovieListItem(id=10, movie_list_id=10, movie_id=100, position=1),
            MovieListItem(id=20, movie_list_id=20, movie_id=200, position=1),
        ]
        favorites = [
            ProfileFavoriteMovie(id=10, profile_id=1, movie_id=100, position=1),
            ProfileFavoriteMovie(id=20, profile_id=2, movie_id=200, position=1),
        ]
        changes = [
            ProfileDataChange(
                id=10,
                profile_id=1,
                profile_sync_id=10,
                change_key="target-change",
                change_type="watchlist_added",
                entity_type="watchlist",
                entity_key="movie:100",
                source_kind="full_html_upload",
                movie_id=100,
            ),
            ProfileDataChange(
                id=20,
                profile_id=2,
                profile_sync_id=20,
                change_key="survivor-change",
                change_type="watchlist_added",
                entity_type="watchlist",
                entity_key="movie:200",
                source_kind="full_html_upload",
                movie_id=200,
            ),
        ]
        source_activities = [
            ProfileSourceActivity(
                id=10,
                profile_id=1,
                movie_id=100,
                activity_key="target-activity",
                activity_type="watched_marked",
                activity_date=date(2026, 7, 1),
                date_semantics="account_activity",
                source_kind="letterboxd_export",
                source_dataset="watched.csv",
                first_seen_profile_sync_id=10,
                last_seen_profile_sync_id=10,
            ),
            ProfileSourceActivity(
                id=20,
                profile_id=2,
                movie_id=200,
                activity_key="survivor-activity",
                activity_type="watched_marked",
                activity_date=date(2026, 7, 2),
                date_semantics="account_activity",
                source_kind="letterboxd_export",
                source_dataset="watched.csv",
                first_seen_profile_sync_id=20,
                last_seen_profile_sync_id=20,
            ),
        ]
        self.db.add_all(
            [
                *syncs,
                *datasets,
                *ratings,
                *reviews,
                *profile_films,
                *events,
                *watchlist_items,
                *movie_lists,
                *movie_list_items,
                *favorites,
                *changes,
                *source_activities,
            ]
        )
        self.db.commit()

        for profile_id, sync_id in ((1, 10), (2, 20)):
            self.db.get(Profile, profile_id).last_profile_sync_id = sync_id
        self.db.commit()

    def _profile_row_count(self, model, profile_id):
        return self.db.query(model).filter(model.profile_id == profile_id).count()

    def test_clear_removes_all_profile_owned_import_data_only(self):
        deleted = ProfileRepository(self.db).clear_profile_data(1)

        self.assertEqual(
            deleted,
            {
                "profile_data_changes": 1,
                "source_activities": 1,
                "watch_events": 1,
                "watchlist_items": 1,
                "favorite_movies": 1,
                "movie_list_items": 1,
                "movie_lists": 1,
                "profile_films": 1,
                "reviews": 1,
                "ratings": 1,
                "sync_datasets": 1,
                "profile_syncs": 1,
            },
        )
        for model in (
            Rating,
            Review,
            ProfileFilm,
            WatchEvent,
            WatchlistItem,
            MovieList,
            ProfileFavoriteMovie,
            ProfileDataChange,
            ProfileSourceActivity,
            ProfileSync,
        ):
            self.assertEqual(self._profile_row_count(model, 1), 0)
            self.assertEqual(self._profile_row_count(model, 2), 1)
        self.assertEqual(
            self.db.query(MovieListItem).filter(MovieListItem.movie_list_id == 10).count(),
            0,
        )
        self.assertEqual(
            self.db.query(MovieListItem).filter(MovieListItem.movie_list_id == 20).count(),
            1,
        )
        self.assertEqual(
            self.db.query(SyncDataset).filter(SyncDataset.profile_sync_id == 10).count(),
            0,
        )
        self.assertEqual(
            self.db.query(SyncDataset).filter(SyncDataset.profile_sync_id == 20).count(),
            1,
        )
        self.assertEqual(self.db.query(Movie).count(), 2)

        profile = self.db.get(Profile, 1)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.scraping_status, "pending")
        self.assertIsNone(profile.last_profile_sync_id)
        self.assertIsNone(profile.last_scraped_at)
        self.assertIsNone(profile.metadata_synced_at)
        self.assertIsNone(profile.reported_total_films)
        self.assertIsNone(profile.reported_total_reviews)
        self.assertIsNone(profile.reported_total_lists)
        self.assertIsNone(profile.enhanced_metrics)
        self.assertEqual(profile.avg_rating, 0.0)
        self.assertEqual(profile.total_reviews, 0)

    def test_clear_rolls_back_every_delete_when_commit_fails(self):
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                ProfileRepository(self.db).clear_profile_data(1)

        self.assertEqual(self._profile_row_count(Rating, 1), 1)
        self.assertEqual(self._profile_row_count(WatchEvent, 1), 1)
        self.assertEqual(self._profile_row_count(ProfileSync, 1), 1)
        profile = self.db.get(Profile, 1)
        self.assertEqual(profile.scraping_status, "completed")
        self.assertEqual(profile.last_profile_sync_id, 10)


class ComposeIngestionTokenTests(TestCase):
    def test_compose_passes_ingestion_token_to_api(self):
        compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn(
            "INGESTION_API_TOKEN: ${INGESTION_API_TOKEN:-}",
            compose,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()

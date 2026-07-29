"""Contract and optional PostgreSQL checks for the additive data foundation."""

from __future__ import annotations

import os
from pathlib import Path
import unittest

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from backend.database.models import Base


REPO_ROOT = Path(__file__).resolve().parents[2]


class AdditiveMigrationContractTests(unittest.TestCase):
    def test_revision_chain_has_one_expected_head(self) -> None:
        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)

        self.assertEqual(script.get_heads(), ["20260729_0006"])
        self.assertEqual(script.get_revision("20260729_0006").down_revision, "20260729_0005")
        self.assertEqual(script.get_revision("20260729_0005").down_revision, "20260729_0004")
        self.assertEqual(script.get_revision("20260729_0004").down_revision, "20260728_0003")
        self.assertEqual(script.get_revision("20260728_0003").down_revision, "20260728_0002")
        self.assertEqual(script.get_revision("20260728_0002").down_revision, "20260313_0001")

    def test_model_metadata_exposes_the_foundation_contract(self) -> None:
        expected_tables = {
            "profiles",
            "profile_syncs",
            "profile_feed_states",
            "sync_datasets",
            "movies",
            "profile_films",
            "watch_events",
            "watchlist_items",
            "movie_lists",
            "movie_list_items",
            "profile_favorite_movies",
            "profile_data_changes",
            "profile_source_activities",
            "movie_enrichments",
            "movie_watch_providers",
            "ratings",
            "reviews",
        }
        self.assertTrue(expected_tables.issubset(Base.metadata.tables))

        expected_columns = {
            "profiles": {"display_name", "followers_count", "following_count", "last_profile_sync_id"},
            "ratings": {"movie_id", "first_seen_profile_sync_id", "last_seen_profile_sync_id", "removed_at"},
            "reviews": {"movie_id", "source_review_key", "published_at", "removed_at", "tags"},
            "movies": {"canonical_key", "letterboxd_id", "tmdb_id", "imdb_id"},
            "profile_films": {"profile_id", "movie_id", "legacy_rating_id", "watch_count", "rewatch_count"},
            "watch_events": {"profile_id", "movie_id", "event_key", "watched_date", "superseded_at"},
            "profile_data_changes": {"profile_id", "profile_sync_id", "change_type", "before", "after"},
            "profile_feed_states": {
                "profile_id",
                "feed_url",
                "content_sha256",
                "activity_guids",
                "last_polled_at",
                "last_success_at",
                "last_changed_at",
                "next_poll_at",
                "lease_until",
                "consecutive_failures",
                "requires_full_sync",
                "reconciliation_reason",
            },
            "profile_source_activities": {"profile_id", "movie_id", "activity_type", "activity_date", "date_semantics"},
            "movie_lists": {"tags"},
            "watchlist_items": {"added_date_source_kind"},
        }
        for table_name, columns in expected_columns.items():
            self.assertTrue(columns.issubset(Base.metadata.tables[table_name].c.keys()))

        expected_unique_constraints = {
            "profile_syncs": {"unique_profile_sync_fingerprint"},
            "sync_datasets": {"unique_sync_dataset_name"},
            "movies": {"unique_movie_canonical_key"},
            "profile_films": {"unique_profile_film", "unique_profile_film_legacy_rating"},
            "watch_events": {"unique_profile_watch_event"},
            "watchlist_items": {"unique_profile_watchlist_movie"},
            "movie_list_items": {"unique_movie_list_item"},
            "profile_data_changes": {"unique_profile_sync_change_key"},
            "profile_source_activities": {"unique_profile_source_activity"},
        }
        for table_name, constraint_names in expected_unique_constraints.items():
            actual_names = {
                constraint.name
                for constraint in Base.metadata.tables[table_name].constraints
                if constraint.name
            }
            self.assertTrue(constraint_names.issubset(actual_names))


@unittest.skipUnless(
    os.getenv("SPYBOXD_TEST_DATABASE_URL"),
    "Set SPYBOXD_TEST_DATABASE_URL to run read-only PostgreSQL migration checks.",
)
class AdditiveMigrationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_engine(os.environ["SPYBOXD_TEST_DATABASE_URL"], future=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def test_backfill_is_complete_without_changing_legacy_cardinality(self) -> None:
        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            try:
                current_revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                self.assertEqual(current_revision, "20260729_0006")

                counts = connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM ratings) AS ratings,
                            (SELECT count(*) FROM profile_films) AS profile_films,
                            (SELECT count(*) FROM ratings WHERE watched_date IS NOT NULL) AS dated_ratings,
                            (
                                SELECT count(*) FROM watch_events
                                WHERE source_kind = 'legacy_rating_snapshot'
                            ) AS inferred_events,
                            (SELECT count(*) FROM ratings WHERE movie_id IS NULL) AS unlinked_ratings,
                            (SELECT count(*) FROM reviews WHERE movie_id IS NULL) AS unlinked_reviews
                        """
                    )
                ).mappings().one()

                self.assertEqual(counts["profile_films"], counts["ratings"])
                self.assertEqual(counts["inferred_events"], counts["dated_ratings"])
                self.assertEqual(counts["unlinked_ratings"], 0)
                self.assertEqual(counts["unlinked_reviews"], 0)
            finally:
                transaction.rollback()


if __name__ == "__main__":
    unittest.main()

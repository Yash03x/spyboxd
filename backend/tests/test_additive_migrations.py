"""Contract and isolated PostgreSQL checks for the additive data foundation."""

from __future__ import annotations

import os
import re
import unittest
import uuid
from pathlib import Path
from unittest import mock

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    MetaData,
    create_engine,
    select,
    text,
)
from sqlalchemy.engine import URL, make_url

from backend.database.models import Base


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_REVISION = "20260313_0001"
FOUNDATION_REVISION = "20260728_0002"
BACKFILL_REVISION = "20260728_0003"
HEAD_REVISION = "20260730_0009"
TEST_DATABASE_NAME_PATTERN = re.compile(r"(?:^|[_-])(?:ci|test|testing)(?:$|[_-])")
TEST_SCHEMA_NAME_PATTERN = re.compile(r"^spyboxd_migration_test_[0-9a-f]{24}$")


def _validated_test_database_url(raw_url: str) -> URL:
    """Fail closed before creating even an isolated migration-test schema."""

    try:
        database_url = make_url(raw_url)
    except Exception as exc:
        raise RuntimeError(
            "SPYBOXD_TEST_DATABASE_URL is not a valid database URL"
        ) from exc

    if database_url.get_backend_name() != "postgresql":
        raise RuntimeError("migration compatibility tests require PostgreSQL")
    if database_url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError(
            "migration compatibility tests only accept a loopback PostgreSQL host"
        )
    database_name = (database_url.database or "").casefold()
    if not TEST_DATABASE_NAME_PATTERN.search(database_name):
        raise RuntimeError(
            "migration compatibility tests require a database name containing "
            "a standalone 'test', 'testing', or 'ci' marker"
        )

    if database_url.drivername == "postgresql":
        database_url = database_url.set(drivername="postgresql+psycopg")
    return database_url


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return config


class AdditiveMigrationSafetyTests(unittest.TestCase):
    def test_accepts_only_explicit_loopback_postgres_test_database(self) -> None:
        database_url = _validated_test_database_url(
            "postgresql://user:password@127.0.0.1:5432/spyboxd_ci"
        )

        self.assertEqual(database_url.drivername, "postgresql+psycopg")
        self.assertEqual(database_url.database, "spyboxd_ci")

    def test_rejects_non_test_database_name(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "standalone 'test'.*marker"):
            _validated_test_database_url(
                "postgresql+psycopg://user:password@localhost:5432/spyboxd"
            )

    def test_rejects_remote_database_host(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "loopback PostgreSQL host"):
            _validated_test_database_url(
                "postgresql+psycopg://user:password@db.example.com/spyboxd_test"
            )

    def test_rejects_non_postgres_database(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "require PostgreSQL"):
            _validated_test_database_url("sqlite:///spyboxd_test.db")


class AdditiveMigrationContractTests(unittest.TestCase):
    def test_revision_chain_has_one_expected_head(self) -> None:
        config = Config(str(REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        script = ScriptDirectory.from_config(config)

        self.assertEqual(script.get_heads(), [HEAD_REVISION])
        self.assertEqual(
            script.get_revision(HEAD_REVISION).down_revision, "20260730_0008"
        )
        self.assertEqual(
            script.get_revision("20260730_0008").down_revision, "20260729_0007"
        )
        self.assertEqual(
            script.get_revision("20260729_0007").down_revision, "20260729_0006"
        )
        self.assertEqual(
            script.get_revision("20260729_0006").down_revision, "20260729_0005"
        )
        self.assertEqual(
            script.get_revision("20260729_0005").down_revision, "20260729_0004"
        )
        self.assertEqual(
            script.get_revision("20260729_0004").down_revision, "20260728_0003"
        )
        self.assertEqual(
            script.get_revision(BACKFILL_REVISION).down_revision, FOUNDATION_REVISION
        )
        self.assertEqual(
            script.get_revision(FOUNDATION_REVISION).down_revision, LEGACY_REVISION
        )

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
            "app_users",
            "user_tracked_profiles",
            "profile_access_requests",
        }
        self.assertTrue(expected_tables.issubset(Base.metadata.tables))

        expected_columns = {
            "profiles": {
                "display_name",
                "followers_count",
                "following_count",
                "last_profile_sync_id",
            },
            "ratings": {
                "movie_id",
                "first_seen_profile_sync_id",
                "last_seen_profile_sync_id",
                "removed_at",
            },
            "reviews": {
                "movie_id",
                "source_review_key",
                "published_at",
                "removed_at",
                "tags",
            },
            "movies": {
                "canonical_key",
                "letterboxd_id",
                "tmdb_id",
                "imdb_id",
                "tmdb_lookup_attempted_at",
                "tmdb_lookup_expires_at",
                "tmdb_lookup_key",
            },
            "profile_films": {
                "profile_id",
                "movie_id",
                "legacy_rating_id",
                "watch_count",
                "rewatch_count",
            },
            "watch_events": {
                "profile_id",
                "movie_id",
                "event_key",
                "watched_date",
                "superseded_at",
            },
            "profile_data_changes": {
                "profile_id",
                "profile_sync_id",
                "change_type",
                "before",
                "after",
            },
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
            "profile_source_activities": {
                "profile_id",
                "movie_id",
                "activity_type",
                "activity_date",
                "date_semantics",
            },
            "movie_lists": {"tags"},
            "watchlist_items": {"added_date_source_kind"},
            "app_users": {
                "clerk_user_id",
                "letterboxd_username",
                "primary_profile_required",
                "is_active",
            },
            "user_tracked_profiles": {"user_id", "profile_id", "source"},
            "profile_access_requests": {
                "user_id",
                "requested_username",
                "normalized_username",
                "status",
                "fulfilled_profile_id",
            },
        }
        for table_name, columns in expected_columns.items():
            self.assertTrue(columns.issubset(Base.metadata.tables[table_name].c.keys()))

        expected_unique_constraints = {
            "profile_syncs": {"unique_profile_sync_fingerprint"},
            "sync_datasets": {"unique_sync_dataset_name"},
            "movies": {"unique_movie_canonical_key"},
            "profile_films": {
                "unique_profile_film",
                "unique_profile_film_legacy_rating",
            },
            "watch_events": {"unique_profile_watch_event"},
            "watchlist_items": {"unique_profile_watchlist_movie"},
            "movie_list_items": {"unique_movie_list_item"},
            "profile_data_changes": {"unique_profile_sync_change_key"},
            "profile_source_activities": {"unique_profile_source_activity"},
            "user_tracked_profiles": {"uq_user_tracked_profile"},
            "profile_access_requests": {"uq_profile_access_request_user_username"},
        }
        for table_name, constraint_names in expected_unique_constraints.items():
            actual_names = {
                constraint.name
                for constraint in Base.metadata.tables[table_name].constraints
                if constraint.name
            }
            self.assertTrue(constraint_names.issubset(actual_names))

        profile_indexes = {
            index.name: index for index in Base.metadata.tables["profiles"].indexes
        }
        self.assertIn("uq_profiles_username_lower", profile_indexes)
        self.assertTrue(profile_indexes["uq_profiles_username_lower"].unique)

        app_user_indexes = {
            index.name: index for index in Base.metadata.tables["app_users"].indexes
        }
        self.assertIn(
            "uq_app_users_letterboxd_username_lower",
            app_user_indexes,
        )
        self.assertTrue(
            app_user_indexes["uq_app_users_letterboxd_username_lower"].unique
        )

        migration_source = (
            REPO_ROOT / "alembic/versions/20260730_0008_add_profile_access.py"
        ).read_text()
        self.assertIn("HAVING count(*) > 1", migration_source)
        self.assertIn("uq_profiles_username_lower", migration_source)

        identity_migration_source = (
            REPO_ROOT / "alembic/versions/20260730_0009_add_letterboxd_identity.py"
        ).read_text()
        self.assertIn(
            "uq_app_users_letterboxd_username_lower",
            identity_migration_source,
        )
        self.assertIn(
            "UPDATE app_users SET primary_profile_required = false",
            identity_migration_source,
        )
        self.assertIn('server_default=sa.text("true")', identity_migration_source)


@unittest.skipUnless(
    os.getenv("SPYBOXD_TEST_DATABASE_URL"),
    "Set SPYBOXD_TEST_DATABASE_URL to run isolated PostgreSQL migration checks.",
)
class AdditiveMigrationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.database_url = _validated_test_database_url(
            os.environ["SPYBOXD_TEST_DATABASE_URL"]
        )
        cls.schema_name = f"spyboxd_migration_test_{uuid.uuid4().hex[:24]}"
        if not TEST_SCHEMA_NAME_PATTERN.fullmatch(cls.schema_name):
            raise RuntimeError("generated migration-test schema name is unsafe")

        cls.schema_created = False
        cls.engine = None
        cls.admin_engine = create_engine(
            cls.database_url,
            future=True,
            pool_pre_ping=True,
        )
        cls.addClassCleanup(cls._cleanup_resources)

        with cls.admin_engine.begin() as connection:
            actual_database = connection.execute(
                text("SELECT current_database()")
            ).scalar_one()
            if actual_database != cls.database_url.database:
                raise RuntimeError(
                    "connected database does not match the guarded test URL"
                )
            existing_schema = connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_namespace
                        WHERE nspname = :schema_name
                    )
                    """
                ),
                {"schema_name": cls.schema_name},
            ).scalar_one()
            if existing_schema:
                raise RuntimeError("generated migration-test schema already exists")
            quoted_schema = connection.dialect.identifier_preparer.quote_identifier(
                cls.schema_name
            )
            connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            cls.schema_created = True

        cls.engine = create_engine(
            cls.database_url,
            connect_args={"options": f"-csearch_path={cls.schema_name}"},
            future=True,
            pool_pre_ping=True,
        )
        cls._upgrade(LEGACY_REVISION)
        cls._seed_legacy_data()
        cls._snapshot_legacy_application_reads()
        cls._upgrade("20260730_0008")
        cls._seed_pre_identity_app_user()
        cls._upgrade(HEAD_REVISION)

    @classmethod
    def _cleanup_resources(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        try:
            if cls.schema_created:
                with cls.admin_engine.begin() as connection:
                    quoted_schema = (
                        connection.dialect.identifier_preparer.quote_identifier(
                            cls.schema_name
                        )
                    )
                    connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
                cls.schema_created = False
        finally:
            cls.admin_engine.dispose()

    @classmethod
    def _upgrade(cls, revision: str) -> None:
        migration_environment = {
            "DATABASE_URL": cls.database_url.render_as_string(hide_password=False),
            "PGOPTIONS": f"-csearch_path={cls.schema_name}",
        }
        with mock.patch.dict(os.environ, migration_environment, clear=False):
            command.upgrade(_alembic_config(), revision)

    @classmethod
    def _seed_legacy_data(cls) -> None:
        with cls.engine.begin() as connection:
            current_schema = connection.execute(
                text("SELECT current_schema()")
            ).scalar_one()
            if current_schema != cls.schema_name:
                raise RuntimeError(
                    "legacy fixture connection escaped its isolated schema"
                )

            connection.execute(
                text(
                    """
                    INSERT INTO profiles (
                        id,
                        username,
                        created_at,
                        updated_at,
                        last_scraped_at,
                        scraping_status,
                        avg_rating,
                        total_reviews,
                        join_date,
                        is_active,
                        enhanced_metrics
                    )
                    VALUES
                        (
                            101,
                            'legacy_alpha',
                            '2023-01-02T10:00:00+00:00',
                            '2024-03-04T11:00:00+00:00',
                            '2024-03-04T11:00:00+00:00',
                            'completed',
                            4.25,
                            1,
                            '2023-01-02',
                            true,
                            '{"data_coverage":{"ratings":"legacy"}}'::json
                        ),
                        (
                            102,
                            'legacy_beta',
                            '2023-02-03T10:00:00+00:00',
                            '2024-03-05T12:00:00+00:00',
                            NULL,
                            'completed',
                            4.0,
                            1,
                            '2023-02-03',
                            true,
                            '{"data_coverage":{"ratings":"legacy"}}'::json
                        )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO ratings (
                        id,
                        profile_id,
                        movie_title,
                        movie_year,
                        letterboxd_id,
                        rating,
                        watched_date,
                        is_rewatch,
                        is_liked,
                        created_at,
                        tags,
                        film_slug,
                        poster_url
                    )
                    VALUES
                        (
                            1001,
                            101,
                            'Arrival',
                            2016,
                            '12345',
                            4.5,
                            '2024-01-02',
                            false,
                            true,
                            '2024-01-02T20:00:00+00:00',
                            '["science-fiction"]'::json,
                            'arrival-2016',
                            'https://a.ltrbxd.com/resized/film-poster/arrival.jpg'
                        ),
                        (
                            1002,
                            102,
                            'Arrival',
                            2016,
                            '12345',
                            4.0,
                            '2024-01-03',
                            false,
                            false,
                            '2024-01-03T20:00:00+00:00',
                            '[]'::json,
                            'arrival-2016',
                            NULL
                        ),
                        (
                            1003,
                            101,
                            'Moonlight',
                            2016,
                            NULL,
                            5.0,
                            '2024-02-01',
                            true,
                            true,
                            '2024-02-01T20:00:00+00:00',
                            '["favourite"]'::json,
                            'moonlight-2016',
                            NULL
                        ),
                        (
                            1004,
                            101,
                            'Undated Legacy Film',
                            1999,
                            NULL,
                            0.5,
                            NULL,
                            false,
                            false,
                            '2024-02-02T20:00:00+00:00',
                            'null'::json,
                            NULL,
                            NULL
                        )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO reviews (
                        id,
                        profile_id,
                        movie_title,
                        movie_year,
                        letterboxd_id,
                        review_text,
                        rating,
                        contains_spoilers,
                        likes_count,
                        comments_count,
                        published_date,
                        created_at
                    )
                    VALUES
                        (
                            2001,
                            101,
                            'Arrival',
                            2016,
                            '12345',
                            'A precise legacy review.',
                            4.5,
                            false,
                            3,
                            1,
                            '2024-01-02',
                            '2024-01-02T21:00:00+00:00'
                        ),
                        (
                            2002,
                            102,
                            'Review Only Classic',
                            1988,
                            NULL,
                            'A review without a legacy rating.',
                            4.0,
                            true,
                            2,
                            0,
                            '2024-01-04',
                            '2024-01-04T21:00:00+00:00'
                        )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO movie_lists (
                        id,
                        profile_id,
                        name,
                        description,
                        is_public,
                        is_ranked,
                        movie_count,
                        created_at,
                        updated_at,
                        movies
                    )
                    VALUES (
                        3001,
                        101,
                        'Legacy favourites',
                        'A list retained through normalization.',
                        true,
                        false,
                        1,
                        '2024-01-05T10:00:00+00:00',
                        '2024-01-05T10:00:00+00:00',
                        CAST(:movies AS json)
                    )
                    """
                ),
                {"movies": '[{"Name":"Arrival","Year":2016}]'},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO system_metrics (
                        id,
                        timestamp,
                        total_profiles,
                        total_movies_tracked,
                        total_reviews,
                        avg_scraping_time,
                        active_scraping_jobs,
                        metrics
                    )
                    VALUES (
                        5001,
                        '2024-03-05T12:30:00+00:00',
                        2,
                        4,
                        2,
                        12.5,
                        1,
                        CAST(:metrics AS json)
                    )
                    """
                ),
                {"metrics": '{"source":"legacy-fixture"}'},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO scraping_jobs (
                        id,
                        profile_id,
                        status,
                        progress_message,
                        progress_percentage,
                        queued_at,
                        started_at,
                        completed_at,
                        error_message,
                        retry_count,
                        job_type,
                        job_params
                    )
                    VALUES (
                        6001,
                        101,
                        'completed',
                        'Legacy scrape complete',
                        100.0,
                        '2024-03-05T12:00:00+00:00',
                        '2024-03-05T12:01:00+00:00',
                        '2024-03-05T12:12:30+00:00',
                        NULL,
                        0,
                        'profile_sync',
                        CAST(:job_params AS json)
                    )
                    """
                ),
                {"job_params": '{"source":"legacy"}'},
            )

    @classmethod
    def _snapshot_legacy_application_reads(cls) -> None:
        """Retain the exact v1 table projections an old ORM would select."""

        legacy_table_names = (
            "profiles",
            "system_metrics",
            "movie_lists",
            "ratings",
            "reviews",
            "scraping_jobs",
        )
        cls.legacy_metadata = MetaData()
        with cls.engine.connect() as connection:
            cls.legacy_metadata.reflect(bind=connection, only=legacy_table_names)
            cls.legacy_snapshots = {
                table_name: [
                    dict(row)
                    for row in connection.execute(
                        select(cls.legacy_metadata.tables[table_name]).order_by(
                            cls.legacy_metadata.tables[table_name].c.id
                        )
                    ).mappings()
                ]
                for table_name in legacy_table_names
            }

    @classmethod
    def _seed_pre_identity_app_user(cls) -> None:
        """Create an account in the exact schema shape exposed by revision 0008."""

        with cls.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO app_users (id, clerk_user_id, is_active)
                    VALUES (4001, 'user_legacy_before_identity', true)
                    """
                )
            )

    def test_backfill_is_complete_without_changing_legacy_cardinality(self) -> None:
        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            try:
                current_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                self.assertEqual(current_revision, HEAD_REVISION)

                counts = (
                    connection.execute(
                        text(
                            """
                        SELECT
                            (SELECT count(*) FROM ratings) AS ratings,
                            (SELECT count(*) FROM reviews) AS reviews,
                            (SELECT count(*) FROM movies) AS movies,
                            (SELECT count(*) FROM profile_films) AS profile_films,
                            (SELECT count(*) FROM ratings WHERE watched_date IS NOT NULL) AS dated_ratings,
                            (
                                SELECT count(*) FROM watch_events
                                WHERE source_kind = 'legacy_rating_snapshot'
                            ) AS inferred_events,
                            (SELECT count(*) FROM ratings WHERE movie_id IS NULL) AS unlinked_ratings,
                            (SELECT count(*) FROM reviews WHERE movie_id IS NULL) AS unlinked_reviews,
                            (
                                SELECT count(*) FROM profiles
                                WHERE last_profile_sync_id IS NULL
                            ) AS profiles_without_sync,
                            (
                                SELECT count(*) FROM profile_films
                                WHERE first_seen_profile_sync_id IS NULL
                                   OR last_seen_profile_sync_id IS NULL
                            ) AS profile_films_without_lineage
                        """
                        )
                    )
                    .mappings()
                    .one()
                )

                self.assertEqual(counts["ratings"], 4)
                self.assertEqual(counts["reviews"], 2)
                self.assertEqual(counts["movies"], 4)
                self.assertEqual(counts["profile_films"], counts["ratings"])
                self.assertEqual(counts["dated_ratings"], 3)
                self.assertEqual(counts["inferred_events"], counts["dated_ratings"])
                self.assertEqual(counts["unlinked_ratings"], 0)
                self.assertEqual(counts["unlinked_reviews"], 0)
                self.assertEqual(counts["profiles_without_sync"], 0)
                self.assertEqual(counts["profile_films_without_lineage"], 0)

                datasets = (
                    connection.execute(
                        text(
                            """
                        SELECT
                            p.username,
                            sd.dataset_name,
                            sd.source_row_count,
                            sd.imported_row_count,
                            sd.is_authoritative
                        FROM sync_datasets sd
                        JOIN profile_syncs ps ON ps.id = sd.profile_sync_id
                        JOIN profiles p ON p.id = ps.profile_id
                        WHERE ps.source_kind = 'legacy_database'
                        ORDER BY p.username, sd.dataset_name
                        """
                        )
                    )
                    .mappings()
                    .all()
                )
                self.assertEqual(
                    [
                        (
                            row["username"],
                            row["dataset_name"],
                            row["source_row_count"],
                            row["imported_row_count"],
                            row["is_authoritative"],
                        )
                        for row in datasets
                    ],
                    [
                        ("legacy_alpha", "ratings", 3, 3, False),
                        ("legacy_alpha", "reviews", 1, 1, False),
                        ("legacy_alpha", "watch_events", 2, 2, False),
                        ("legacy_beta", "ratings", 1, 1, False),
                        ("legacy_beta", "reviews", 1, 1, False),
                        ("legacy_beta", "watch_events", 1, 1, False),
                    ],
                )

                normalized_rows = (
                    connection.execute(
                        text(
                            """
                        SELECT
                            p.username,
                            m.canonical_key,
                            pf.rating,
                            pf.watch_count,
                            pf.rewatch_count,
                            pf.has_review,
                            pf.tags
                        FROM profile_films pf
                        JOIN profiles p ON p.id = pf.profile_id
                        JOIN movies m ON m.id = pf.movie_id
                        ORDER BY p.username, m.canonical_key
                        """
                        )
                    )
                    .mappings()
                    .all()
                )
                arrival = next(
                    row
                    for row in normalized_rows
                    if row["username"] == "legacy_alpha"
                    and row["canonical_key"] == "letterboxd:12345"
                )
                self.assertEqual(arrival["rating"], 4.5)
                self.assertEqual(arrival["watch_count"], 1)
                self.assertEqual(arrival["rewatch_count"], 0)
                self.assertTrue(arrival["has_review"])
                self.assertEqual(arrival["tags"], ["science-fiction"])

                moonlight = next(
                    row
                    for row in normalized_rows
                    if row["canonical_key"] == "letterboxd-slug:moonlight-2016"
                )
                self.assertEqual(moonlight["watch_count"], 2)
                self.assertEqual(moonlight["rewatch_count"], 1)
                self.assertEqual(moonlight["tags"], ["favourite"])

                undated = next(
                    row
                    for row in normalized_rows
                    if row["canonical_key"] == "title-year:undated legacy film:1999"
                )
                self.assertEqual(undated["rating"], 0.5)
                self.assertEqual(undated["tags"], [])

                list_lineage = (
                    connection.execute(
                        text(
                            """
                        SELECT
                            source_list_key,
                            first_seen_profile_sync_id,
                            last_seen_profile_sync_id
                        FROM movie_lists
                        WHERE id = 3001
                        """
                        )
                    )
                    .mappings()
                    .one()
                )
                self.assertEqual(list_lineage["source_list_key"], "legacy-list:3001")
                self.assertIsNotNone(list_lineage["first_seen_profile_sync_id"])
                self.assertEqual(
                    list_lineage["first_seen_profile_sync_id"],
                    list_lineage["last_seen_profile_sync_id"],
                )

                grandfathered_user = (
                    connection.execute(
                        text(
                            """
                        SELECT letterboxd_username, primary_profile_required
                        FROM app_users
                        WHERE id = 4001
                        """
                        )
                    )
                    .mappings()
                    .one()
                )
                self.assertIsNone(grandfathered_user["letterboxd_username"])
                self.assertFalse(grandfathered_user["primary_profile_required"])
            finally:
                transaction.rollback()

    def test_legacy_application_projection_still_reads_head_schema(self) -> None:
        """Run every exact v1 table projection against the additive head schema."""

        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("SET TRANSACTION READ ONLY"))
            try:
                for table_name, before_rows in self.legacy_snapshots.items():
                    legacy_table = self.legacy_metadata.tables[table_name]
                    after_rows = [
                        dict(row)
                        for row in connection.execute(
                            select(legacy_table).order_by(legacy_table.c.id)
                        ).mappings()
                    ]
                    self.assertEqual(
                        after_rows,
                        before_rows,
                        f"legacy {table_name} projection changed after upgrade",
                    )
            finally:
                transaction.rollback()


if __name__ == "__main__":
    unittest.main()

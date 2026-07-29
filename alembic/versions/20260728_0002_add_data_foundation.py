"""Add canonical movie, event, sync-lineage, list, and enrichment schema.

Revision ID: 20260728_0002
Revises: 20260313_0001
Create Date: 2026-07-28 21:30:00

This revision is intentionally additive. Existing profile, rating, review, and
movie-list rows remain valid while the application dual-writes the new model.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260728_0002"
down_revision: Union[str, None] = "20260313_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSONB_EMPTY_OBJECT = sa.text("'{}'::jsonb")
JSONB_EMPTY_ARRAY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "profile_syncs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=200), nullable=False),
        sa.Column("importer_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_OBJECT, nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_OBJECT, nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_OBJECT, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'skipped')",
            name="ck_profile_syncs_status",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "source_fingerprint",
            "importer_version",
            name="unique_profile_sync_fingerprint",
        ),
    )
    op.create_index("ix_profile_syncs_profile_started", "profile_syncs", ["profile_id", "started_at"])

    op.create_table(
        "sync_datasets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_sync_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_name", sa.String(length=50), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_row_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_authoritative", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_OBJECT, nullable=False),
        sa.CheckConstraint("source_row_count >= 0", name="ck_sync_datasets_source_rows_nonnegative"),
        sa.CheckConstraint("imported_row_count >= 0", name="ck_sync_datasets_imported_rows_nonnegative"),
        sa.ForeignKeyConstraint(["profile_sync_id"], ["profile_syncs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_sync_id", "dataset_name", name="unique_sync_dataset_name"),
    )

    op.create_table(
        "movies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_key", sa.String(length=500), nullable=False),
        sa.Column("letterboxd_id", sa.String(length=100), nullable=True),
        sa.Column("letterboxd_slug", sa.String(length=250), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("normalized_title", sa.String(length=300), nullable=False),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("letterboxd_url", sa.String(length=500), nullable=True),
        sa.Column("poster_url", sa.String(length=500), nullable=True),
        sa.Column("tmdb_id", sa.BigInteger(), nullable=True),
        sa.Column("imdb_id", sa.String(length=32), nullable=True),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"],
            ["profile_syncs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"],
            ["profile_syncs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_key", name="unique_movie_canonical_key"),
    )
    op.create_index("ix_movies_letterboxd_slug", "movies", ["letterboxd_slug"])
    op.create_index("ix_movies_normalized_title_year", "movies", ["normalized_title", "release_year"])
    op.create_index(
        "uq_movies_letterboxd_id",
        "movies",
        ["letterboxd_id"],
        unique=True,
        postgresql_where=sa.text("letterboxd_id IS NOT NULL"),
    )
    op.create_index(
        "uq_movies_tmdb_id",
        "movies",
        ["tmdb_id"],
        unique=True,
        postgresql_where=sa.text("tmdb_id IS NOT NULL"),
    )
    op.create_index(
        "uq_movies_imdb_id",
        "movies",
        ["imdb_id"],
        unique=True,
        postgresql_where=sa.text("imdb_id IS NOT NULL"),
    )

    op.add_column("profiles", sa.Column("display_name", sa.String(length=200), nullable=True))
    op.add_column("profiles", sa.Column("following_count", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("followers_count", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("reported_total_films", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("reported_total_reviews", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("reported_total_lists", sa.Integer(), nullable=True))
    op.add_column("profiles", sa.Column("metadata_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("profiles", sa.Column("last_profile_sync_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "profiles_last_profile_sync_id_fkey",
        "profiles",
        "profile_syncs",
        ["last_profile_sync_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_profiles_following_nonnegative",
        "profiles",
        "following_count IS NULL OR following_count >= 0",
    )
    op.create_check_constraint(
        "ck_profiles_followers_nonnegative",
        "profiles",
        "followers_count IS NULL OR followers_count >= 0",
    )
    op.create_check_constraint(
        "ck_profiles_reported_films_nonnegative",
        "profiles",
        "reported_total_films IS NULL OR reported_total_films >= 0",
    )
    op.create_check_constraint(
        "ck_profiles_reported_reviews_nonnegative",
        "profiles",
        "reported_total_reviews IS NULL OR reported_total_reviews >= 0",
    )
    op.create_check_constraint(
        "ck_profiles_reported_lists_nonnegative",
        "profiles",
        "reported_total_lists IS NULL OR reported_total_lists >= 0",
    )

    for table_name in ("ratings", "reviews"):
        op.add_column(table_name, sa.Column("movie_id", sa.BigInteger(), nullable=True))
        op.add_column(table_name, sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True))
        op.add_column(table_name, sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True))
        op.add_column(table_name, sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
        op.create_foreign_key(
            f"{table_name}_movie_id_fkey",
            table_name,
            "movies",
            ["movie_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"{table_name}_first_seen_profile_sync_id_fkey",
            table_name,
            "profile_syncs",
            ["first_seen_profile_sync_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"{table_name}_last_seen_profile_sync_id_fkey",
            table_name,
            "profile_syncs",
            ["last_seen_profile_sync_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column("reviews", sa.Column("source_review_key", sa.String(length=600), nullable=True))
    op.add_column("reviews", sa.Column("source_url", sa.String(length=500), nullable=True))
    op.add_column("reviews", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_ratings_movie_profile", "ratings", ["movie_id", "profile_id"])
    op.create_index("ix_reviews_profile_movie", "reviews", ["profile_id", "movie_id"])
    op.create_index(
        "uq_reviews_profile_source_key",
        "reviews",
        ["profile_id", "source_review_key"],
        unique=True,
        postgresql_where=sa.text("source_review_key IS NOT NULL"),
    )

    op.create_table(
        "profile_films",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("legacy_rating_id", sa.Integer(), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("is_liked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_ARRAY, nullable=False),
        sa.Column("first_watched_date", sa.Date(), nullable=True),
        sa.Column("latest_watched_date", sa.Date(), nullable=True),
        sa.Column("watch_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rewatch_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("has_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("rating IS NULL OR (rating >= 0.5 AND rating <= 5.0)", name="ck_profile_films_rating"),
        sa.CheckConstraint("watch_count >= 0", name="ck_profile_films_watch_count_nonnegative"),
        sa.CheckConstraint("rewatch_count >= 0", name="ck_profile_films_rewatch_count_nonnegative"),
        sa.CheckConstraint("rewatch_count <= watch_count", name="ck_profile_films_rewatch_le_watch"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["legacy_rating_id"], ["ratings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "movie_id", name="unique_profile_film"),
        sa.UniqueConstraint("legacy_rating_id", name="unique_profile_film_legacy_rating"),
    )
    op.create_index("ix_profile_films_movie_profile", "profile_films", ["movie_id", "profile_id"])
    op.create_index("ix_profile_films_profile_removed", "profile_films", ["profile_id", "removed_at"])

    op.create_table(
        "watch_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_film_id", sa.BigInteger(), nullable=True),
        sa.Column("event_key", sa.String(length=600), nullable=False),
        sa.Column("watched_date", sa.Date(), nullable=False),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("is_rewatch", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_liked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_ARRAY, nullable=False),
        sa.Column("source_kind", sa.String(length=50), nullable=False),
        sa.Column("source_entry_id", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("rating IS NULL OR (rating >= 0.5 AND rating <= 5.0)", name="ck_watch_events_rating"),
        sa.CheckConstraint(
            "source_row_number IS NULL OR source_row_number > 0",
            name="ck_watch_events_source_row_positive",
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_film_id"], ["profile_films.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "event_key", name="unique_profile_watch_event"),
    )
    op.create_index("ix_watch_events_profile_date", "watch_events", ["profile_id", "watched_date"])
    op.create_index(
        "ix_watch_events_movie_date_active",
        "watch_events",
        ["movie_id", "watched_date", "profile_id"],
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("added_date", sa.Date(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("position IS NULL OR position > 0", name="ck_watchlist_items_position_positive"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "movie_id", name="unique_profile_watchlist_movie"),
    )
    op.create_index("ix_watchlist_items_profile_removed", "watchlist_items", ["profile_id", "removed_at"])
    op.create_index(
        "ix_watchlist_items_movie_active",
        "watchlist_items",
        ["movie_id", "profile_id"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.add_column("movie_lists", sa.Column("source_list_key", sa.String(length=600), nullable=True))
    op.add_column("movie_lists", sa.Column("letterboxd_url", sa.String(length=500), nullable=True))
    op.add_column("movie_lists", sa.Column("published_date", sa.Date(), nullable=True))
    op.add_column("movie_lists", sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True))
    op.add_column("movie_lists", sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True))
    op.add_column("movie_lists", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "movie_lists_first_seen_profile_sync_id_fkey",
        "movie_lists",
        "profile_syncs",
        ["first_seen_profile_sync_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "movie_lists_last_seen_profile_sync_id_fkey",
        "movie_lists",
        "profile_syncs",
        ["last_seen_profile_sync_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_movie_lists_profile_id", "movie_lists", ["profile_id"])
    op.create_index(
        "uq_movie_lists_profile_source_key",
        "movie_lists",
        ["profile_id", "source_list_key"],
        unique=True,
        postgresql_where=sa.text("source_list_key IS NOT NULL"),
    )

    op.create_table(
        "movie_list_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("movie_list_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_movie_list_items_position_positive"),
        sa.ForeignKeyConstraint(["movie_list_id"], ["movie_lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("movie_list_id", "movie_id", name="unique_movie_list_item"),
    )
    op.create_index("ix_movie_list_items_movie", "movie_list_items", ["movie_id", "movie_list_id"])
    op.create_index(
        "uq_movie_list_items_active_position",
        "movie_list_items",
        ["movie_list_id", "position"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "profile_favorite_movies",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("first_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_profile_sync_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 4", name="ck_profile_favorite_position"),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["first_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_profile_sync_id"], ["profile_syncs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "position", name="unique_profile_favorite_position"),
        sa.UniqueConstraint("profile_id", "movie_id", name="unique_profile_favorite_movie"),
    )
    op.create_index(
        "ix_profile_favorite_movies_movie",
        "profile_favorite_movies",
        ["movie_id", "profile_id"],
    )

    op.create_table(
        "movie_enrichments",
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("original_title", sa.String(length=300), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("runtime_minutes", sa.Integer(), nullable=True),
        sa.Column("original_language", sa.String(length=20), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("genres", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_ARRAY, nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_ARRAY, nullable=False),
        sa.Column("credits", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_OBJECT, nullable=False),
        sa.Column("production_countries", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_ARRAY, nullable=False),
        sa.Column("poster_path", sa.String(length=500), nullable=True),
        sa.Column("backdrop_path", sa.String(length=500), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), server_default=JSONB_EMPTY_OBJECT, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "runtime_minutes IS NULL OR runtime_minutes >= 0",
            name="ck_movie_enrichments_runtime_nonnegative",
        ),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("movie_id"),
    )
    op.create_index("ix_movie_enrichments_expires_at", "movie_enrichments", ["expires_at"])

    op.create_table(
        "movie_watch_providers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("movie_id", sa.BigInteger(), nullable=False),
        sa.Column("region", sa.String(length=2), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=200), nullable=False),
        sa.Column("provider_type", sa.String(length=20), nullable=False),
        sa.Column("logo_path", sa.String(length=500), nullable=True),
        sa.Column("display_priority", sa.Integer(), nullable=True),
        sa.Column("link", sa.String(length=1000), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("char_length(region) = 2", name="ck_movie_watch_providers_region"),
        sa.CheckConstraint(
            "provider_type IN ('flatrate', 'rent', 'buy', 'free', 'ads')",
            name="ck_movie_watch_providers_type",
        ),
        sa.CheckConstraint(
            "display_priority IS NULL OR display_priority >= 0",
            name="ck_movie_watch_providers_priority_nonnegative",
        ),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "movie_id",
            "region",
            "provider_id",
            "provider_type",
            name="unique_movie_watch_provider",
        ),
    )
    op.create_index(
        "ix_movie_watch_providers_region_movie",
        "movie_watch_providers",
        ["region", "movie_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_movie_watch_providers_region_movie", table_name="movie_watch_providers")
    op.drop_table("movie_watch_providers")
    op.drop_index("ix_movie_enrichments_expires_at", table_name="movie_enrichments")
    op.drop_table("movie_enrichments")
    op.drop_index("ix_profile_favorite_movies_movie", table_name="profile_favorite_movies")
    op.drop_table("profile_favorite_movies")
    op.drop_index("uq_movie_list_items_active_position", table_name="movie_list_items")
    op.drop_index("ix_movie_list_items_movie", table_name="movie_list_items")
    op.drop_table("movie_list_items")

    op.drop_index("uq_movie_lists_profile_source_key", table_name="movie_lists")
    op.drop_index("ix_movie_lists_profile_id", table_name="movie_lists")
    op.drop_constraint("movie_lists_last_seen_profile_sync_id_fkey", "movie_lists", type_="foreignkey")
    op.drop_constraint("movie_lists_first_seen_profile_sync_id_fkey", "movie_lists", type_="foreignkey")
    op.drop_column("movie_lists", "removed_at")
    op.drop_column("movie_lists", "last_seen_profile_sync_id")
    op.drop_column("movie_lists", "first_seen_profile_sync_id")
    op.drop_column("movie_lists", "published_date")
    op.drop_column("movie_lists", "letterboxd_url")
    op.drop_column("movie_lists", "source_list_key")

    op.drop_index("ix_watchlist_items_movie_active", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_profile_removed", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_index("ix_watch_events_movie_date_active", table_name="watch_events")
    op.drop_index("ix_watch_events_profile_date", table_name="watch_events")
    op.drop_table("watch_events")
    op.drop_index("ix_profile_films_profile_removed", table_name="profile_films")
    op.drop_index("ix_profile_films_movie_profile", table_name="profile_films")
    op.drop_table("profile_films")

    op.drop_index("uq_reviews_profile_source_key", table_name="reviews")
    op.drop_index("ix_reviews_profile_movie", table_name="reviews")
    op.drop_index("ix_ratings_movie_profile", table_name="ratings")
    op.drop_column("reviews", "published_at")
    op.drop_column("reviews", "source_url")
    op.drop_column("reviews", "source_review_key")
    for table_name in ("reviews", "ratings"):
        op.drop_constraint(f"{table_name}_last_seen_profile_sync_id_fkey", table_name, type_="foreignkey")
        op.drop_constraint(f"{table_name}_first_seen_profile_sync_id_fkey", table_name, type_="foreignkey")
        op.drop_constraint(f"{table_name}_movie_id_fkey", table_name, type_="foreignkey")
        op.drop_column(table_name, "removed_at")
        op.drop_column(table_name, "last_seen_profile_sync_id")
        op.drop_column(table_name, "first_seen_profile_sync_id")
        op.drop_column(table_name, "movie_id")

    op.drop_constraint("ck_profiles_reported_lists_nonnegative", "profiles", type_="check")
    op.drop_constraint("ck_profiles_reported_reviews_nonnegative", "profiles", type_="check")
    op.drop_constraint("ck_profiles_reported_films_nonnegative", "profiles", type_="check")
    op.drop_constraint("ck_profiles_followers_nonnegative", "profiles", type_="check")
    op.drop_constraint("ck_profiles_following_nonnegative", "profiles", type_="check")
    op.drop_constraint("profiles_last_profile_sync_id_fkey", "profiles", type_="foreignkey")
    op.drop_column("profiles", "last_profile_sync_id")
    op.drop_column("profiles", "metadata_synced_at")
    op.drop_column("profiles", "reported_total_lists")
    op.drop_column("profiles", "reported_total_reviews")
    op.drop_column("profiles", "reported_total_films")
    op.drop_column("profiles", "followers_count")
    op.drop_column("profiles", "following_count")
    op.drop_column("profiles", "display_name")

    op.drop_index("uq_movies_imdb_id", table_name="movies")
    op.drop_index("uq_movies_tmdb_id", table_name="movies")
    op.drop_index("uq_movies_letterboxd_id", table_name="movies")
    op.drop_index("ix_movies_normalized_title_year", table_name="movies")
    op.drop_index("ix_movies_letterboxd_slug", table_name="movies")
    op.drop_table("movies")
    op.drop_table("sync_datasets")
    op.drop_index("ix_profile_syncs_profile_started", table_name="profile_syncs")
    op.drop_table("profile_syncs")

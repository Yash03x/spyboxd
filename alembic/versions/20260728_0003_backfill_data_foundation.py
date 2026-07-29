"""Backfill canonical movies, profile films, sync lineage, and watch events.

Revision ID: 20260728_0003
Revises: 20260728_0002
Create Date: 2026-07-28 21:45:00

The backfill is repeat-safe: every insert has a stable natural key and uses an
upsert. Legacy ratings and reviews are never removed or rewritten apart from
their newly added nullable linkage/lineage columns.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260728_0003"
down_revision: Union[str, None] = "20260728_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LEGACY_IMPORTER_VERSION = "20260728_0003"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO profile_syncs (
            profile_id,
            source_kind,
            source_fingerprint,
            importer_version,
            status,
            started_at,
            completed_at,
            manifest,
            coverage,
            stats
        )
        SELECT
            p.id,
            'legacy_database',
            'legacy-database-profile:' || p.id::text,
            '{LEGACY_IMPORTER_VERSION}',
            'completed',
            COALESCE(p.last_scraped_at, p.updated_at, p.created_at, CURRENT_TIMESTAMP),
            COALESCE(p.last_scraped_at, p.updated_at, p.created_at, CURRENT_TIMESTAMP),
            jsonb_build_object('migration_revision', '{LEGACY_IMPORTER_VERSION}'),
            COALESCE(p.enhanced_metrics::jsonb -> 'data_coverage', '{{}}'::jsonb),
            jsonb_build_object(
                'legacy_ratings', (SELECT count(*) FROM ratings r WHERE r.profile_id = p.id),
                'legacy_reviews', (SELECT count(*) FROM reviews rv WHERE rv.profile_id = p.id),
                'inferred_watch_events', (
                    SELECT count(*) FROM ratings r
                    WHERE r.profile_id = p.id AND r.watched_date IS NOT NULL
                )
            )
        FROM profiles p
        ON CONFLICT (profile_id, source_fingerprint, importer_version)
        DO UPDATE SET
            status = EXCLUDED.status,
            completed_at = EXCLUDED.completed_at,
            coverage = EXCLUDED.coverage,
            stats = EXCLUDED.stats,
            error_message = NULL
        """
    )

    op.execute(
        f"""
        UPDATE profiles p
        SET last_profile_sync_id = ps.id
        FROM profile_syncs ps
        WHERE ps.profile_id = p.id
          AND ps.source_kind = 'legacy_database'
          AND ps.importer_version = '{LEGACY_IMPORTER_VERSION}'
          AND p.last_profile_sync_id IS DISTINCT FROM ps.id
        """
    )

    op.execute(
        f"""
        INSERT INTO sync_datasets (
            profile_sync_id,
            dataset_name,
            source_row_count,
            imported_row_count,
            is_authoritative,
            metadata
        )
        SELECT
            ps.id,
            dataset.dataset_name,
            dataset.row_count,
            dataset.row_count,
            false,
            jsonb_build_object('inferred_from', dataset.inferred_from)
        FROM profile_syncs ps
        CROSS JOIN LATERAL (
            VALUES
                (
                    'ratings',
                    (SELECT count(*)::integer FROM ratings r WHERE r.profile_id = ps.profile_id),
                    'legacy ratings table'
                ),
                (
                    'reviews',
                    (SELECT count(*)::integer FROM reviews rv WHERE rv.profile_id = ps.profile_id),
                    'legacy reviews table'
                ),
                (
                    'watch_events',
                    (
                        SELECT count(*)::integer FROM ratings r
                        WHERE r.profile_id = ps.profile_id AND r.watched_date IS NOT NULL
                    ),
                    'one retained watched_date per legacy rating'
                )
        ) AS dataset(dataset_name, row_count, inferred_from)
        WHERE ps.source_kind = 'legacy_database'
          AND ps.importer_version = '{LEGACY_IMPORTER_VERSION}'
        ON CONFLICT (profile_sync_id, dataset_name)
        DO UPDATE SET
            source_row_count = EXCLUDED.source_row_count,
            imported_row_count = EXCLUDED.imported_row_count,
            is_authoritative = EXCLUDED.is_authoritative,
            metadata = EXCLUDED.metadata
        """
    )

    op.execute(
        """
        WITH movie_candidates AS (
            SELECT
                CASE
                    WHEN NULLIF(BTRIM(r.letterboxd_id), '') IS NOT NULL
                        THEN 'letterboxd:' || BTRIM(r.letterboxd_id)
                    WHEN NULLIF(BTRIM(r.film_slug), '') IS NOT NULL
                        THEN 'letterboxd-slug:' || LOWER(BTRIM(r.film_slug))
                    ELSE
                        'title-year:'
                        || LOWER(REGEXP_REPLACE(BTRIM(r.movie_title), '\\s+', ' ', 'g'))
                        || ':' || COALESCE(r.movie_year::text, 'unknown')
                END AS canonical_key,
                NULLIF(BTRIM(r.letterboxd_id), '') AS letterboxd_id,
                NULLIF(LOWER(BTRIM(r.film_slug)), '') AS letterboxd_slug,
                r.movie_title AS title,
                LOWER(REGEXP_REPLACE(BTRIM(r.movie_title), '\\s+', ' ', 'g')) AS normalized_title,
                r.movie_year AS release_year,
                CASE
                    WHEN NULLIF(BTRIM(r.film_slug), '') IS NOT NULL
                        THEN '/film/' || BTRIM(r.film_slug) || '/'
                    ELSE NULL
                END AS letterboxd_url,
                NULLIF(BTRIM(r.poster_url), '') AS poster_url,
                p.last_profile_sync_id AS profile_sync_id,
                r.id AS source_row_id,
                r.created_at AS source_created_at
            FROM ratings r
            JOIN profiles p ON p.id = r.profile_id

            UNION ALL

            SELECT
                CASE
                    WHEN NULLIF(BTRIM(rv.letterboxd_id), '') IS NOT NULL
                        THEN 'letterboxd:' || BTRIM(rv.letterboxd_id)
                    ELSE
                        'title-year:'
                        || LOWER(REGEXP_REPLACE(BTRIM(rv.movie_title), '\\s+', ' ', 'g'))
                        || ':' || COALESCE(rv.movie_year::text, 'unknown')
                END AS canonical_key,
                NULLIF(BTRIM(rv.letterboxd_id), '') AS letterboxd_id,
                NULL::text AS letterboxd_slug,
                rv.movie_title AS title,
                LOWER(REGEXP_REPLACE(BTRIM(rv.movie_title), '\\s+', ' ', 'g')) AS normalized_title,
                rv.movie_year AS release_year,
                NULL::text AS letterboxd_url,
                NULL::text AS poster_url,
                p.last_profile_sync_id AS profile_sync_id,
                rv.id AS source_row_id,
                rv.created_at AS source_created_at
            FROM reviews rv
            JOIN profiles p ON p.id = rv.profile_id
        ),
        ranked_candidates AS (
            SELECT
                candidate.*,
                ROW_NUMBER() OVER (
                    PARTITION BY canonical_key
                    ORDER BY
                        (poster_url IS NOT NULL) DESC,
                        (letterboxd_slug IS NOT NULL) DESC,
                        source_created_at DESC NULLS LAST,
                        source_row_id DESC
                ) AS candidate_rank,
                MIN(profile_sync_id) OVER (PARTITION BY canonical_key) AS first_sync_id,
                MAX(profile_sync_id) OVER (PARTITION BY canonical_key) AS last_sync_id
            FROM movie_candidates candidate
        )
        INSERT INTO movies (
            canonical_key,
            letterboxd_id,
            letterboxd_slug,
            title,
            normalized_title,
            release_year,
            letterboxd_url,
            poster_url,
            first_seen_profile_sync_id,
            last_seen_profile_sync_id
        )
        SELECT
            canonical_key,
            letterboxd_id,
            letterboxd_slug,
            title,
            normalized_title,
            release_year,
            letterboxd_url,
            poster_url,
            first_sync_id,
            last_sync_id
        FROM ranked_candidates
        WHERE candidate_rank = 1
        ON CONFLICT (canonical_key)
        DO UPDATE SET
            letterboxd_id = COALESCE(EXCLUDED.letterboxd_id, movies.letterboxd_id),
            letterboxd_slug = COALESCE(EXCLUDED.letterboxd_slug, movies.letterboxd_slug),
            title = EXCLUDED.title,
            normalized_title = EXCLUDED.normalized_title,
            release_year = COALESCE(EXCLUDED.release_year, movies.release_year),
            letterboxd_url = COALESCE(EXCLUDED.letterboxd_url, movies.letterboxd_url),
            poster_url = COALESCE(EXCLUDED.poster_url, movies.poster_url),
            first_seen_profile_sync_id = COALESCE(
                movies.first_seen_profile_sync_id,
                EXCLUDED.first_seen_profile_sync_id
            ),
            last_seen_profile_sync_id = COALESCE(
                EXCLUDED.last_seen_profile_sync_id,
                movies.last_seen_profile_sync_id
            ),
            updated_at = CURRENT_TIMESTAMP
        """
    )

    op.execute(
        """
        UPDATE ratings r
        SET movie_id = m.id
        FROM movies m
        WHERE m.canonical_key = CASE
            WHEN NULLIF(BTRIM(r.letterboxd_id), '') IS NOT NULL
                THEN 'letterboxd:' || BTRIM(r.letterboxd_id)
            WHEN NULLIF(BTRIM(r.film_slug), '') IS NOT NULL
                THEN 'letterboxd-slug:' || LOWER(BTRIM(r.film_slug))
            ELSE
                'title-year:'
                || LOWER(REGEXP_REPLACE(BTRIM(r.movie_title), '\\s+', ' ', 'g'))
                || ':' || COALESCE(r.movie_year::text, 'unknown')
        END
          AND r.movie_id IS DISTINCT FROM m.id
        """
    )

    op.execute(
        """
        UPDATE reviews rv
        SET movie_id = m.id
        FROM movies m
        WHERE m.canonical_key = CASE
            WHEN NULLIF(BTRIM(rv.letterboxd_id), '') IS NOT NULL
                THEN 'letterboxd:' || BTRIM(rv.letterboxd_id)
            ELSE
                'title-year:'
                || LOWER(REGEXP_REPLACE(BTRIM(rv.movie_title), '\\s+', ' ', 'g'))
                || ':' || COALESCE(rv.movie_year::text, 'unknown')
        END
          AND rv.movie_id IS DISTINCT FROM m.id
        """
    )

    op.execute(
        """
        UPDATE ratings r
        SET
            first_seen_profile_sync_id = COALESCE(r.first_seen_profile_sync_id, p.last_profile_sync_id),
            last_seen_profile_sync_id = COALESCE(p.last_profile_sync_id, r.last_seen_profile_sync_id)
        FROM profiles p
        WHERE p.id = r.profile_id
          AND (
              r.first_seen_profile_sync_id IS NULL
              OR r.last_seen_profile_sync_id IS DISTINCT FROM p.last_profile_sync_id
          )
        """
    )

    op.execute(
        """
        UPDATE reviews rv
        SET
            first_seen_profile_sync_id = COALESCE(rv.first_seen_profile_sync_id, p.last_profile_sync_id),
            last_seen_profile_sync_id = COALESCE(p.last_profile_sync_id, rv.last_seen_profile_sync_id),
            source_review_key = COALESCE(rv.source_review_key, 'legacy-review:' || rv.id::text)
        FROM profiles p
        WHERE p.id = rv.profile_id
          AND (
              rv.first_seen_profile_sync_id IS NULL
              OR rv.last_seen_profile_sync_id IS DISTINCT FROM p.last_profile_sync_id
              OR rv.source_review_key IS NULL
          )
        """
    )

    op.execute(
        """
        INSERT INTO profile_films (
            profile_id,
            movie_id,
            legacy_rating_id,
            rating,
            is_liked,
            tags,
            first_watched_date,
            latest_watched_date,
            watch_count,
            rewatch_count,
            has_review,
            first_seen_profile_sync_id,
            last_seen_profile_sync_id,
            created_at,
            updated_at
        )
        SELECT
            r.profile_id,
            r.movie_id,
            r.id,
            r.rating,
            COALESCE(r.is_liked, false),
            CASE
                WHEN r.tags IS NULL OR r.tags::text = 'null' THEN '[]'::jsonb
                ELSE r.tags::jsonb
            END,
            r.watched_date,
            r.watched_date,
            CASE WHEN COALESCE(r.is_rewatch, false) THEN 2 ELSE 1 END,
            CASE WHEN COALESCE(r.is_rewatch, false) THEN 1 ELSE 0 END,
            EXISTS (
                SELECT 1
                FROM reviews rv
                WHERE rv.profile_id = r.profile_id
                  AND rv.movie_id = r.movie_id
                  AND rv.removed_at IS NULL
            ),
            r.first_seen_profile_sync_id,
            r.last_seen_profile_sync_id,
            COALESCE(r.created_at, CURRENT_TIMESTAMP),
            CURRENT_TIMESTAMP
        FROM ratings r
        WHERE r.movie_id IS NOT NULL
        ON CONFLICT (profile_id, movie_id)
        DO UPDATE SET
            legacy_rating_id = EXCLUDED.legacy_rating_id,
            rating = EXCLUDED.rating,
            is_liked = EXCLUDED.is_liked,
            tags = EXCLUDED.tags,
            first_watched_date = COALESCE(profile_films.first_watched_date, EXCLUDED.first_watched_date),
            latest_watched_date = COALESCE(EXCLUDED.latest_watched_date, profile_films.latest_watched_date),
            watch_count = GREATEST(profile_films.watch_count, EXCLUDED.watch_count),
            rewatch_count = GREATEST(profile_films.rewatch_count, EXCLUDED.rewatch_count),
            has_review = EXCLUDED.has_review,
            first_seen_profile_sync_id = COALESCE(
                profile_films.first_seen_profile_sync_id,
                EXCLUDED.first_seen_profile_sync_id
            ),
            last_seen_profile_sync_id = COALESCE(
                EXCLUDED.last_seen_profile_sync_id,
                profile_films.last_seen_profile_sync_id
            ),
            removed_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        """
    )

    op.execute(
        """
        INSERT INTO watch_events (
            profile_id,
            movie_id,
            profile_film_id,
            event_key,
            watched_date,
            rating,
            is_rewatch,
            is_liked,
            has_review,
            tags,
            source_kind,
            source_entry_id,
            source_url,
            first_seen_profile_sync_id,
            last_seen_profile_sync_id,
            created_at,
            updated_at
        )
        SELECT
            r.profile_id,
            r.movie_id,
            pf.id,
            'legacy-rating:' || r.id::text,
            r.watched_date,
            r.rating,
            COALESCE(r.is_rewatch, false),
            COALESCE(r.is_liked, false),
            pf.has_review,
            pf.tags,
            'legacy_rating_snapshot',
            r.id::text,
            CASE
                WHEN NULLIF(BTRIM(r.film_slug), '') IS NOT NULL
                    THEN '/film/' || BTRIM(r.film_slug) || '/'
                ELSE NULL
            END,
            r.first_seen_profile_sync_id,
            r.last_seen_profile_sync_id,
            COALESCE(r.created_at, CURRENT_TIMESTAMP),
            CURRENT_TIMESTAMP
        FROM ratings r
        JOIN profile_films pf
          ON pf.profile_id = r.profile_id
         AND pf.movie_id = r.movie_id
        WHERE r.movie_id IS NOT NULL
          AND r.watched_date IS NOT NULL
        ON CONFLICT (profile_id, event_key)
        DO UPDATE SET
            movie_id = EXCLUDED.movie_id,
            profile_film_id = EXCLUDED.profile_film_id,
            watched_date = EXCLUDED.watched_date,
            rating = EXCLUDED.rating,
            is_rewatch = EXCLUDED.is_rewatch,
            is_liked = EXCLUDED.is_liked,
            has_review = EXCLUDED.has_review,
            tags = EXCLUDED.tags,
            source_url = EXCLUDED.source_url,
            last_seen_profile_sync_id = EXCLUDED.last_seen_profile_sync_id,
            updated_at = CURRENT_TIMESTAMP
        """
    )

    op.execute(
        """
        UPDATE movie_lists ml
        SET
            source_list_key = COALESCE(ml.source_list_key, 'legacy-list:' || ml.id::text),
            first_seen_profile_sync_id = COALESCE(
                ml.first_seen_profile_sync_id,
                p.last_profile_sync_id
            ),
            last_seen_profile_sync_id = COALESCE(
                p.last_profile_sync_id,
                ml.last_seen_profile_sync_id
            )
        FROM profiles p
        WHERE p.id = ml.profile_id
        """
    )


def downgrade() -> None:
    # Data-only, additive backfill. The preceding schema downgrade removes these
    # tables/columns if a full rollback is explicitly requested. Leaving the
    # backfilled rows intact during a one-revision downgrade avoids deleting any
    # rows that a newer importer may already have refreshed.
    pass

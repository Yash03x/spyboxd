#!/usr/bin/env python3
"""Read-only, repeatable checks of the database actually served by Spyboxd.

Counts are kept at their stated grain. Undated films are a coverage gap, never
invented diary entries. Exit 1 only for broken invariants, not source sparsity.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database.connection import engine
from sqlalchemy import text


CHECKS = {
    "duplicate_profile_films": "SELECT COUNT(*) FROM (SELECT profile_id,movie_id FROM profile_films GROUP BY 1,2 HAVING COUNT(*)>1) d",
    "duplicate_event_keys": "SELECT COUNT(*) FROM (SELECT profile_id,event_key FROM watch_events WHERE superseded_at IS NULL GROUP BY 1,2 HAVING COUNT(*)>1) d",
    "orphan_events": "SELECT COUNT(*) FROM watch_events w LEFT JOIN profiles p ON p.id=w.profile_id LEFT JOIN movies m ON m.id=w.movie_id WHERE p.id IS NULL OR m.id IS NULL",
    "invalid_ratings": "SELECT COUNT(*) FROM profile_films WHERE rating IS NOT NULL AND (rating < 0.5 OR rating > 5 OR rating <> floor(rating * 2) / 2)",
    "impossible_watch_counts": "SELECT COUNT(*) FROM profile_films WHERE watch_count<0 OR rewatch_count<0 OR rewatch_count>watch_count",
}


def audit(connection):
    failures = {name: connection.execute(text(query)).scalar_one() for name, query in CHECKS.items()}
    profiles = [dict(row) for row in connection.execute(text("""
        WITH films AS (
          SELECT profile_id, COUNT(*) films, COUNT(*) FILTER (WHERE rating IS NOT NULL) rated,
            COUNT(*) FILTER (WHERE first_watched_date IS NULL AND latest_watched_date IS NULL) undated_films
          FROM profile_films WHERE removed_at IS NULL GROUP BY profile_id
        ), events AS (
          SELECT profile_id, COUNT(*) diary_events, MAX(watched_date) latest_watch,
            COUNT(*) FILTER (WHERE watched_date > CURRENT_DATE) future_events
          FROM watch_events WHERE superseded_at IS NULL GROUP BY profile_id
        ) SELECT p.username,p.scraping_status,p.last_scraped_at,
          COALESCE(f.films,0) films,COALESCE(f.rated,0) rated,
          COALESCE(f.undated_films,0) undated_films,COALESCE(e.diary_events,0) diary_events,
          e.latest_watch,COALESCE(e.future_events,0) future_events
        FROM profiles p LEFT JOIN films f ON f.profile_id=p.id LEFT JOIN events e ON e.profile_id=p.id
        WHERE p.is_active ORDER BY p.username
    """)).mappings()]
    metadata = dict(connection.execute(text("""
        WITH relevant AS (
          SELECT movie_id FROM profile_films WHERE removed_at IS NULL
          UNION SELECT movie_id FROM watchlist_items WHERE removed_at IS NULL
        ) SELECT COUNT(*) movies, COUNT(e.movie_id) enriched,
          COUNT(*) FILTER (WHERE e.movie_id IS NULL) missing_metadata,
          COUNT(*) FILTER (WHERE e.movie_id IS NOT NULL AND (e.runtime_minutes IS NULL OR e.runtime_minutes=0)) missing_runtime,
          COUNT(*) FILTER (WHERE e.movie_id IS NOT NULL AND NULLIF(e.original_language,'') IS NULL) missing_language,
          COUNT(*) FILTER (WHERE e.expires_at < NOW()) expired_metadata
        FROM relevant r LEFT JOIN movie_enrichments e ON e.movie_id=r.movie_id
    """)).mappings().one())
    datasets = [dict(row) for row in connection.execute(text("""
        SELECT p.username,s.completed_at,d.dataset_name,d.source_row_count,d.imported_row_count,
          d.is_authoritative,d.metadata
        FROM profiles p JOIN profile_syncs s ON s.id=p.last_profile_sync_id
        JOIN sync_datasets d ON d.profile_sync_id=s.id
        WHERE NOT d.is_authoritative OR d.source_row_count<>d.imported_row_count
        ORDER BY p.username,d.dataset_name
    """)).mappings()]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "invariant_failures": failures, "profiles": profiles, "metadata": metadata,
        "datasets_requiring_review": datasets,
        "notes": [
            "Film state is one profile-film pair; diary events are individual watches, including rewatches.",
            "A missing watch date may mean the person never logged a diary entry. Do not infer a date from a film release or import timestamp.",
            "Non-authoritative or unequal dataset row counts require source-contract review; they are not automatically a failed import.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        result = audit(connection)
    rendered = json.dumps(result, indent=2, default=str)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(json.dumps({key: result[key] for key in ("checked_at", "invariant_failures", "metadata")}, indent=2))
    print(f"Profiles: {len(result['profiles'])}; datasets requiring review: {len(result['datasets_requiring_review'])}")
    raise SystemExit(1 if any(result["invariant_failures"].values()) else 0)

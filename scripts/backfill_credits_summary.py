"""Fill movie_enrichments.credits_summary from the credits already stored.

Purely local work — no network, no TMDB call. Every input is a column this
database already holds, so this is safe to run at any time and safe to
interrupt: rows are committed in batches and only NULL summaries are selected,
which makes a second run continue rather than repeat.

Why a script and not the migration: the migration adds the column in
milliseconds, while rewriting every enrichment row takes long enough to matter
on a live database. Readers fall back to the full `credits` document for rows
this has not reached, so the deploy is correct before, during and after.

    python scripts/backfill_credits_summary.py            # everything
    python scripts/backfill_credits_summary.py --limit 500
    python scripts/backfill_credits_summary.py --dry-run
    python scripts/backfill_credits_summary.py --refresh  # redo summarised rows
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
load_dotenv(REPO_ROOT / ".env")

# On the VPS there is no repo-level .env: DATABASE_URL lives in the API's own
# environment file, and only that one key is taken from it. Resolved before
# importing `database.connection`, which reads it at import time.
_ENV_FILE = os.getenv("SPYBOXD_DATABASE_ENV_FILE")
if _ENV_FILE and not os.getenv("DATABASE_URL"):
    from env_file import read_database_url  # noqa: E402

    os.environ["DATABASE_URL"] = read_database_url(_ENV_FILE)

from database.connection import SessionLocal  # noqa: E402
from database.models import MovieEnrichment  # noqa: E402
from services.tmdb_enrichment import collection_name, summarize_credits  # noqa: E402


def _measure(value: Any) -> int:
    try:
        return len(json.dumps(value))
    except (TypeError, ValueError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows to process.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per commit.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-summarise rows that already have a summary (use after changing the shape).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    arguments = parser.parse_args()

    db = SessionLocal()
    try:
        # The three detail values come out of raw_payload by JSON path here,
        # which is the expensive read this backfill exists to stop the panels
        # doing. Paying it once, in a paced batch job, is the whole point.
        query = db.query(
            MovieEnrichment.movie_id,
            MovieEnrichment.credits,
            MovieEnrichment.raw_payload["details"]["production_companies"],
            MovieEnrichment.raw_payload["details"]["spoken_languages"],
            MovieEnrichment.raw_payload["details"]["belongs_to_collection"],
        )
        if not arguments.refresh:
            query = query.filter(
                (MovieEnrichment.credits_summary.is_(None))
                | (MovieEnrichment.production_companies.is_(None))
            )
        query = query.order_by(MovieEnrichment.movie_id)
        if arguments.limit:
            query = query.limit(arguments.limit)

        rows = query.all()
        print(f"{len(rows)} enrichment row(s) to summarise")
        if not rows:
            return 0

        before = after = written = 0
        for index, (movie_id, credits, companies, languages, collection) in enumerate(
            rows, start=1
        ):
            summary = summarize_credits(credits)
            before += _measure(credits)
            after += _measure(summary)
            if not arguments.dry_run:
                db.query(MovieEnrichment).filter(
                    MovieEnrichment.movie_id == movie_id
                ).update(
                    {
                        "credits_summary": summary,
                        # Empty lists rather than NULL: the row has been
                        # visited, and NULL is what the reader's fallback keys
                        # off. Leaving it null for a film TMDB lists no
                        # companies for would make every later page load fetch
                        # the payload again to learn the same nothing.
                        "production_companies": companies if isinstance(companies, list) else [],
                        "spoken_languages": languages if isinstance(languages, list) else [],
                        "collection_name": collection_name(collection),
                    },
                    synchronize_session=False,
                )
                written += 1
                if index % arguments.batch_size == 0:
                    db.commit()
                    print(f"  committed {index}/{len(rows)}")
        if not arguments.dry_run:
            db.commit()

        saved = (1 - after / before) * 100 if before else 0.0
        print(
            f"\n{'would write' if arguments.dry_run else 'wrote'} {written or len(rows)} summaries"
        )
        print(f"  credits  : {before / len(rows):>9,.0f} bytes/film")
        print(f"  summary  : {after / len(rows):>9,.0f} bytes/film")
        print(f"  reduction: {saved:>9.1f}%")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

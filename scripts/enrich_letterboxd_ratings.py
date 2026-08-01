#!/usr/bin/env python3
"""Opt-in batch command for backfilling Letterboxd's own crowd rating per film."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

load_dotenv(REPO_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env", override=False)

from database.connection import SessionLocal  # noqa: E402
from services.letterboxd_ratings import (  # noqa: E402
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MAX_RETRIES,
    LetterboxdRatingFetcher,
    sync_letterboxd_ratings,
)


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill movies.letterboxd_average_rating / letterboxd_rating_count "
            "from Letterboxd's rating-histogram include. Never run by ingestion; "
            "deliberately paced, bounded by --limit and resumable via --max-age-days."
        )
    )
    parser.add_argument(
        "--limit",
        type=positive_integer,
        default=None,
        help="Maximum number of films to process in this run.",
    )
    parser.add_argument(
        "--max-age-days",
        type=positive_integer,
        default=int(os.getenv("LETTERBOXD_RATING_MAX_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS))),
        help=(
            "Skip films whose letterboxd_rating_synced_at is newer than this "
            f"many days (default: {DEFAULT_MAX_AGE_DAYS}). This is what makes a "
            "long run resumable."
        ),
    )
    parser.add_argument(
        "--delay",
        type=non_negative_float,
        default=float(os.getenv("LETTERBOXD_RATING_DELAY_SECONDS", str(DEFAULT_DELAY_SECONDS))),
        help=f"Seconds to sleep between requests (default: {DEFAULT_DELAY_SECONDS}).",
    )
    parser.add_argument(
        "--batch-size",
        type=positive_integer,
        default=DEFAULT_BATCH_SIZE,
        help="Number of films committed per database batch.",
    )
    parser.add_argument(
        "--max-retries",
        type=positive_integer,
        default=DEFAULT_MAX_RETRIES,
        help="Attempts per film before it is logged as failed and skipped.",
    )
    parser.add_argument(
        "--backoff",
        type=non_negative_float,
        default=DEFAULT_BACKOFF_SECONDS,
        help="Base seconds for exponential retry backoff.",
    )
    parser.add_argument(
        "--movie-id",
        action="append",
        type=positive_integer,
        default=None,
        help="Restrict to one canonical movie ID; repeat for multiple IDs.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch selected films even when their sync stamp is still fresh.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidates without making requests or database writes.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    fetcher = None
    if not args.dry_run:
        fetcher = LetterboxdRatingFetcher(
            max_retries=args.max_retries,
            backoff_seconds=args.backoff,
        )

    def print_progress(index, total, candidate) -> None:
        print(f"[{index}/{total}] {candidate.title} ({candidate.slug})", file=sys.stderr)

    with SessionLocal() as db:
        try:
            stats = sync_letterboxd_ratings(
                db,
                fetcher,
                max_age_days=args.max_age_days,
                delay_seconds=args.delay,
                batch_size=args.batch_size,
                limit=args.limit,
                movie_ids=args.movie_id,
                refresh=args.refresh,
                dry_run=args.dry_run,
                progress=None if args.dry_run else print_progress,
            )
        except Exception as exc:
            db.rollback()
            print(f"Letterboxd rating sync failed: {exc}", file=sys.stderr)
            return 1

    payload = stats.to_dict()
    payload.update(
        {
            "max_age_days": args.max_age_days,
            "delay_seconds": args.delay,
            "batch_size": args.batch_size,
            "refresh": args.refresh,
        }
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

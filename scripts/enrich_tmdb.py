#!/usr/bin/env python3
"""Opt-in batch command for enriching canonical Spyboxd movies with TMDB."""

from __future__ import annotations

import argparse
import json
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
from services.tmdb_client import TMDBClient, TMDBConfigurationError  # noqa: E402
from services.tmdb_enrichment import enrich_movies  # noqa: E402


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich canonical Spyboxd movies with cached TMDB metadata and "
            "region-specific watch providers. This command is never run by ingestion."
        )
    )
    parser.add_argument(
        "--region",
        default=os.getenv("TMDB_DEFAULT_REGION", "DE"),
        help="Two-letter provider region (default: TMDB_DEFAULT_REGION or DE).",
    )
    parser.add_argument(
        "--language",
        default=os.getenv("TMDB_LANGUAGE", "en-US"),
        help="TMDB response language (default: en-US).",
    )
    parser.add_argument(
        "--cache-days",
        type=positive_integer,
        default=int(os.getenv("TMDB_CACHE_DAYS", "30")),
        help=(
            "Number of days before details/providers refresh or an unsuccessful "
            "identity lookup is retried."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=positive_integer,
        default=25,
        help="Number of prepared movies committed per database batch.",
    )
    parser.add_argument(
        "--limit",
        type=positive_integer,
        default=None,
        help="Maximum number of candidate movies to process.",
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
        help="Refresh selected movies even when their cache is still fresh.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count candidates without making TMDB requests or database writes.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    normalized_region = args.region.strip().upper()

    client = None
    if not args.dry_run:
        try:
            client = TMDBClient.from_env()
        except TMDBConfigurationError as exc:
            print(f"TMDB enrichment is not configured: {exc}", file=sys.stderr)
            return 2

    def print_progress(index, total, candidate) -> None:
        print(
            f"[{index}/{total}] {candidate.title}"
            f"{f' ({candidate.release_year})' if candidate.release_year else ''}",
            file=sys.stderr,
        )

    with SessionLocal() as db:
        try:
            stats = enrich_movies(
                db,
                client,
                region=normalized_region,
                language=args.language,
                cache_days=args.cache_days,
                batch_size=args.batch_size,
                limit=args.limit,
                movie_ids=args.movie_id,
                refresh=args.refresh,
                dry_run=args.dry_run,
                progress=None if args.dry_run else print_progress,
            )
        except Exception as exc:
            db.rollback()
            print(f"TMDB enrichment failed: {exc}", file=sys.stderr)
            return 1

    payload = stats.to_dict()
    payload.update(
        {
            "region": normalized_region,
            "cache_days": args.cache_days,
            "batch_size": args.batch_size,
            "refresh": args.refresh,
        }
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

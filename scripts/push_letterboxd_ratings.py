#!/usr/bin/env python3
"""Push locally scraped Letterboxd film ratings to the Spyboxd API.

``scripts/enrich_letterboxd_ratings.py`` can only run where the scraper runs:
Letterboxd challenges datacenter IPs, so the backfill writes
``movies.letterboxd_average_rating`` into the *local* database on a residential
machine. This script is the second half of that trip — it reads those values
back out and POSTs them to ``/api/films/letterboxd-ratings`` with the same
``INGESTION_API_TOKEN`` that ``scripts/local_full_sync.py`` uses for ``/upload/``.

Film ratings are film-level and shared by every profile, so nothing here is
per-profile data: it is one modest ``(slug, average, count)`` dataset that the
whole library reads. Batches are idempotent, so an interrupted run is safe to
repeat.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def load_local_environment(env_file: Path = REPO_ROOT / ".env") -> None:
    """Load ignored local credentials without overriding the caller's shell."""
    load_dotenv(env_file, override=False)


load_local_environment()

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api.routes.film_ratings import MAX_BATCH_SIZE  # noqa: E402
from database.connection import SessionLocal  # noqa: E402
from database.models import Movie  # noqa: E402
from services.letterboxd_ratings import resolve_slug  # noqa: E402


RATINGS_PATH = "/api/films/letterboxd-ratings"
DEFAULT_BATCH_SIZE = 500


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def batch_size_argument(value: str) -> int:
    parsed = positive_integer(value)
    if parsed > MAX_BATCH_SIZE:
        raise argparse.ArgumentTypeError(f"must not exceed {MAX_BATCH_SIZE}")
    return parsed


def collect_ratings(db: Session, *, limit: Optional[int] = None) -> tuple[List[Dict[str, Any]], int]:
    """Read every film that already carries a Letterboxd crowd average.

    Films without a usable slug cannot be matched on the other side, so they are
    counted and left out rather than sent. Returns ``(entries, skipped_no_slug)``.
    """

    query = (
        db.query(
            Movie.letterboxd_slug,
            Movie.letterboxd_url,
            Movie.letterboxd_average_rating,
            Movie.letterboxd_rating_count,
            Movie.letterboxd_rating_synced_at,
        )
        .filter(Movie.letterboxd_average_rating.isnot(None))
        .order_by(Movie.id)
    )
    if limit is not None:
        query = query.limit(limit)

    entries: List[Dict[str, Any]] = []
    skipped_no_slug = 0
    for slug, url, average, count, synced_at in query.all():
        resolved = resolve_slug(slug, url)
        if not resolved:
            skipped_no_slug += 1
            continue
        entries.append(
            {
                "slug": resolved,
                "average_rating": float(average),
                "rating_count": int(count) if count is not None else None,
                "synced_at": synced_at.isoformat() if synced_at is not None else None,
            }
        )
    return entries, skipped_no_slug


def iter_batches(entries: Sequence[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    for start in range(0, len(entries), size):
        yield list(entries[start : start + size])


def push_batch(
    *,
    api_base_url: str,
    entries: Sequence[Dict[str, Any]],
    upload_token: Optional[str],
    bearer_token: Optional[str],
    timeout_seconds: int,
) -> Dict[str, Any]:
    headers = {}
    if upload_token:
        headers["X-Upload-Token"] = upload_token
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    response = requests.post(
        f"{api_base_url.rstrip('/')}{RATINGS_PATH}",
        json={"ratings": list(entries)},
        headers=headers,
        timeout=timeout_seconds,
    )

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_response": response.text}

    if not response.ok:
        raise RuntimeError(f"Rating push failed ({response.status_code}): {payload}")

    return payload


def push_ratings(
    entries: Sequence[Dict[str, Any]],
    *,
    api_base_url: str,
    upload_token: Optional[str],
    bearer_token: Optional[str],
    batch_size: int,
    timeout_seconds: int,
    progress=None,
) -> Dict[str, Any]:
    """Send every batch, accumulating the API's per-batch counts."""

    totals = {"received": 0, "updated": 0, "unmatched": 0, "skipped": 0}
    batches = 0
    total_batches = (len(entries) + batch_size - 1) // batch_size
    for batch in iter_batches(entries, batch_size):
        batches += 1
        if progress:
            progress(batches, total_batches, len(batch))
        payload = push_batch(
            api_base_url=api_base_url,
            entries=batch,
            upload_token=upload_token,
            bearer_token=bearer_token,
            timeout_seconds=timeout_seconds,
        )
        for key in totals:
            totals[key] += int(payload.get(key, 0) or 0)
    return {"batches": batches, **totals}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Push locally backfilled Letterboxd film ratings (movies.letterboxd_*) "
            "to the Spyboxd API, which cannot scrape them itself because Letterboxd "
            "challenges datacenter IPs."
        ),
    )
    parser.add_argument(
        "--api-base-url",
        default=os.environ.get("SPYBOXD_API_BASE_URL"),
        help="Spyboxd API base URL, e.g. https://api.spyboxd.com",
    )
    parser.add_argument(
        "--upload-token",
        default=os.environ.get("INGESTION_API_TOKEN"),
        help="Value for X-Upload-Token. Recommended for trusted local syncs.",
    )
    parser.add_argument(
        "--bearer-token",
        default=os.environ.get("SPYBOXD_BEARER_TOKEN"),
        help="Clerk admin bearer token. Use this instead of --upload-token if preferred.",
    )
    parser.add_argument(
        "--limit",
        type=positive_integer,
        default=None,
        help="Maximum number of films to push in this run.",
    )
    parser.add_argument(
        "--batch-size",
        type=batch_size_argument,
        default=DEFAULT_BATCH_SIZE,
        help=f"Films per request (default: {DEFAULT_BATCH_SIZE}, API maximum: {MAX_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=positive_integer,
        default=120,
        help="HTTP timeout for each batch request.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be pushed without contacting the API.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if not args.dry_run:
        if not args.api_base_url:
            print("Provide --api-base-url or set SPYBOXD_API_BASE_URL.", file=sys.stderr)
            return 1
        if not args.upload_token and not args.bearer_token:
            print(
                "Provide --upload-token (INGESTION_API_TOKEN) or --bearer-token.",
                file=sys.stderr,
            )
            return 1

    try:
        with SessionLocal() as db:
            entries, skipped_no_slug = collect_ratings(db, limit=args.limit)
    except Exception as exc:
        print(f"Reading local film ratings failed: {exc}", file=sys.stderr)
        return 1

    summary: Dict[str, Any] = {
        "films": len(entries),
        "skipped_no_slug": skipped_no_slug,
        "batch_size": args.batch_size,
        "batches": (len(entries) + args.batch_size - 1) // args.batch_size,
        "api_base_url": args.api_base_url,
        "dry_run": args.dry_run,
    }

    if args.dry_run:
        summary["sample"] = entries[:3]
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if not entries:
        print("No locally backfilled Letterboxd ratings to push.", file=sys.stderr)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    def print_progress(index: int, total: int, size: int) -> None:
        print(f"[{index}/{total}] pushing {size} films...", file=sys.stderr)

    try:
        result = push_ratings(
            entries,
            api_base_url=args.api_base_url,
            upload_token=args.upload_token,
            bearer_token=args.bearer_token,
            batch_size=args.batch_size,
            timeout_seconds=args.timeout_seconds,
            progress=print_progress,
        )
    except Exception as exc:
        print(f"Rating push failed: {exc}", file=sys.stderr)
        return 1

    summary.update(result)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

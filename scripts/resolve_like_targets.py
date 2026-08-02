#!/usr/bin/env python3
"""Resolve stored `boxd.it` like targets to the member who wrote them.

An official export records a like as a short link and a date, which is all
Letterboxd publishes. The link redirects to the full path, and that path names
both the author and — for a review — the film:

    https://boxd.it/fwSSUD
      -> https://letterboxd.com/deathproof/film/spider-man-brand-new-day/

Unresolved, a like is an opaque token and a member's 46 of them render as the
number 46. Resolved, they answer whose writing that member actually rates.

One request per unresolved like against a rate-limited host, so results are
stored and rows already carrying `target_resolved_at` are skipped unless
`--refresh` is passed.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from database.connection import SessionLocal  # noqa: E402
from database.models import MemberContentLike, Profile  # noqa: E402

# `/<member>/film/<slug>/` for a review, `/<member>/list/<slug>/` for a list.
TARGET = re.compile(
    r"^https://letterboxd\.com/([A-Za-z0-9_]+)/(?:(film|list)/([a-z0-9][a-z0-9-]*))?"
)
# Paths that are Letterboxd's own, not a member's.
RESERVED = {"films", "film", "lists", "list", "members", "settings", "search", "journal"}


def resolve(url: str, fetch) -> tuple[str | None, str | None]:
    """Return (author, film slug). Either may be None; neither is guessed."""

    response = fetch(url)
    location = response.headers.get("location") or response.headers.get("Location") or ""
    match = TARGET.match(location)
    if not match:
        return None, None
    author = match.group(1)
    if author.casefold() in RESERVED:
        return None, None
    slug = match.group(3) if match.group(2) == "film" else None
    return author, slug


def build_fetch(timeout: int):
    try:
        from curl_cffi import requests as curl_requests

        return lambda url: curl_requests.get(
            url, impersonate="chrome", allow_redirects=False, timeout=timeout
        )
    except ImportError:  # pragma: no cover - exercised only without curl_cffi
        import requests

        return lambda url: requests.get(url, allow_redirects=False, timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", help="Restrict to one profile.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pause", type=float, default=0.4, help="Seconds between requests.")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-resolve rows that already carry a resolution.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fetch = build_fetch(args.timeout)
    session = SessionLocal()
    try:
        query = session.query(MemberContentLike).filter(
            MemberContentLike.removed_at.is_(None)
        )
        if not args.refresh:
            query = query.filter(MemberContentLike.target_resolved_at.is_(None))
        if args.username:
            query = query.join(
                Profile, Profile.id == MemberContentLike.profile_id
            ).filter(Profile.username.ilike(args.username))
        if args.limit:
            query = query.limit(args.limit)
        rows = query.all()

        print(f"{len(rows)} like(s) to resolve")
        if args.dry_run:
            return 0

        resolved = unresolved = 0
        for index, row in enumerate(rows, start=1):
            try:
                author, slug = resolve(row.target_url or "", fetch)
            except Exception as exc:  # a dead link is data, not a crash
                print(f"  [{index}/{len(rows)}] {row.target_url}: {type(exc).__name__}")
                author, slug = None, None
            row.target_username = author
            row.target_film_slug = slug
            # Stamped even when nothing resolved, so a dead link is not retried
            # on every run.
            row.target_resolved_at = datetime.now(timezone.utc)
            if author:
                resolved += 1
            else:
                unresolved += 1
            if index % 25 == 0:
                session.commit()
            time.sleep(args.pause)
        session.commit()
        print(f"resolved {resolved}, left unresolved {unresolved}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

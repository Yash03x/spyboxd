"""Single-process, conservative Letterboxd RSS polling worker.

The worker is intentionally small: PostgreSQL stores due/backoff/lease state,
and the incremental service performs additions/upserts only.  It does not
restore the retired Celery/Redis or server-side full-HTML scraping paths.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time
from typing import Iterable, Optional

import requests

from database import SessionLocal
from database.models import Profile
from database.repository import AnalyticsRepository
from services.rss_incremental import (
    acquire_profile_feed_lease,
    due_profiles,
    poll_profile_feed,
)


LOGGER = logging.getLogger("spyboxd.rss")
STOP_REQUESTED = False


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.warning("Ignoring invalid %s=%r", name, raw)
        return default
    return value if value > 0 else default


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        LOGGER.warning("Ignoring invalid %s=%r", name, raw)
        return default
    return value if value > 0 else default


def _request_stop(_signum, _frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _profile_ids_due(*, usernames: Optional[Iterable[str]], limit: int) -> list[int]:
    requested = {
        username.strip().casefold()
        for username in usernames or []
        if username.strip()
    }
    with SessionLocal() as db:
        profiles = due_profiles(db, limit=limit)
        return [
            profile.id
            for profile in profiles
            if not requested or profile.username.casefold() in requested
        ]


def run_cycle(
    *,
    session: requests.Session,
    usernames: Optional[Iterable[str]] = None,
    interval_seconds: int,
    max_backoff_seconds: int,
    batch_size: int,
    pause_seconds: float,
) -> dict:
    profile_ids = _profile_ids_due(usernames=usernames, limit=batch_size)
    summary = {
        "due": len(profile_ids),
        "polled": 0,
        "updated": 0,
        "unchanged": 0,
        "overflow": 0,
        "failed": 0,
    }

    for index, profile_id in enumerate(profile_ids):
        if STOP_REQUESTED:
            break
        with SessionLocal() as db:
            if not acquire_profile_feed_lease(db, profile_id):
                continue
            profile = db.get(Profile, profile_id)
            if profile is None:
                continue
            result = poll_profile_feed(
                db,
                profile,
                session=session,
                interval_seconds=interval_seconds,
                max_backoff_seconds=max_backoff_seconds,
            )

        status = str(result.get("status") or "failed")
        summary["polled"] += 1
        if status == "updated":
            summary["updated"] += 1
        elif status in {"unchanged", "not_modified", "baseline_required"}:
            summary["unchanged"] += 1
        elif status in {"overflow", "full_sync_required"}:
            summary["overflow"] += 1
        else:
            summary["failed"] += 1

        LOGGER.info(
            "RSS @%s: %s (%s applied, %s observed)",
            result.get("username") or profile_id,
            status,
            result.get("changes", 0),
            result.get("items", 0),
        )

        # A shared 429 is a host-level signal; stop this cycle instead of
        # moving immediately to the next profile.
        if int(result.get("http_status") or 0) == 429:
            LOGGER.warning("Letterboxd returned 429; ending the current RSS cycle")
            break

        if index < len(profile_ids) - 1 and pause_seconds > 0:
            time.sleep(pause_seconds)

    if summary["updated"]:
        with SessionLocal() as db:
            AnalyticsRepository(db).refresh_dashboard_analytics_snapshot(
                group_limit=6,
                top_movies_limit=10,
            )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Poll tracked Letterboxd RSS feeds for recent public activity. "
            "A completed full profile sync is required first."
        )
    )
    parser.add_argument("--once", action="store_true", help="Run one due-profile cycle and exit.")
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Optional case-insensitive subset of tracked usernames.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    interval_seconds = _positive_int("SPYBOXD_RSS_POLL_INTERVAL_SECONDS", 600)
    sweep_seconds = _positive_int("SPYBOXD_RSS_SWEEP_SECONDS", 60)
    max_backoff_seconds = _positive_int("SPYBOXD_RSS_MAX_BACKOFF_SECONDS", 86400)
    batch_size = _positive_int("SPYBOXD_RSS_BATCH_SIZE", 50)
    pause_seconds = _positive_float("SPYBOXD_RSS_REQUEST_PAUSE_SECONDS", 3.0)
    user_agent = os.getenv(
        "SPYBOXD_RSS_USER_AGENT",
        "Spyboxd/1.0 (+https://spyboxd.com)",
    ).strip()

    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/rss+xml, application/xml;q=0.9",
            "User-Agent": user_agent,
        }
    )

    while not STOP_REQUESTED:
        summary = run_cycle(
            session=session,
            usernames=args.only,
            interval_seconds=interval_seconds,
            max_backoff_seconds=max_backoff_seconds,
            batch_size=batch_size,
            pause_seconds=pause_seconds,
        )
        LOGGER.info("RSS cycle complete: %s", summary)
        if args.once:
            return 1 if summary["failed"] else 0

        deadline = time.monotonic() + sweep_seconds
        while not STOP_REQUESTED and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Delivery path for Letterboxd's own crowd rating per film.

Letterboxd challenges datacenter IPs, which is why every Letterboxd read in this
repo happens on a residential machine and is then uploaded (``/upload/``). TMDB
enrichment can run on the production server because TMDB has no such
restriction; the Letterboxd rating backfill in ``services.letterboxd_ratings``
cannot, so it writes ``movies.letterboxd_average_rating`` into the *local*
database. This endpoint is how those values reach production.

A film's crowd rating is film-level and shared by every profile, so this carries
no per-profile data at all: one modest batch of ``(slug, average, count)`` rows
that any profile's comparison can then read.

Auth is deliberately the same trust boundary as ``/upload/``: ``main`` mounts
this router behind ``get_active_upload_user`` (ingestion token, or an enabled
Clerk admin), and the route additionally declares ``get_upload_user`` itself so
the token gate travels with the router even if the mount is ever rewritten.
``backend/tests/test_route_access_matrix.py`` pins the mounted dependency.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth import ClerkUser, get_upload_user
from database.connection import get_db
from database.models import Movie
from services.letterboxd_ratings import resolve_slug


LOGGER = logging.getLogger("spyboxd.film_ratings")

router = APIRouter(prefix="/api/films", tags=["film ratings"])

# One request must never be unbounded: the pusher chunks the library, and the
# whole catalogue is only a few thousand films.
MAX_BATCH_SIZE = 1000
# Letterboxd's scale. The column carries a matching CHECK constraint
# (``ck_movies_letterboxd_average_range``), so a value outside this range has to
# be rejected here rather than handed to the database as a 500.
MIN_AVERAGE_RATING = 0.0
MAX_AVERAGE_RATING = 5.0
# ``letterboxd_rating_count`` is a BIGINT with a non-negative CHECK. The most
# rated film on the site sits in the low millions, so anything past a trillion
# is a corrupt payload rather than a real count.
MAX_RATING_COUNT = 10**12


class FilmRatingEntry(BaseModel):
    """One film's crowd rating as scraped on the residential machine."""

    slug: str = Field(..., max_length=250)
    average_rating: Optional[float] = None
    rating_count: Optional[int] = None
    synced_at: Optional[datetime] = None


class FilmRatingBatch(BaseModel):
    ratings: List[FilmRatingEntry] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _movies_by_slug(db: Session, slugs: set[str]) -> Dict[str, List[Movie]]:
    """Load every film whose slug matches, case-insensitively, in one query."""

    if not slugs:
        return {}
    movies = (
        db.query(Movie)
        .filter(func.lower(Movie.letterboxd_slug).in_(sorted(slugs)))
        .all()
    )
    mapping: Dict[str, List[Movie]] = defaultdict(list)
    for movie in movies:
        mapping[(movie.letterboxd_slug or "").lower()].append(movie)
    return mapping


@router.post("/letterboxd-ratings")
def ingest_letterboxd_ratings(
    payload: FilmRatingBatch,
    db: Session = Depends(get_db),
    _user: ClerkUser = Depends(get_upload_user),
):
    """Apply a batch of locally scraped Letterboxd film ratings.

    Every count is per submitted entry, and ``updated + unmatched + skipped``
    always equals ``received``:

    * ``updated`` — matched a film by ``movies.letterboxd_slug`` (case
      insensitively) and wrote the average.
    * ``unmatched`` — production has never seen that film. Expected drift
      between the two databases, so it is reported, never fatal.
    * ``skipped`` — the entry carried nothing safely writable: no usable slug,
      an average outside Letterboxd's 0-5 scale, an impossible rating count, or
      a null average.

    A null average is "Letterboxd did not publish one", not zero, so it never
    overwrites a value production already holds — the same rule the local
    backfill applies in ``services.letterboxd_ratings``. A null ``rating_count``
    likewise leaves the stored count alone. ``synced_at`` records when the
    residential machine read the figure, falling back to the request time.
    """

    received = len(payload.ratings)
    request_time = datetime.now(timezone.utc)

    # (slug, average, count, synced_at) for entries worth writing.
    prepared: List[Tuple[str, float, Optional[int], datetime]] = []
    skipped = 0
    for entry in payload.ratings:
        slug = resolve_slug(entry.slug, None)
        average = entry.average_rating
        count = entry.rating_count
        usable = (
            slug is not None
            and average is not None
            # Written as a range test so NaN — which compares false against
            # everything — is skipped rather than stored.
            and MIN_AVERAGE_RATING <= average <= MAX_AVERAGE_RATING
            and (count is None or 0 <= count <= MAX_RATING_COUNT)
        )
        if not usable:
            skipped += 1
            continue
        prepared.append(
            (slug.lower(), float(average), count, _as_utc(entry.synced_at) or request_time)
        )

    matches = _movies_by_slug(db, {slug for slug, _, _, _ in prepared})

    updated = 0
    unmatched = 0
    for slug, average, count, synced_at in prepared:
        movies = matches.get(slug)
        if not movies:
            unmatched += 1
            continue
        for movie in movies:
            movie.letterboxd_average_rating = average
            if count is not None:
                movie.letterboxd_rating_count = count
            movie.letterboxd_rating_synced_at = synced_at
        updated += 1

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        # The payload is trusted-but-remote; its details never reach the client.
        LOGGER.exception("Letterboxd film rating batch failed to persist")
        raise HTTPException(status_code=500, detail="Failed to store Letterboxd film ratings")

    return {
        "received": received,
        "updated": updated,
        "unmatched": unmatched,
        "skipped": skipped,
    }

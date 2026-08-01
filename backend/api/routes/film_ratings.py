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

Auth is deliberately the same trust boundary as ``/upload/``: the route
declares ``get_active_upload_user`` (ingestion token, or an enabled Clerk
admin) directly, so the gate is visible on the route itself rather than
depending on how it happens to be mounted.
``backend/tests/test_route_access_matrix.py`` pins it.
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

from api.dependencies import get_active_upload_user
from auth import ClerkUser
from database.connection import get_db
from database.models import Movie
from services.letterboxd_ratings import BUCKET_KEYS, resolve_slug


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
    rating_distribution: Optional[Dict[str, int]] = None
    synced_at: Optional[datetime] = None


class FilmRatingBatch(BaseModel):
    ratings: List[FilmRatingEntry] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)


def _usable_distribution(
    distribution: Optional[Dict[str, int]]
) -> Optional[Dict[str, int]]:
    """Return the histogram if it is safe to store, otherwise ``None``.

    Every key has to be one of the ten half-star buckets the scraper emits, but
    *all ten* are not required: Letterboxd omits a bucket nobody has voted in,
    and films in the tracked library really do come back with nine or seven.
    Demanding a full ten here would drop those on the floor.

    Sizes are bounded like ``rating_count`` and may not be negative, since the
    column feeds a crowd-position share whose denominator is their sum. Pydantic
    has already made every value an ``int`` by the time this runs, so only the
    range is left to check here.
    """

    if not distribution:
        return None
    for key, size in distribution.items():
        if key not in BUCKET_KEYS:
            return None
        if not 0 <= size <= MAX_RATING_COUNT:
            return None
    return dict(distribution)


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
    _user: ClerkUser = Depends(get_active_upload_user),
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

    ``distributions_written`` and ``distributions_rejected`` are reported
    alongside, and sit outside the ``received`` identity on purpose: the
    histogram rides along with the average rather than replacing it, so a film
    can be ``updated`` while carrying no usable histogram.
    """

    received = len(payload.ratings)
    request_time = datetime.now(timezone.utc)

    # (slug, average, count, distribution, synced_at) for entries worth writing.
    prepared: List[
        Tuple[str, float, Optional[int], Optional[Dict[str, int]], datetime]
    ] = []
    skipped = 0
    distributions_rejected = 0
    for entry in payload.ratings:
        slug = resolve_slug(entry.slug, None)
        average = entry.average_rating
        count = entry.rating_count
        distribution = _usable_distribution(entry.rating_distribution)
        # A malformed histogram must not cost the film its average, which is the
        # primary payload and validated separately. Drop the histogram, keep the
        # average, and report the drop rather than swallowing it.
        if entry.rating_distribution is not None and distribution is None:
            distributions_rejected += 1
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
            (
                slug.lower(),
                float(average),
                count,
                distribution,
                _as_utc(entry.synced_at) or request_time,
            )
        )

    matches = _movies_by_slug(db, {slug for slug, _, _, _, _ in prepared})

    updated = 0
    unmatched = 0
    distributions_written = 0
    for slug, average, count, distribution, synced_at in prepared:
        movies = matches.get(slug)
        if not movies:
            unmatched += 1
            continue
        for movie in movies:
            movie.letterboxd_average_rating = average
            if count is not None:
                movie.letterboxd_rating_count = count
            # A null histogram is "this push carried none", not "the film has
            # none", so it never clears one production already holds.
            if distribution is not None:
                movie.letterboxd_rating_distribution = distribution
            movie.letterboxd_rating_synced_at = synced_at
        if distribution is not None:
            distributions_written += 1
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
        "distributions_written": distributions_written,
        "distributions_rejected": distributions_rejected,
    }

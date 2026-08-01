"""Watchlist insights: an unwatched list ranked by the circle's own verdict."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.profile_access import require_profile_access
from services.watchlist_insights import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    build_watchlist_insights,
)


router = APIRouter(prefix="/api", tags=["watchlist insights"])


@router.get("/profiles/{username}/watchlist-insights")
def get_watchlist_insights(
    username: str,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    # Providers are imported per country, so an unset region means "do not
    # claim anything about where this can be streamed".
    region: str | None = Query(default=None, min_length=2, max_length=2),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """What to watch next off this profile's watchlist, ranked by the group.

    Letterboxd keeps a watchlist as an undifferentiated list and can only ever
    annotate it with its own site-wide average. Every tracked profile's rating
    is already held locally, so each unwatched film here carries the average
    over the *other* members who have seen it, the number of them behind it,
    and who they were.

    Only films with no ``profile_films`` row for this profile are recommended,
    and a film needs at least one other rater to be ranked at all. ``coverage``
    reports the size of that unwatched pool, how much of it the group has rated
    and how much carries a Letterboxd crowd average, so a client can qualify a
    partial queue instead of presenting it as the whole watchlist.
    """

    profile = require_profile_access(db, user, username)
    return build_watchlist_insights(db, profile, limit=limit, region=region)

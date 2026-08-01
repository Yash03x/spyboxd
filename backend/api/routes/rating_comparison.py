"""Rating comparison: one profile's ratings against its circle, Letterboxd and TMDB."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.profile_access import require_profile_access
from services.rating_comparison import DEFAULT_LIMIT, MAX_LIMIT, build_rating_comparison


router = APIRouter(prefix="/api", tags=["rating comparison"])


@router.get("/profiles/{username}/rating-comparison")
def get_rating_comparison(
    username: str,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Whether this profile runs generous or harsh relative to its own circle.

    Every tracked profile's rating for the same film is already held locally, so
    each film carries a group average taken over the *other* profiles who rated
    it -- never over this one, which would correlate a member with themselves.
    Letterboxd can only ever show its own site-wide average, which is why this
    comparison does not exist there.

    ``summary`` also reports the same profile against Letterboxd's crowd average
    and TMDB's (halved from /10 onto the 5-point scale). The Letterboxd figures
    stay null until that backfill lands; everything else is unaffected.
    """

    profile = require_profile_access(db, user, username)
    return build_rating_comparison(db, profile, limit=limit)

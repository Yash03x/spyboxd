"""Obscurity index: how mainstream one profile's rated films are."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.obscurity import DEFAULT_LIMIT, MAX_LIMIT, build_obscurity_index
from services.profile_access import require_profile_access


router = APIRouter(prefix="/api", tags=["obscurity"])


@router.get("/profiles/{username}/obscurity")
def get_profile_obscurity(
    username: str,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """How mainstream this profile's taste is, in audience size.

    ``index.median_rating_count`` is the headline: the number of Letterboxd
    ratings behind the *typical* film this person rated. It is a median rather
    than a mean on purpose -- one blockbuster among five hundred arthouse films
    would move a mean by orders of magnitude and describe a taste nobody has.
    ``mean_rating_count`` sits beside it so that skew stays visible.

    ``percentile_vs_group`` places that median against every *other* tracked
    profile's median, as an obscurity percentile: 100 means every other tracked
    profile watches bigger films. ``lean`` is read straight off it, so the label
    and the number can never disagree, and both are null when there is no other
    profile to compare against.

    Letterboxd itself never shows any of this. It publishes a film's rating
    count on that film's page and never aggregates those counts across a
    member's history.

    Coverage is reported rather than papered over. Films the crowd-rating
    backfill has not reached are excluded from the median instead of counted as
    an audience of zero, and ``coverage.films_with_rating_count`` says how many
    of the profile's ``rated_films`` actually stood behind it.
    ``crowd_position`` additionally needs ``letterboxd_rating_distribution``
    and returns an empty list -- never null -- until that backfill is re-run
    with ``--refresh``.
    """

    profile = require_profile_access(db, user, username)
    return build_obscurity_index(db, profile, limit=limit)

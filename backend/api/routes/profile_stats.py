"""Profile statistics: Letterboxd's Patron-only stats page, recomputed locally."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.profile_access import require_profile_access
from services.profile_stats import build_profile_stats


router = APIRouter(prefix="/api", tags=["profile stats"])


@router.get("/profiles/{username}/stats")
def get_profile_stats(
    username: str,
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Viewing statistics computed from imported rows plus TMDB enrichment.

    Letterboxd gates its own stats page behind Patron membership, so scraping
    it reaches almost none of the tracked profiles. Enrichment already holds
    runtime, credits, countries, languages and release dates, so the same
    figures are derived here for every profile instead.

    ``coverage`` and ``totals.runtime_coverage`` qualify the answer: hours and
    people counts are summed only over films we actually hold data for, never
    extrapolated to the rest of the library. ``letterboxd_reported`` returns
    the scraped Patron figures verbatim when they exist, purely as a
    cross-check, and is null for every profile that was never scraped.
    """

    profile = require_profile_access(db, user, username)
    return build_profile_stats(db, profile)

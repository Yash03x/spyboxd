"""People: one person, two people, and what a rename would cost.

Every handler resolves its subject through the same access check the rest of
the analytics surface uses, so an untracked username is a 403 before any query
runs rather than an empty answer that looks like a quiet profile.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import Profile
from services.people import (
    build_decade_drift,
    build_favourites,
    build_member_card,
    build_pair_blind_spots,
    build_quiet,
    build_reach,
    build_rename_resilience,
    build_reviews_per_watch,
    build_rewatch_shifts,
    build_silent_fives,
    build_tag_overlap,
    build_unrated,
)
from services.profile_access import accessible_profiles, authorize_profile_usernames


router = APIRouter(prefix="/api", tags=["people"])


def _selected_profiles(
    db: Session, user: ClerkUser, requested: Optional[List[str]]
) -> List[Profile]:
    """Resolve an access-checked selection to Profile rows.

    Defined above the first decorated handler: a helper between
    ``@router.get(...)`` and its function binds the decorator to the helper and
    silently drops the route's auth dependency.
    """

    usernames = authorize_profile_usernames(db, user, requested)
    if not usernames:
        return []
    lowered = {username.casefold() for username in usernames}
    visible = accessible_profiles(db, user)
    return [profile for profile in visible if profile.username.casefold() in lowered]


def _subject(db: Session, user: ClerkUser, username: str) -> Profile:
    profiles = _selected_profiles(db, user, [username])
    if not profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That profile is not in your monitored set.",
        )
    return profiles[0]


@router.get("/people/{username}/unrated")
def get_unrated(
    username: str,
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Films they logged and never rated — the hole every comparison skips."""

    return build_unrated(db, _subject(db, user, username), limit=limit)


@router.get("/people/{username}/silent-fives")
def get_silent_fives(
    username: str,
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Top-of-scale ratings carrying no review text."""

    return build_silent_fives(db, _subject(db, user, username), limit=limit)


@router.get("/people/{username}/rewatch-shifts")
def get_rewatch_shifts(
    username: str,
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Films whose rating moved between two authoritative reads."""

    return build_rewatch_shifts(db, _subject(db, user, username), limit=limit)


@router.get("/people/{username}/favourites")
def get_favourites(
    username: str,
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """The four slots, plus every swap we have observed between reads."""

    return build_favourites(db, _subject(db, user, username))


@router.get("/people/{username}/member-card")
def get_member_card(
    username: str,
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Badge, pronouns, location, bio — and what of it is export-only."""

    return build_member_card(db, _subject(db, user, username))


@router.get("/people/quiet")
def get_quiet(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """How long each profile has been silent, against its own usual gap."""

    return build_quiet(db, _selected_profiles(db, user, profiles))


@router.get("/people/reviews-per-watch")
def get_reviews_per_watch(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """How often watching turns into writing, per profile."""

    return build_reviews_per_watch(db, _selected_profiles(db, user, profiles))


@router.get("/people/tag-overlap")
def get_tag_overlap(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Tags more than one selected profile independently invented."""

    return build_tag_overlap(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/people/decade-drift")
def get_decade_drift(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Average release year watched, per year of watching, per profile."""

    return build_decade_drift(db, _selected_profiles(db, user, profiles))


@router.get("/people/pair-blind-spots")
def get_pair_blind_spots(
    profiles: List[str] = Query(...),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Films the rest of the circle rates highly that neither of the pair logged."""

    pair = _selected_profiles(db, user, profiles[:2])
    circle = accessible_profiles(db, user)
    return build_pair_blind_spots(db, pair, circle, limit=limit)


@router.get("/people/rename-resilience")
def get_rename_resilience(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Which profiles survive a username change, and what one costs us."""

    return build_rename_resilience(db, _selected_profiles(db, user, profiles))


@router.get("/people/reach")
def get_reach(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Followers against following, from Letterboxd's own header figures."""

    return build_reach(db, _selected_profiles(db, user, profiles))

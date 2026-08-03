from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import Profile
from services.group_activity import (
    build_logging_lag,
    build_marathons,
    build_season_shape,
    build_weekday_rhythm,
)
from services.first_watches import build_first_watch_order, build_shared_firsts
from services.profile_changes import get_recent_profile_changes
from services.profile_access import accessible_profiles, authorize_profile_usernames


router = APIRouter(prefix="/api", tags=["activity"])


def _selected_profiles(
    db: Session, user: ClerkUser, requested: Optional[List[str]]
) -> List[Profile]:
    """Resolve an access-checked selection to Profile rows.

    Kept above the first decorated handler on purpose: defining a helper
    between ``@router.get(...)`` and its function binds the decorator to the
    helper instead, which silently drops the route's auth dependency.
    """

    usernames = authorize_profile_usernames(db, user, requested)
    if not usernames:
        return []
    lowered = {username.casefold() for username in usernames}
    visible = accessible_profiles(db, user)
    return [profile for profile in visible if profile.username.casefold() in lowered]


@router.get("/recent-changes")
def get_recent_changes(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    since: Optional[datetime] = Query(default=None),
    latest_sync_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Return source-backed changes detected by successful profile syncs."""

    selected_profiles = authorize_profile_usernames(db, user, profiles)
    if user.is_admin and profiles is None:
        selected_profile_ids = None
    else:
        visible_by_username = {
            profile.username: profile.id for profile in accessible_profiles(db, user)
        }
        selected_profile_ids = [
            visible_by_username[username]
            for username in selected_profiles
            if username in visible_by_username
        ]
    return get_recent_profile_changes(
        db,
        profile_ids=selected_profile_ids,
        limit=limit,
        since=since,
        latest_sync_only=latest_sync_only,
    )


@router.get("/activity/marathons")
def get_marathons(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Days one person in the selection logged several films."""

    return build_marathons(db, _selected_profiles(db, user, profiles), limit=limit)


@router.get("/activity/weekday")
def get_weekday_rhythm(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Watches by day of week across the selection."""

    return build_weekday_rhythm(db, _selected_profiles(db, user, profiles))


@router.get("/activity/season")
def get_season_shape(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Month of year, folded across every year the selection covers."""

    return build_season_shape(db, _selected_profiles(db, user, profiles))


@router.get("/activity/logging-lag")
def get_logging_lag(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Distance between when a film was watched and when it was logged."""

    return build_logging_lag(db, _selected_profiles(db, user, profiles))


@router.get("/insights/first-watch-order")
def get_first_watch_order(
    profiles: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Share of shared films where each profile was the earlier watch."""

    return build_first_watch_order(db, _selected_profiles(db, user, profiles))


@router.get("/insights/shared-firsts")
def get_shared_firsts(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Films two profiles watched for the first time on the same day."""

    return build_shared_firsts(db, _selected_profiles(db, user, profiles), limit=limit)

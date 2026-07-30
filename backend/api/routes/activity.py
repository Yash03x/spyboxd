from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from services.profile_changes import get_recent_profile_changes
from services.profile_access import accessible_profiles, authorize_profile_usernames


router = APIRouter(prefix="/api", tags=["activity"])


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

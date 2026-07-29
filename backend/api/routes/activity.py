from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.connection import get_db
from services.profile_changes import get_recent_profile_changes


router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/recent-changes")
def get_recent_changes(
    profiles: Optional[List[str]] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    since: Optional[datetime] = Query(default=None),
    latest_sync_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """Return source-backed changes detected by successful profile syncs."""

    return get_recent_profile_changes(
        db,
        usernames=profiles or None,
        limit=limit,
        since=since,
        latest_sync_only=latest_sync_only,
    )

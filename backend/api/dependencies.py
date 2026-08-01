"""Shared FastAPI dependencies for route modules.

``get_active_upload_user`` lived in ``main`` while only ``main`` used it, but a
route module cannot import from ``main`` — ``main`` imports the routers first,
so the reference does not exist yet. Applying the dependency at the
``include_router`` call worked around that and made the route's auth invisible
to anything inspecting the route itself. Keeping it here lets every route
declare its own trust boundary directly.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from auth import ClerkUser, get_upload_user
from database.connection import get_db
from services.profile_access import ensure_app_user


def get_active_upload_user(
    user: ClerkUser = Depends(get_upload_user),
    db: Session = Depends(get_db),
) -> ClerkUser:
    """Reject disabled Clerk admins while preserving ingestion-token uploads."""

    if user.user_id != "ingestion-token":
        ensure_app_user(db, user)
    return user

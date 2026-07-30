from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import ClerkUser, get_admin_user, get_current_user
from database.connection import get_db
from services.profile_access import (
    decide_profile_request,
    list_profile_catalog,
    list_profile_requests,
    provision_app_user_identity,
    track_profile_by_id,
    track_or_request_profile,
    untrack_profile,
)


router = APIRouter(tags=["profile access"])


class ProfileRequestCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class ProfileRequestDecision(BaseModel):
    status: Literal["approved", "rejected"]
    note: Optional[str] = Field(default=None, max_length=1000)


@router.get("/api/me")
def get_me(
    user: ClerkUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    identity = provision_app_user_identity(db, user)
    return {
        "user_id": user.user_id,
        "is_admin": user.is_admin,
        **identity,
    }


@router.get("/profiles/catalog")
def get_profile_catalog(
    search: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: ClerkUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_profile_catalog(
        db,
        user,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post("/profiles/{profile_id}/tracking")
def create_profile_tracking(
    profile_id: int,
    user: ClerkUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return track_profile_by_id(db, user, profile_id)


@router.get("/profiles/requests")
def get_my_profile_requests(
    request_status: Optional[str] = Query(default=None, alias="status"),
    user: ClerkUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "requests": list_profile_requests(
            db,
            user,
            request_status=request_status,
        )
    }


@router.post("/profiles/requests")
def create_profile_request(
    payload: ProfileRequestCreate,
    user: ClerkUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return track_or_request_profile(db, user, payload.username)


@router.delete("/profiles/{username}/tracking")
def delete_profile_tracking(
    username: str,
    user: ClerkUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not untrack_profile(db, user, username):
        raise HTTPException(status_code=404, detail="Profile is not tracked")
    return {
        "message": f"{username} is no longer tracked.",
        "status": "untracked",
        "username": username,
    }


@router.get("/admin/profile-requests")
def get_admin_profile_requests(
    request_status: Optional[str] = Query(default=None, alias="status"),
    user: ClerkUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    return {
        "requests": list_profile_requests(
            db,
            user,
            include_all=True,
            request_status=request_status,
        )
    }


@router.put("/admin/profile-requests/{request_id}")
def update_admin_profile_request(
    request_id: int,
    payload: ProfileRequestDecision,
    user: ClerkUser = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    request = decide_profile_request(
        db,
        user,
        request_id,
        decision=payload.status,
        note=payload.note,
    )
    return {"message": "Profile request updated.", "request": request}

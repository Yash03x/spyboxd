"""Export-only member surfaces: liked content, comments, and lost history."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import LostEntry, MemberComment, MemberContentLike
from services.profile_access import require_profile_access


router = APIRouter(prefix="/api", tags=["member archive"])


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


@router.get("/profiles/{username}/archive")
def get_member_archive(
    username: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
):
    """Surfaces that exist only in official account exports.

    Liked reviews and lists carry just a boxd.it URL (Letterboxd does not
    name the author or target in the export), comments carry their own HTML,
    and lost entries are diary rows, reviews, comments, and deleted-list films
    whose target no longer resolves on Letterboxd.
    """
    profile = require_profile_access(db, user, username)

    likes = (
        db.query(MemberContentLike)
        .filter(
            MemberContentLike.profile_id == profile.id,
            MemberContentLike.removed_at.is_(None),
        )
        .order_by(MemberContentLike.liked_date.desc().nullslast(), MemberContentLike.id.desc())
        .limit(limit)
        .all()
    )
    comments = (
        db.query(MemberComment)
        .filter(
            MemberComment.profile_id == profile.id,
            MemberComment.removed_at.is_(None),
        )
        .order_by(MemberComment.commented_date.desc().nullslast(), MemberComment.id.desc())
        .limit(limit)
        .all()
    )
    lost = (
        db.query(LostEntry)
        .filter(LostEntry.profile_id == profile.id)
        .order_by(LostEntry.entry_date.desc().nullslast(), LostEntry.id.desc())
        .limit(limit)
        .all()
    )

    return {
        "username": profile.username,
        "liked_reviews": [
            {"target_url": like.target_url, "liked_date": _iso(like.liked_date)}
            for like in likes
            if like.content_type == "review"
        ],
        "liked_lists": [
            {"target_url": like.target_url, "liked_date": _iso(like.liked_date)}
            for like in likes
            if like.content_type == "list"
        ],
        "comments": [
            {
                "target_url": comment.target_url,
                "commented_date": _iso(comment.commented_date),
                "comment_html": comment.comment_html,
            }
            for comment in comments
        ],
        "lost_entries": [
            {
                "lost_kind": entry.lost_kind,
                "entry_type": entry.entry_type,
                "title": entry.title,
                "release_year": entry.release_year,
                "source_url": entry.source_url,
                "entry_date": _iso(entry.entry_date),
                "watched_date": _iso(entry.watched_date),
                "rating": entry.rating,
                "body_text": entry.body_text,
            }
            for entry in lost
        ],
        "totals": {
            "liked_reviews": sum(1 for like in likes if like.content_type == "review"),
            "liked_lists": sum(1 for like in likes if like.content_type == "list"),
            "comments": len(comments),
            "lost_entries": len(lost),
        },
    }

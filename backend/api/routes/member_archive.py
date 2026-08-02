"""Export-only member surfaces: liked content, comments, and lost history."""
from __future__ import annotations

from html.parser import HTMLParser
from typing import List, Optional

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from auth import ClerkUser, get_current_user
from database.connection import get_db
from database.models import LostEntry, MemberComment, MemberContentLike
from services.profile_access import require_profile_access


router = APIRouter(prefix="/api", tags=["member archive"])


def _iso(value) -> Optional[str]:
    return value.isoformat() if value is not None else None


class _TextExtractor(HTMLParser):
    """Collect only text nodes, dropping markup and script/style contents."""

    _SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self._chunks).split())


def comment_plain_text(comment_html: Optional[str]) -> Optional[str]:
    """Render an export comment as plain text using a real HTML tokenizer.

    Export comments are Letterboxd-authored HTML. Regex tag-stripping is
    incomplete sanitization — nested constructions survive a single pass — so
    the API serves parsed text and clients never have to sanitize markup.
    """
    if not comment_html:
        return None
    parser = _TextExtractor()
    try:
        parser.feed(comment_html)
        parser.close()
    except Exception:
        return None
    return parser.text or None


def _liked_authors(likes) -> list[dict]:
    """Authors ranked by how often this member liked their writing.

    Unresolved likes are excluded rather than bucketed under an "unknown"
    author, and the caller is told how many were left out so a short list is
    read as partial resolution rather than as a short history.
    """

    counts: dict[str, int] = {}
    unresolved = 0
    for like in likes:
        if like.target_username:
            counts[like.target_username] = counts.get(like.target_username, 0) + 1
        else:
            unresolved += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"username": username, "likes": total, "unresolved_likes": unresolved}
        for username, total in ranked[:10]
    ]


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
            {
                "target_url": like.target_url,
                "liked_date": _iso(like.liked_date),
                "author": like.target_username,
                "film_slug": like.target_film_slug,
            }
            for like in likes
            if like.content_type == "review"
        ],
        "liked_lists": [
            {
                "target_url": like.target_url,
                "liked_date": _iso(like.liked_date),
                "author": like.target_username,
            }
            for like in likes
            if like.content_type == "list"
        ],
        # Whose writing this member actually rates. A like is an opaque
        # `boxd.it` token until its redirect is resolved, so 46 of them
        # rendered as the number 46; resolved, one author accounts for 12 of
        # the 44 that resolve and the next accounts for 2.
        "liked_authors": _liked_authors(likes),
        "comments": [
            {
                "target_url": comment.target_url,
                "commented_date": _iso(comment.commented_date),
                "comment_text": comment_plain_text(comment.comment_html),
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


@router.post("/profiles/{username}/archive/like-targets")
def resolve_like_targets(
    username: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: ClerkUser = Depends(get_current_user),
) -> dict:
    """Attach resolved authors to this profile's stored likes.

    A like is a `boxd.it` token until its redirect is followed, and Letterboxd
    blocks the datacenter addresses this API runs on, so the redirect can only
    be resolved from the residential machine that holds the export. This is the
    counterpart to that constraint: the answer is computed there and posted
    here, exactly as a scrape is.

    Only the three resolution columns are written. Nothing is created, removed,
    or soft-deleted, so a partial or repeated post cannot cost data -- unlike a
    bundle upload, where a present authoritative file removes what it omits.
    """

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resolving like targets requires an admin.",
        )
    profile = require_profile_access(db, user, username)
    resolutions = payload.get("resolutions")
    if not isinstance(resolutions, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Send {'resolutions': {url: {'author': str, 'film_slug': str|null}}}.",
        )

    likes = (
        db.query(MemberContentLike)
        .filter(
            MemberContentLike.profile_id == profile.id,
            MemberContentLike.removed_at.is_(None),
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    updated = 0
    for like in likes:
        entry = resolutions.get(like.target_url)
        if not isinstance(entry, dict):
            continue
        author = (entry.get("author") or "").strip()[:255]
        if not author:
            continue
        like.target_username = author
        slug = (entry.get("film_slug") or "").strip()[:250] or None
        like.target_film_slug = slug
        like.target_resolved_at = now
        updated += 1
    db.commit()
    return {
        "username": profile.username,
        "likes": len(likes),
        "resolved": updated,
        # Stated rather than implied: a caller that sent fewer resolutions than
        # there are likes should see that, not infer it from a smaller number.
        "still_unresolved": sum(1 for like in likes if not like.target_username),
    }
